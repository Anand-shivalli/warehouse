"""Document ingestion worker (Document Ingestion sheet, steps 2-6; step 1 'register' is incident_store.register_document).

  parse (Docling / fallback) -> chunk -> embed (Ollama) -> store chunks + vectors + text-search columns
  -> for RoHS documents, propose candidate records for a compliance reviewer.

One document is processed at a time (Docling is memory-hungry on small machines). Re-running a document replaces its
chunks only after the new ones were built successfully, so a failed re-index never leaves a document unsearchable.
"""
import hashlib
import logging
import threading
from pathlib import Path

from psycopg.types.json import Jsonb

import db
import incident_store as store
import rag_config
import rohs_extract
from doc_parse import ParseError, parse_document
from embedder import EmbedError, get_embedder

log = logging.getLogger("doc_ingest")
_ingest_lock = threading.Lock()


def vec_literal(v) -> str:
    return "[" + ",".join(f"{x:.7g}" for x in v) + "]"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def _check_dim(embedder):
    """The chunks table was created with a fixed vector size; refuse to write vectors of another size."""
    have = db.vector_dim()
    if have is None:
        raise EmbedError("document_chunks table is missing; migrations have not run.")
    if have != embedder.dim:
        raise EmbedError(f"Embedding size mismatch: the table stores {have}-dim vectors but the embedder produces {embedder.dim}. "
                         "Set EMBED_DIM to match your model; if you changed models, recreate the table (see README).")


def mark_queued(doc_pk):
    with db.conn() as c:
        c.execute("UPDATE documents SET ingestion='Processing', ingest_stage='queued' WHERE id=%s", (doc_pk,))


def _fail(doc_pk, key, msg, actor):
    log.error("ingest failed for %s: %s", key, msg)
    with db.conn() as c:
        c.execute("UPDATE documents SET ingestion='Failed', ingest_stage='failed', warnings=%s WHERE id=%s", (Jsonb([msg]), doc_pk))
        store.audit(actor, "Document ingestion failed", msg[:300], entity_id=key, conn=c)
    return {"ok": False, "document": key, "error": msg}


def ingest_document(doc_pk, embedder=None, actor="Ingestion worker"):
    """Parse, chunk, embed and index one document revision. Never raises for document problems; returns a summary."""
    with _ingest_lock:
        return _ingest(doc_pk, embedder, actor)


def _ingest(doc_pk, embedder, actor):
    with db.conn() as c:
        d = c.execute("SELECT * FROM documents WHERE id=%s", (doc_pk,)).fetchone()
        if not d:
            raise store.StoreError("Document not found", 404)
        c.execute("UPDATE documents SET ingestion='Processing', ingest_stage='parsing' WHERE id=%s", (doc_pk,))
    key = f"{d['document_id']}@{d['revision']}"
    try:
        embedder = embedder or get_embedder()
        _check_dim(embedder)
        if not d["storage_key"]:
            raise ParseError("This document has no stored file to index.")
        path = store.STORAGE_DIR / d["storage_key"]
        if not path.is_file():
            raise ParseError("The original file is missing from storage.")
        if d["checksum"] and _sha256(path) != d["checksum"]:
            raise ParseError("Checksum mismatch: the stored file changed after upload.")

        parsed = parse_document(path)
        warnings = list(parsed.warnings)

        if not parsed.chunks:                      # keep any existing chunks rather than wipe a searchable document
            with db.conn() as c:
                c.execute("UPDATE documents SET ingestion='Needs review', ingest_stage='done', warnings=%s, parser=%s, parser_version=%s, "
                          "ocr_used=%s, pages=%s WHERE id=%s",
                          (Jsonb(warnings), parsed.parser, parsed.parser_version, parsed.ocr_used, parsed.pages, doc_pk))
                store.audit(actor, "Document parsed with no text", "; ".join(warnings)[:300], entity_id=key, conn=c)
            return {"ok": True, "document": key, "chunks": 0, "ingestion": "Needs review", "warnings": warnings}

        with db.conn() as c:
            c.execute("UPDATE documents SET ingest_stage='embedding' WHERE id=%s", (doc_pk,))
        vecs = embedder.embed_documents([ch.embed_text for ch in parsed.chunks], [ch.section for ch in parsed.chunks])
        if len(vecs) != len(parsed.chunks):
            raise EmbedError("Embedder returned the wrong number of vectors.")

        records, rwarn = ([], [])
        is_rohs = d["document_type"] == "RoHS"
        if is_rohs:
            records, rwarn = rohs_extract.extract_candidates(parsed.chunks)

        model = getattr(embedder, "model", rag_config.embed_model())
        with db.conn() as c:
            c.execute("DELETE FROM document_chunks WHERE doc_id=%s", (doc_pk,))
            with c.cursor() as cur:
                cur.executemany(
                    "INSERT INTO document_chunks (doc_id,chunk_index,section_title,page_start,page_end,content,embedding,embed_model,chunker_version) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s::vector,%s,%s)",
                    [(doc_pk, ch.index, ch.section, ch.page_start, ch.page_end, ch.content, vec_literal(v), model, rag_config.CHUNKER_VERSION)
                     for ch, v in zip(parsed.chunks, vecs)])
            if is_rohs:
                kept = c.execute("SELECT COUNT(*) AS n FROM rohs_records WHERE doc_id=%s AND validation_status='Verified'", (doc_pk,)).fetchone()["n"]
                if kept:                           # never overwrite a human-verified record
                    rwarn.append(f"{kept} verified RoHS record(s) were kept; automatic re-extraction was skipped.")
                    records = []
                else:
                    c.execute("DELETE FROM rohs_records WHERE doc_id=%s", (doc_pk,))
                for r in records:
                    c.execute(
                        "INSERT INTO rohs_records (doc_id,supplier,part_number,product_scope,declaration_date,valid_until,exemptions,source_page,"
                        "source_excerpt,extraction_confidence,field_confidence) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                        (doc_pk, r["supplier"], r["part_number"], r["product_scope"], r["declaration_date"], r["valid_until"],
                         Jsonb(r["exemptions"]), r["source_page"], r["source_excerpt"], r["extraction_confidence"], Jsonb(r["field_confidence"])))
                warnings += rwarn
            needs_review = bool(warnings) or (is_rohs and rohs_extract.needs_review(records, []))
            status = "Needs review" if needs_review else "Indexed"
            c.execute("UPDATE documents SET ingestion=%s, ingest_stage='done', warnings=%s, parser=%s, parser_version=%s, ocr_used=%s, pages=%s, "
                      "chunker_version=%s, embed_model=%s, indexed_at=now() WHERE id=%s",
                      (status, Jsonb(warnings), parsed.parser, parsed.parser_version, parsed.ocr_used, parsed.pages,
                       rag_config.CHUNKER_VERSION, model, doc_pk))
            store.audit(actor, "Document indexed", f"{len(parsed.chunks)} chunks via {parsed.parser}; {len(warnings)} warning(s)", entity_id=key, conn=c)
        return {"ok": True, "document": key, "chunks": len(parsed.chunks), "ingestion": status, "parser": parsed.parser,
                "pages": parsed.pages, "warnings": warnings, "rohs_records": len(records)}
    except (ParseError, EmbedError, store.StoreError) as e:
        return _fail(doc_pk, key, str(e), actor)
    except Exception as e:                           # unexpected: record it, keep the worker alive
        log.exception("unexpected ingest error for %s", key)
        return _fail(doc_pk, key, f"{type(e).__name__}: {e}", actor)


def requeue_stuck():
    """Startup recovery: documents left in 'Processing' (server stopped mid-ingest, or upload never started) are re-run."""
    with db.conn() as c:
        ids = [r["id"] for r in c.execute("SELECT id FROM documents WHERE ingestion='Processing' AND storage_key IS NOT NULL ORDER BY id")]
    for i in ids:
        ingest_document(i)
    return len(ids)


def list_chunks(doc_pk, limit=50, offset=0):
    with db.conn() as c:
        total = c.execute("SELECT COUNT(*) AS n FROM document_chunks WHERE doc_id=%s", (doc_pk,)).fetchone()["n"]
        rows = c.execute("SELECT chunk_id, chunk_index, section_title, page_start, page_end, content, embed_model, chunker_version "
                         "FROM document_chunks WHERE doc_id=%s ORDER BY chunk_index LIMIT %s OFFSET %s", (doc_pk, limit, offset)).fetchall()
    return {"total": total, "chunks": rows}


def health():
    """What the indexer would use right now. Used by GET /api/rag/health so setup problems are visible without reading logs."""
    import importlib.util
    out = {"embedder": rag_config.embedder_kind(), "embed_model": rag_config.embed_model(), "embed_dim": rag_config.embed_dim(),
           "table_dim": None, "embedder_ok": False, "embedder_error": None, "parser_pref": rag_config.parser_pref(),
           "docling_installed": importlib.util.find_spec("docling") is not None, "pypdf_installed": importlib.util.find_spec("pypdf") is not None,
           "ocr": rag_config.ocr_enabled()}
    try:
        out["table_dim"] = db.vector_dim()
        dim = get_embedder().ping()
        out["embedder_ok"] = True
        if out["table_dim"] and dim != out["table_dim"]:
            out["embedder_ok"] = False
            out["embedder_error"] = f"model returns {dim}-dim vectors but the table stores {out['table_dim']}"
    except Exception as e:
        out["embedder_error"] = str(e)
    return out


def reindex_all(actor="Reindex"):
    """Re-run ingestion for every document that has a stored file. Use after changing the embedding model
    (and recreating the chunks table), or after upgrading the parser/chunker."""
    with db.conn() as c:
        ids = [r["id"] for r in c.execute("SELECT id FROM documents WHERE storage_key IS NOT NULL ORDER BY id")]
    results = [ingest_document(i, actor=actor) for i in ids]
    return {"documents": len(ids), "ok": sum(1 for r in results if r.get("ok")), "failed": [r["document"] for r in results if not r.get("ok")]}


if __name__ == "__main__":
    import sys
    from dotenv import load_dotenv
    load_dotenv()
    store.init_db()
    try:
        if sys.argv[1:] == ["--all"]:
            print(reindex_all())
        elif len(sys.argv) == 3:
            print(ingest_document(store.doc_pk(sys.argv[1], sys.argv[2])))
        else:
            print("usage: python doc_ingest.py --all | python doc_ingest.py DOCUMENT_ID REVISION")
    finally:
        db.close_pool()
