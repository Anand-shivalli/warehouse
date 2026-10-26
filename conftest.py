"""Test setup. Tests run against a REAL PostgreSQL + pgvector database, because that is what production uses.

    export TEST_DATABASE_URL=postgresql://incident:pw@localhost:5432/incidents_test
    python -m pytest -q

SAFETY: the database name must end in '_test'. The schema is DROPPED and recreated at the start of every run.
Embeddings use the deterministic fake embedder (no Ollama needed) with 64 dimensions; PDFs are parsed with pypdf.
"""
import io
import json
import os
import tempfile
from datetime import datetime, timezone

import psycopg
import pytest

URL = os.getenv("TEST_DATABASE_URL")
if not URL:
    raise pytest.UsageError("Set TEST_DATABASE_URL, e.g. postgresql://incident:pw@localhost:5432/incidents_test "
                            "(an empty database whose name ends in _test; its schema is wiped each run).")
if not psycopg.conninfo.conninfo_to_dict(URL).get("dbname", "").endswith("_test"):
    raise pytest.UsageError("TEST_DATABASE_URL must point at a database whose name ends in '_test' (its schema is dropped).")

TMP = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=URL, INCIDENT_SEED=f"{TMP}/seed.json", INCIDENT_STORAGE=f"{TMP}/storage", MAX_UPLOAD_MB="1",
                  EMBEDDER="fake", EMBED_DIM="64", PARSER="pypdf", OCR="0")

with psycopg.connect(URL, autocommit=True) as _c:
    _c.execute("DROP SCHEMA public CASCADE")
    _c.execute("CREATE SCHEMA public")

T = datetime.now(timezone.utc).isoformat()
SEED = {"generated_at": T,
        "documents": [{"document_id": "SOP-014", "title": "Spill", "type": "SOP", "revision": "C", "status": "Effective",
                       "effective_from": "2026-03-01", "ingestion": "Indexed", "pages": 12},
                      {"document_id": "SOP-030", "title": "Fire", "type": "SOP", "revision": "A", "status": "Draft",
                       "effective_from": None, "ingestion": "Processing", "pages": 14},
                      {"document_id": "ROHS-2291", "title": "Voltrex", "type": "RoHS", "revision": "A", "status": "Pending verification",
                       "effective_from": "2026-08-02", "ingestion": "Needs review", "pages": 3, "warning": "Exemption field extracted with low confidence."}],
        "incidents": [
            {"incident_id": "INC-1047", "title": "Spill", "priority": "P2", "status": "in_review", "incident_type": "Spill",
             "source": "worker", "site_id": "S", "zone_id": "Bay 4", "equipment_id": "d", "assigned_to": "P", "occurred_at": T,
             "received_at": T, "affected": ["Bay 4"], "classification": {"category": "near_miss", "confidence": 0.91, "flags": []},
             "evidence": [{"asset_id": "AST-1", "type": "photo", "name": "p.jpg", "size": "1 MB", "checksum": "abc", "captured_at": T, "uploaded_at": T, "uploader": "w"}],
             "detections": [], "transcript": [{"t": "0:01", "speaker": "S0", "text": "hi"}],
             "locations": [{"source_type": "Photo EXIF", "method": "EXIF GPS", "lat": 39.96, "lon": -83.0, "accuracy_m": 8, "captured_at": T, "validation": "valid"}],
             "runs": [{"run_id": "RUN-1047A", "agent": "A", "status": "completed", "started_at": T, "duration_s": 9}],
             "retrievals": [{"query": "q", "hits": [{"doc": "SOP-014", "rev": "C", "section": "s", "page": 3, "score": 0.8}]}],
             "report": {"report_id": "RPT-1047", "version": 1, "review_status": "in_review", "generated_by": "x", "summary": "s", "observed": ["a"],
                        "interpretation": [], "unknowns": [], "recommendations": [], "citations": [], "reviewed_by": None, "review_note": None},
             "audit": [{"actor": "Worker app", "action": "Incident created", "at": T}]},
            # fields the real mock.js omits for some incidents: no conf/flags, audit entry without actor
            {"incident_id": "INC-1045", "title": "No report", "priority": "P3", "status": "new", "incident_type": "PPE violation", "source": "edge",
             "zone_id": "Dock B", "occurred_at": T, "received_at": T, "affected": [], "evidence": [], "locations": [],
             "audit": [{"action": "Incident created", "at": T}]}]}
json.dump(SEED, open(os.environ["INCIDENT_SEED"], "w"))

from fastapi import FastAPI                      # noqa: E402
from fastapi.testclient import TestClient        # noqa: E402

import incident_routes                           # noqa: E402
import incident_store                            # noqa: E402

incident_store.init_db()
_app = FastAPI()
_app.include_router(incident_routes.router)


@pytest.fixture(scope="session")
def client():
    return TestClient(_app)


def make_pdf(pages):
    """pages: list of pages, each a list of text lines. Returns PDF bytes (reportlab is a test-only dependency)."""
    reportlab = pytest.importorskip("reportlab.pdfgen.canvas")
    buf = io.BytesIO()
    cv = reportlab.Canvas(buf)
    for lines in pages:
        y = 800
        for ln in lines:
            cv.drawString(50, y, ln)
            y -= 16 if ln else 10
        cv.showPage()
    cv.save()
    return buf.getvalue()


@pytest.fixture(scope="session")
def pdf():
    return make_pdf


def upload_doc(client, doc_id, rev, data, typ="SOP", title="Doc", name="d.pdf"):
    return client.post("/api/documents", data={"document_id": doc_id, "type": typ, "title": title, "revision": rev},
                       files={"file": (name, io.BytesIO(data), "application/pdf")})


def doc_row(client, doc_id, rev):
    return next(d for d in client.get("/api/documents").json() if d["document_id"] == doc_id and d["revision"] == rev)
