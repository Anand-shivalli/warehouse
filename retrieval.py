"""Retrieval over indexed documents (Part B). Plain code, no LLM.

search():       hybrid = vector similarity + full-text, merged with reciprocal rank fusion (RRF).
                Only revisions that are Effective AND Indexed, inside their effective dates, and valid for the site.
lookup_rohs():  exact supplier / part-number lookup over HUMAN-VERIFIED RoHS records. Facts only, never a verdict.
run_retrieval(): builds queries from the pipeline state and returns the state update the RetrievalStep agent writes.

If the embedder is down, search() falls back to full-text only and says so (degraded). It never raises for "no results".
"""
import logging
import os
import re
from datetime import date

import db
from embedder import get_embedder

log = logging.getLogger("retrieval")
RRF_K = 60
CANDIDATES = 20
MAX_CONTEXT_CHARS = 6000
EMPTY_CONTEXT = "No company documents were retrieved for this incident."

_ELIGIBLE = """d.status = 'Effective' AND d.ingestion = 'Indexed' AND d.document_type = ANY(%(types)s)
  AND (d.effective_from IS NULL OR d.effective_from <= current_date)
  AND (d.effective_to IS NULL OR d.effective_to >= current_date)
  AND (%(site)s::text IS NULL OR d.applies_to_sites IS NULL OR %(site)s = ANY(d.applies_to_sites))"""
_COLS = "c.chunk_id, c.section_title, c.page_start, c.content, d.document_id, d.revision, d.title, d.document_type"


def _vec(v):
    return "[" + ",".join(f"{x:.7g}" for x in v) + "]"


def _or_query(text: str) -> str:
    """'drum leak forklift' -> 'drum | leak | forklift' (a long narrative must not require every word to match)."""
    words = []
    for w in re.findall(r"[A-Za-z0-9]{3,}", text.lower()):
        if w not in words:
            words.append(w)
    return " | ".join(words[:24])


def search(query: str, doc_types, site=None, k=4, embedder=None):
    """Returns (hits, info). Each hit: chunk_id, doc, rev, title, doc_type, section, page, score (cosine similarity or None),
    lexical (matched the text search), text. info = {"degraded": None | reason}."""
    params = {"types": list(doc_types), "site": site}
    info = {"degraded": None}
    vec_rows = []
    try:
        qv = (embedder or get_embedder()).embed_query(query)
        with db.conn() as c:
            vec_rows = c.execute(
                f"SELECT {_COLS}, 1 - (c.embedding <=> %(q)s::vector) AS sim FROM document_chunks c JOIN documents d ON d.id=c.doc_id "
                f"WHERE {_ELIGIBLE} ORDER BY c.embedding <=> %(q)s::vector LIMIT {CANDIDATES}", {**params, "q": _vec(qv)}).fetchall()
    except Exception as e:                                   # Ollama down, dimension mismatch...: keep going on text search
        info["degraded"] = f"vector search unavailable ({type(e).__name__}); text search only"
        log.warning("vector search failed: %s", e)
    fts_rows = []
    tq = _or_query(query)
    if tq:
        with db.conn() as c:
            fts_rows = c.execute(
                f"SELECT {_COLS}, ts_rank_cd(c.tsv, q.q) AS r FROM document_chunks c JOIN documents d ON d.id=c.doc_id, "
                f"to_tsquery('english', %(tq)s) q(q) WHERE {_ELIGIBLE} AND c.tsv @@ q.q ORDER BY r DESC LIMIT {CANDIDATES}",
                {**params, "tq": tq}).fetchall()
    fused = {}
    for rows, tag in ((vec_rows, "v"), (fts_rows, "f")):
        for rank, r in enumerate(rows, start=1):
            h = fused.setdefault(r["chunk_id"], {"row": r, "rrf": 0.0, "sim": None, "lexical": False})
            h["rrf"] += 1.0 / (RRF_K + rank)
            if tag == "v":
                h["sim"] = float(r["sim"])
            else:
                h["lexical"] = True
    hits = []
    for h in sorted(fused.values(), key=lambda x: -x["rrf"])[:k]:
        r = h["row"]
        hits.append({"chunk_id": r["chunk_id"], "doc": r["document_id"], "rev": r["revision"], "title": r["title"],
                     "doc_type": r["document_type"], "section": r["section_title"], "page": r["page_start"],
                     "score": round(h["sim"], 2) if h["sim"] is not None else None, "lexical": h["lexical"], "text": r["content"]})
    return hits, info


def lookup_rohs(part_number: str, supplier: str | None = None):
    """Verified RoHS declarations for a part. `expired` is date arithmetic on valid_until, not a compliance judgement.
    `unverified_candidates` counts extracted records no human has verified yet (they are NOT used as evidence)."""
    with db.conn() as c:
        rows = c.execute(
            "SELECT r.*, d.document_id, d.revision FROM rohs_records r JOIN documents d ON d.id=r.doc_id "
            "WHERE d.status='Effective' AND lower(r.part_number)=lower(%s) AND (%s::text IS NULL OR lower(r.supplier)=lower(%s)) "
            "ORDER BY r.declaration_date DESC NULLS LAST", (part_number, supplier, supplier)).fetchall()
    today = date.today()
    verified = [r for r in rows if r["validation_status"] == "Verified"]
    return {"part_number": part_number, "supplier": supplier, "found": bool(verified),
            "unverified_candidates": sum(1 for r in rows if r["validation_status"] == "Pending verification"),
            "records": [{"doc": r["document_id"], "rev": r["revision"], "supplier": r["supplier"], "part_number": r["part_number"],
                         "declaration_date": str(r["declaration_date"]) if r["declaration_date"] else None,
                         "valid_until": str(r["valid_until"]) if r["valid_until"] else None,
                         "expired": (r["valid_until"] < today) if r["valid_until"] else None,
                         "exemptions": r["exemptions"], "page": r["source_page"]} for r in verified]}


def format_context(hits) -> str:
    if not hits:
        return EMPTY_CONTEXT
    out, used = [], 0
    for h in hits:
        body = h["text"].strip()[:1200]
        block = f"[{h['sid']}] {h['doc_type']} {h['doc']} rev {h['rev']} - {h['section'] or 'untitled section'} (p.{h['page']})\n{body}"
        if used + len(block) > MAX_CONTEXT_CHARS:
            break
        out.append(block)
        used += len(block)
    return "\n\n".join(out)


def _s(v):
    return v if isinstance(v, str) else ""


def build_query(state: dict) -> str:
    """Deterministic query text from what the earlier agents produced."""
    ext, vis, cat = state.get("extraction_result") or {}, state.get("vision_result") or {}, state.get("category_result") or {}
    parts = []
    hz = _s(vis.get("hazard_type"))
    if hz and hz != "not available":
        parts.append(hz)
    parts += [_s(ext.get("narrative_summary"))[:400], _s(ext.get("treatment_described"))[:150], _s(vis.get("description"))[:200],
              _s(cat.get("category")).replace("_", " ")]
    return " ".join(p for p in parts if p).strip()


# (label, document types, hits wanted, must the hit also match the text search?)
PLAN = [("SOP", ["SOP"], 4, False), ("Guideline", ["Guideline"], 3, False), ("RoHS", ["RoHS"], 2, True)]


def empty_delta(status: str) -> dict:
    return {"retrieved_context": EMPTY_CONTEXT, "retrieval_hits": [], "retrieval_log": [], "retrieval_status": status}


def run_retrieval(state: dict, site=None, embedder=None) -> dict:
    """State update for the pipeline. retrieved_context ALWAYS exists, because the agent prompts reference it."""
    site = site or os.getenv("SITE_ID", "WH-07 Columbus")     # same default as incident_store.SITE
    query = build_query(state)
    if not query:
        return empty_delta("skipped: nothing to search with")
    hits, log_events, notes = [], [], []
    for label, types, k, need_lexical in PLAN:
        got, info = search(query, types, site=site, k=k, embedder=embedder)
        if need_lexical:                       # RoHS passages are shown only on an actual word match, never on similarity alone
            got = [h for h in got if h["lexical"]]
        if info["degraded"]:
            notes.append(info["degraded"])
        log_events.append({"query": f"[{label}] {query[:200]}",
                           "hits": [{k_: h[k_] for k_ in ("doc", "rev", "section", "page", "score")} for h in got]})
        hits += got
    seen, uniq = set(), []
    for h in hits:
        if h["chunk_id"] not in seen:
            seen.add(h["chunk_id"])
            uniq.append(h)
    for i, h in enumerate(uniq, start=1):
        h["sid"] = f"S{i}"
    status = "ok" if not notes else "degraded: " + "; ".join(sorted(set(notes)))
    return {"retrieved_context": format_context(uniq), "retrieval_hits": uniq, "retrieval_log": log_events, "retrieval_status": status}
