"""Document ingestion (Part A) checks against real PostgreSQL + pgvector. See conftest.py for setup.

Tests run in file order and share one database: later RoHS tests reuse documents created by earlier ones, so run the whole
file (or the whole suite) rather than a single test in isolation."""
import io

import pytest

import db
import doc_ingest
import doc_parse
import incident_store as store
from conftest import doc_row, upload_doc
from embedder import EmbedError, FakeEmbedder

SOP = [["SOP-014 Chemical spill response", "", "1 Purpose", "This procedure explains spill response for chemical drums.", "",
        "2 Containment", "Wear gloves and goggles before approaching the spill.", "Use absorbent pads to contain the liquid."],
       ["3 Reporting", "Report every spill to the shift lead within 15 minutes.", "Part VX-220 must be isolated."]]


def pk(doc_id, rev):
    return store.doc_pk(doc_id, rev)


def chunks(doc_id, rev):
    with db.conn() as c:
        return c.execute("SELECT * FROM document_chunks WHERE doc_id=%s ORDER BY chunk_index", (pk(doc_id, rev),)).fetchall()


class Boom:
    dim, model = 64, "boom"
    def embed_documents(self, *a, **k): raise EmbedError("Ollama exploded")


def test_upload_indexes_chunks_with_pages_sections_and_vectors(client, pdf):
    r = upload_doc(client, "T-SOP-1", "A", pdf(SOP), title="Spill")
    assert r.status_code == 201
    row = doc_row(client, "T-SOP-1", "A")
    assert row["ingestion"] == "Indexed" and row["pages"] == 2 and row["parser"] == "pypdf" and not row["warning"]
    cs = chunks("T-SOP-1", "A")
    assert len(cs) >= 3
    sections = {c["section_title"] for c in cs}
    assert {"1 Purpose", "2 Containment", "3 Reporting"} <= sections                    # headings detected
    assert next(c for c in cs if c["section_title"] == "3 Reporting")["page_start"] == 2   # page numbers kept
    assert next(c for c in cs if c["section_title"] == "1 Purpose")["page_start"] == 1
    assert all(c["embed_model"] == "fake-hash" and c["chunker_version"] for c in cs)
    assert "Wear gloves" in next(c for c in cs if c["section_title"] == "2 Containment")["content"]


def test_vector_and_keyword_search_work_on_stored_chunks(client):
    pk_ = pk("T-SOP-1", "A")
    q = FakeEmbedder().embed_query("wear gloves goggles spill")
    with db.conn() as c:
        top = c.execute("SELECT section_title FROM document_chunks WHERE doc_id=%s ORDER BY embedding <=> %s::vector LIMIT 1",
                        (pk_, doc_ingest.vec_literal(q))).fetchone()
        stem = c.execute("SELECT section_title FROM document_chunks WHERE doc_id=%s AND tsv @@ plainto_tsquery('english', 'reporting spills')", (pk_,)).fetchall()
        exact = c.execute("SELECT section_title FROM document_chunks WHERE doc_id=%s AND tsv_exact @@ plainto_tsquery('simple', 'VX-220')", (pk_,)).fetchall()
    assert top["section_title"] == "2 Containment"                       # vector nearest neighbour
    assert [r["section_title"] for r in stem] == ["3 Reporting"]          # stemmed prose search
    assert [r["section_title"] for r in exact] == ["3 Reporting"]         # exact part-number token


def test_chunks_endpoint_paginates_without_vectors(client):
    r = client.get("/api/documents/T-SOP-1/A/chunks?limit=2").json()
    assert r["total"] >= 3 and len(r["chunks"]) == 2 and "embedding" not in r["chunks"][0]
    assert client.get("/api/documents/T-SOP-1/A/chunks?limit=0").status_code == 422
    assert client.get("/api/documents/NOPE/A/chunks").status_code == 404


def test_reindex_replaces_chunks_without_duplicates(client):
    before = {c["chunk_id"] for c in chunks("T-SOP-1", "A")}
    assert client.post("/api/documents/T-SOP-1/A/reindex").status_code == 202
    after = chunks("T-SOP-1", "A")
    assert len(after) == len(before) and not ({c["chunk_id"] for c in after} & before)
    assert [c["chunk_index"] for c in after] == list(range(len(after)))
    assert doc_row(client, "T-SOP-1", "A")["ingestion"] == "Indexed"


def test_embedder_failure_keeps_old_chunks_and_marks_failed(client):
    n = len(chunks("T-SOP-1", "A"))
    res = doc_ingest.ingest_document(pk("T-SOP-1", "A"), embedder=Boom())
    assert not res["ok"] and "exploded" in res["error"]
    row = doc_row(client, "T-SOP-1", "A")
    assert row["ingestion"] == "Failed" and "exploded" in row["warning"]
    assert len(chunks("T-SOP-1", "A")) == n                              # still searchable
    assert client.post("/api/documents/T-SOP-1/A/reindex").status_code == 202
    assert doc_row(client, "T-SOP-1", "A")["ingestion"] == "Indexed"      # recovers on retry


def test_embedding_size_mismatch_is_refused(client):
    res = doc_ingest.ingest_document(pk("T-SOP-1", "A"), embedder=FakeEmbedder(dim=32))
    assert not res["ok"] and "mismatch" in res["error"].lower()
    doc_ingest.ingest_document(pk("T-SOP-1", "A"))                        # restore


def test_tampered_file_fails_checksum(client, pdf):
    upload_doc(client, "T-SOP-2", "A", pdf([["1 Scope", "Original text."]]))
    with db.conn() as c:
        key = c.execute("SELECT storage_key FROM documents WHERE id=%s", (pk("T-SOP-2", "A"),)).fetchone()["storage_key"]
    (store.STORAGE_DIR / key).write_bytes(pdf([["1 Scope", "Altered text."]]))
    res = doc_ingest.ingest_document(pk("T-SOP-2", "A"))
    assert not res["ok"] and "checksum" in res["error"].lower()


def test_pdf_without_text_needs_review_and_keeps_existing_chunks(client, pdf):
    upload_doc(client, "T-SOP-3", "A", pdf([[]]))                         # a blank page
    row = doc_row(client, "T-SOP-3", "A")
    assert row["ingestion"] == "Needs review" and "No text" in row["warning"] and not chunks("T-SOP-3", "A")


def test_corrupt_pdf_fails_cleanly(client):
    upload_doc(client, "T-SOP-4", "A", b"this is not a pdf")
    row = doc_row(client, "T-SOP-4", "A")
    assert row["ingestion"] == "Failed" and row["warning"]


def test_auto_parser_falls_back_and_says_so(client, pdf, monkeypatch):
    monkeypatch.setenv("PARSER", "auto")
    upload_doc(client, "T-SOP-5", "A", pdf(SOP))
    row = doc_row(client, "T-SOP-5", "A")
    assert row["parser"] == "pypdf" and row["ingestion"] == "Needs review"          # degraded parse is flagged, not silent
    assert "fallback" in row["warning"].lower()


def test_forced_docling_without_it_working_fails_with_clear_message(client, pdf, monkeypatch):
    monkeypatch.setenv("PARSER", "docling")
    upload_doc(client, "T-SOP-6", "A", pdf(SOP))
    row = doc_row(client, "T-SOP-6", "A")
    # Either Docling really is installed and works here (then it indexed), or the message names Docling.
    assert row["ingestion"] == "Indexed" or "docling" in row["warning"].lower()


def test_docx_and_guideline_type(client):
    docx = pytest.importorskip("docx")
    d = docx.Document()
    d.add_heading("Hand hygiene", level=1)
    d.add_paragraph("Wash hands for twenty seconds after handling chemicals.")
    d.add_heading("First aid", level=1)
    d.add_paragraph("Rinse eyes for fifteen minutes.")
    buf = io.BytesIO(); d.save(buf)
    r = client.post("/api/documents", data={"document_id": "G-001", "type": "Guideline", "title": "Health", "revision": "1"},
                    files={"file": ("g.docx", io.BytesIO(buf.getvalue()), "application/octet-stream")})
    assert r.status_code == 201, r.text
    row = doc_row(client, "G-001", "1")
    assert row["type"] == "Guideline" and row["parser"] == "python-docx" and row["pages"] is None
    assert {c["section_title"] for c in chunks("G-001", "1")} == {"Hand hygiene", "First aid"}


def test_requeue_stuck_documents(client, pdf):
    reg = store.register_document(io.BytesIO(pdf(SOP)), "r.pdf", "T-SOP-7", "SOP", "Stuck", "A", None, "tester")   # registered, never indexed
    assert doc_row(client, "T-SOP-7", "A")["ingestion"] == "Processing"
    assert doc_ingest.requeue_stuck() >= 1
    assert doc_row(client, "T-SOP-7", "A")["ingestion"] == "Indexed" and reg["doc_pk"]


def test_docling_chunk_adapter_with_stub_objects():
    class P:  page_no = 0
    class It:
        def __init__(self, *pages): self.prov = [type("P", (), {"page_no": n}) for n in pages]
    class Meta:
        def __init__(self, heads, items): self.headings, self.doc_items = heads, items
    class Ch:
        def __init__(self, text, meta): self.text, self.meta = text, meta
    class FakeChunker:
        def chunk(self, dl_doc):
            yield Ch("body one", Meta(["A", "B"], [It(3, 2)]))
            yield Ch("   ", Meta(None, []))                                 # empty chunk is skipped
            yield Ch("body two", Meta(None, []))
        def contextualize(self, chunk): return "ctx " + chunk.text
    out = doc_parse.chunks_from_docling(FakeChunker(), object())
    assert [(c.index, c.section, c.page_start, c.page_end, c.embed_text) for c in out] == [
        (0, "A > B", 2, 3, "ctx body one"), (1, None, None, None, "ctx body two")]


def test_block_chunker_splits_long_text_and_never_mixes_sections(monkeypatch):
    monkeypatch.setenv("CHUNK_MAX_TOKENS", "50")                              # 200 chars
    long_sentence_text = " ".join(f"Sentence number {i} is here." for i in range(40))
    out = doc_parse.chunks_from_blocks([(1, "Alpha", True), (1, long_sentence_text, False), (2, "Beta", True), (2, "short body", False)])
    alpha = [c for c in out if c.section == "Alpha"]
    assert len(alpha) > 3 and all(len(c.content) <= 200 for c in alpha)
    assert [c.content for c in out if c.section == "Beta"] == ["short body"] and out[-1].page_start == 2
    assert [c.index for c in out] == list(range(len(out)))


# ---------------------------------------------------------------- RoHS
ROHS = [["RoHS Declaration of Conformity", "Supplier: Voltrex Ltd", "Part Number: VX-220", "Declaration Date: 2 August 2026",
         "Product scope: Power supply units", "Exemption 7(a) applies to lead in solder."]]


def test_rohs_candidates_extracted_with_source_page_and_pending_status(client, pdf):
    upload_doc(client, "ROHS-T1", "A", pdf(ROHS), typ="RoHS", title="Voltrex")
    recs = client.get("/api/rohs", params={"document_id": "ROHS-T1"}).json()
    assert len(recs) == 1
    r = recs[0]
    assert (r["supplier"], r["part_number"], r["declaration_date"], r["product_scope"]) == ("Voltrex Ltd", "VX-220", "2026-08-02", "Power supply units")
    assert r["exemptions"] == ["7(a)"] and r["source_page"] == 1 and r["validation_status"] == "Pending verification"
    assert r["extraction_confidence"] >= 0.9 and "compliant" not in str(r).lower()      # never a compliance verdict
    row = doc_row(client, "ROHS-T1", "A")
    assert row["status"] == "Pending verification" and row["ingestion"] == "Indexed"


def test_rohs_ambiguous_date_and_missing_fields_are_flagged_not_guessed(client, pdf):
    upload_doc(client, "ROHS-T2", "A", pdf([["Supplier: Acme", "Date: 03/04/2026", "Notes about exempt items only."]]), typ="RoHS")
    r = client.get("/api/rohs", params={"document_id": "ROHS-T2"}).json()[0]
    assert r["declaration_date"] is None and r["part_number"] is None and r["extraction_confidence"] < 0.5
    row = doc_row(client, "ROHS-T2", "A")
    assert row["ingestion"] == "Needs review" and "ambiguous" in row["warning"] and "No part number" in row["warning"]
    # a reviewer cannot verify an incomplete record without supplying the gaps
    assert client.post(f"/api/rohs/{r['rohs_record_id']}/verify", json={}).status_code == 422
    ok = client.post(f"/api/rohs/{r['rohs_record_id']}/verify", json={"part_number": "AC-9", "declaration_date": "2026-04-03", "note": "checked PDF p1"})
    assert ok.status_code == 200 and ok.json()["validation_status"] == "Verified" and ok.json()["verified_by"]
    assert client.post(f"/api/rohs/{r['rohs_record_id']}/verify", json={"declaration_date": "not-a-date"}).status_code == 422


def test_rohs_verify_reject_and_audit(client):
    rid = client.get("/api/rohs", params={"document_id": "ROHS-T1"}).json()[0]["rohs_record_id"]
    assert client.post(f"/api/rohs/{rid}/reject", json={"note": ""}).status_code == 422
    v = client.post(f"/api/rohs/{rid}/verify", json={"supplier": "Voltrex Ltd.", "note": "ok"}).json()
    assert v["validation_status"] == "Verified" and v["supplier"] == "Voltrex Ltd."
    assert client.post(f"/api/rohs/{rid}/verify", json={}).status_code == 409           # already verified, nothing to change
    assert client.post(f"/api/rohs/{rid}/reject", json={"note": "wrong supplier"}).json()["validation_status"] == "Rejected"
    assert client.post("/api/rohs/999999/verify", json={}).status_code == 404
    with db.conn() as c:
        acts = [r["action"] for r in c.execute("SELECT action FROM audit_logs WHERE entity_id=%s ORDER BY id", (f"rohs:{rid}",))]
    assert acts == ["RoHS record verified", "RoHS record rejected"]
    assert len(client.get("/api/rohs", params={"status": "Rejected"}).json()) >= 1


def test_reindex_never_overwrites_verified_rohs_records(client):
    rid = client.get("/api/rohs", params={"document_id": "ROHS-T2"}).json()[0]["rohs_record_id"]       # verified earlier
    client.post("/api/documents/ROHS-T2/A/reindex")
    recs = client.get("/api/rohs", params={"document_id": "ROHS-T2"}).json()
    assert [r["rohs_record_id"] for r in recs] == [rid] and recs[0]["part_number"] == "AC-9"          # corrections survived
    assert "verified RoHS record" in doc_row(client, "ROHS-T2", "A")["warning"]


def test_health_endpoint(client):
    h = client.get("/api/rag/health").json()
    assert h["embedder_ok"] and h["table_dim"] == 64 and h["embed_dim"] == 64 and h["pypdf_installed"]


def test_overview_flags_documents_needing_attention(client):
    o = client.get("/api/overview").json()
    ind = next(p for p in o["pipeline"] if p["name"] == "Document indexer")
    assert ind["state"] == "warn" and "need review" in ind["note"]


def test_ollama_client_errors_are_actionable(monkeypatch):
    import httpx
    from embedder import OllamaEmbedder
    e = OllamaEmbedder(model="embeddinggemma", url="http://127.0.0.1:9", dim=64)           # nothing listens on port 9
    with pytest.raises(EmbedError, match="Cannot reach Ollama"):
        e.embed_query("x")

    def fake_post(url, json, timeout):
        return httpx.Response(404, json={"error": "model not found"}, request=httpx.Request("POST", url))
    monkeypatch.setattr(httpx, "post", fake_post)
    with pytest.raises(EmbedError, match="ollama pull embeddinggemma"):
        e.embed_query("x")

    def wrong_dim(url, json, timeout):
        return httpx.Response(200, json={"embeddings": [[0.1] * 10 for _ in json["input"]]}, request=httpx.Request("POST", url))
    monkeypatch.setattr(httpx, "post", wrong_dim)
    with pytest.raises(EmbedError, match="EMBED_DIM"):
        e.embed_documents(["a"])


def test_embeddinggemma_prefixes_applied(monkeypatch):
    import httpx
    from embedder import OllamaEmbedder
    seen = {}

    def spy(url, json, timeout):
        seen["input"] = json["input"]
        return httpx.Response(200, json={"embeddings": [[0.0] * 64 for _ in json["input"]]}, request=httpx.Request("POST", url))
    monkeypatch.setattr(httpx, "post", spy)
    e = OllamaEmbedder(model="embeddinggemma", url="http://x", dim=64)
    e.embed_documents(["body"], ["Title"])
    assert seen["input"] == ["title: Title | text: body"]
    e.embed_query("what")
    assert seen["input"] == ["task: search result | query: what"]


def test_reindex_all_rebuilds_every_stored_document(client):
    before = {c["chunk_id"] for c in chunks("T-SOP-1", "A")}
    res = doc_ingest.reindex_all()
    assert res["documents"] >= 5 and "T-SOP-1@A" not in res["failed"]
    assert not ({c["chunk_id"] for c in chunks("T-SOP-1", "A")} & before)
