"""Incident API checks against real PostgreSQL. See conftest.py for setup. Run: python -m pytest -q"""
import hashlib
import io

import psycopg
import pytest

import incident_store as store
from conftest import doc_row, upload_doc


def test_seed_loaded_and_shape(client):
    r = client.get("/api/incidents").json()
    assert {i["incident_id"] for i in r} >= {"INC-1047", "INC-1045"}
    d = client.get("/api/incidents/INC-1047").json()
    for k in ("evidence", "detections", "transcript", "locations", "runs", "retrievals", "report", "audit", "classification", "affected"):
        assert k in d
    assert d["report"]["observed"] == ["a"] and d["classification"]["category"] == "near_miss"
    assert d["retrievals"][0]["hits"][0]["doc"] == "SOP-014"
    assert isinstance(d["received_at"], str) and "T" in d["received_at"]                 # ISO strings, as the UI expects
    assert client.get("/api/incidents/NOPE").status_code == 404
    # seed rows with missing optional fields loaded (no conf/flags, audit without actor)
    odd = client.get("/api/incidents/INC-1045").json()
    assert odd["classification"] is None and odd["audit"][0]["actor"] == "system"


def test_coordinates_masked_by_role_and_view_logged(client):
    d = client.get("/api/incidents/INC-1047", headers={"X-Role": "worker"}).json()
    assert d["locations"][0]["lat"] is None and d["locations"][0]["restricted"]
    assert client.get("/api/incidents/INC-1047").json()["locations"][0]["lat"] == 39.96
    assert any(a["action"] == "Viewed precise location" for a in store.get_incident("INC-1047", log_access=False)["audit"])
    assert client.get("/api/incidents", headers={"X-Role": "worker"}).json()[0]["locations"][0]["lat"] is None


def test_review_flow_and_guards(client):
    u = "/api/incidents/INC-1047/review"
    assert client.post(u, json={"action": "reject", "comment": " "}).status_code == 400
    assert client.post(u, json={"action": "close"}).status_code == 409
    assert client.post("/api/incidents/INC-1045/review", json={"action": "start_review"}).status_code == 409   # no report
    assert client.post(u, json={"action": "approve", "comment": "ok"}).json()["report"]["review_status"] == "approved"
    assert client.post(u, json={"action": "close"}).json()["status"] == "closed"
    assert client.post(u, json={"action": "approve"}).status_code == 409
    assert client.post(u, json={"action": "bogus"}).status_code == 422


def test_create_incident_ids_increment(client):
    a = client.post("/api/incidents", json={"title": "T", "zone": "Dock A", "type": "Fall"})
    b = client.post("/api/incidents", json={"title": "T2", "zone": "Dock A", "type": "Fall"})
    assert a.status_code == 201 and int(b.json()["incident_id"][4:]) == int(a.json()["incident_id"][4:]) + 1
    assert client.post("/api/incidents", json={"title": "", "zone": "x", "type": "y"}).status_code == 422


def test_session_correlation_and_evidence_upload(client):
    s = client.post("/api/incidents/INC-1047/sessions").json()["reporting_session_id"]
    other = client.post("/api/incidents/INC-1045/sessions").json()["reporting_session_id"]
    data = b"\xff\xd8fakejpeg" * 100
    up = lambda inc, sid, name="a.jpg", payload=data, typ="photo", cap=None: client.post(
        f"/api/incidents/{inc}/evidence", data={"asset_type": typ, "reporting_session_id": sid, **({"captured_at": cap} if cap else {})},
        files={"file": (name, io.BytesIO(payload), "image/jpeg")})
    assert up("INC-1047", other).status_code == 422                       # session belongs to another incident
    assert up("INC-1047", "no-such-session").status_code == 422
    assert up("INC-1047", s, name="x.exe").status_code == 400
    assert up("INC-1047", s, typ="weird").status_code == 400
    assert up("INC-1047", s, payload=b"").status_code == 400
    assert up("INC-1047", s, cap="not-a-date").status_code == 422
    assert up("INC-1047", s, payload=b"0" * (1024 * 1024 + 1)).status_code == 413
    assert not list((store.STORAGE_DIR / "evidence" / "INC-1047").glob("*.part"))   # temp files cleaned
    r = up("INC-1047", s, name="../../etc/passwd.jpg", cap="2026-01-01T10:00:00")  # naive timestamp is taken as UTC
    assert r.status_code == 201, r.text
    a = r.json()
    assert a["checksum"] == hashlib.sha256(data).hexdigest() and a["has_file"] and "/" not in a["name"]
    dl = client.get(f"/api/incidents/INC-1047/evidence/{a['asset_id']}/download")
    assert dl.status_code == 200 and dl.content == data
    assert client.get(f"/api/incidents/INC-1045/evidence/{a['asset_id']}/download").status_code == 404   # wrong incident
    assert client.get("/api/incidents/INC-1047/evidence/AST-1/download").status_code == 404              # metadata-only seed asset
    assert client.post(f"/api/incidents/INC-1047/sessions/{s}/close").json()["status"] == "closed"
    assert up("INC-1047", s).status_code == 409                           # closed session


def test_location_validation_and_provenance(client):
    p = "/api/incidents/INC-1047/locations"
    assert client.post(p, json={"source_type": "Mobile GPS", "lat": 95, "lon": 0}).status_code == 422
    assert client.post(p, json={"source_type": "Mobile GPS", "lat": 10}).status_code == 400
    assert client.post(p, json={"source_type": "Mobile GPS", "lat": 10, "lon": 10, "accuracy_m": -1}).status_code == 422
    assert client.post(p, json={"source_type": "Mobile GPS", "asset_id": "AST-nope"}).status_code == 422
    assert client.post(p, json={"source_type": "Mobile GPS", "lat": 10, "lon": 10, "captured_at": "garbage"}).status_code == 422
    assert client.post(p, json={"source_type": "Mobile GPS", "lat": 10, "lon": 10, "accuracy_m": 5}).json()["validation"] == "valid"
    assert client.post(p, json={"source_type": "Mobile GPS", "lat": 10, "lon": 10, "captured_at": "2020-01-01T00:00:00+00:00"}).json()["validation"] == "stale"
    assert client.post(p, json={"source_type": "Mobile GPS", "lat": 10, "lon": 10, "captured_at": "2020-01-01T00:00:00"}).json()["validation"] == "stale"   # naive = UTC, no crash
    assert len(store.get_incident("INC-1047", log_access=False)["locations"]) >= 4   # conflicting observations appended, never overwritten


def test_documents_versioning(client, pdf):
    data = pdf([["1 Purpose", "Spill response steps."]])
    assert upload_doc(client, "SOP-014", "C", data).status_code == 409                # duplicate revision
    assert upload_doc(client, "SOP-014", "D", b"x", name="s.txt").status_code == 400
    assert upload_doc(client, "SOP-014", "D", data, typ="Memo").status_code == 400
    assert upload_doc(client, "bad id!", "A", data).status_code == 400
    r = upload_doc(client, "SOP-014", "D", data)
    assert r.status_code == 201 and r.json()["status"] == "Draft" and r.json()["ingestion"] == "Processing"
    assert doc_row(client, "SOP-014", "D")["ingestion"] == "Indexed"                  # background indexing finished
    assert client.post("/api/documents/SOP-014/D/status", json={"status": "Effective"}).status_code == 200
    docs = {d["revision"]: d for d in client.get("/api/documents").json() if d["document_id"] == "SOP-014"}
    assert docs["D"]["status"] == "Effective" and docs["C"]["status"] == "Superseded" and docs["C"]["effective_to"]   # history kept
    assert isinstance(docs["C"]["effective_from"], str)
    assert client.post("/api/documents/SOP-014/Z/status", json={"status": "Effective"}).status_code == 404


def test_audit_log_is_append_only(client):
    with psycopg.connect(__import__("os").environ["DATABASE_URL"]) as c:
        for sql in ("UPDATE audit_logs SET actor='x'", "DELETE FROM audit_logs"):
            with pytest.raises(psycopg.errors.RaiseException):
                c.execute(sql)
            c.rollback()


def test_pipeline_hook_and_overview(client):
    iid = store.create_from_pipeline({"category": "recordable_injury", "flags": ["OSHA_recordable"], "report": "R",
                                      "extraction": {"location": "Bay 4", "narrative_summary": "n"}, "vision": {"hazard_type": "Spill", "description": "d"},
                                      "signals": {"potential_severity": "high", "confidence": "high"}, "needs_human_review": True, "state": {"k": 1, "when": "2026"}}, "A")
    d = client.get(f"/api/incidents/{iid}").json()
    assert d["priority"] == "P1" and d["report"]["review_status"] == "draft" and d["report"]["unknowns"]
    assert client.post(f"/api/incidents/{iid}/review", json={"action": "start_review"}).json()["status"] == "in_review"
    o = client.get("/api/overview").json()
    assert set(o) == {"sparks", "resolved30d", "meanReview", "meanClose", "pipeline"}
    assert all(len(v) == 12 for v in o["sparks"].values())
    assert o["resolved30d"] >= 1 and o["meanReview"] != "n/a"
    assert any(p["name"] == "Document indexer" for p in o["pipeline"])


def test_concurrent_incident_ids_are_unique(client):
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(8) as ex:
        ids = list(ex.map(lambda i: client.post("/api/incidents", json={"title": f"c{i}", "zone": "Dock A", "type": "Fall"}).json()["incident_id"], range(16)))
    assert len(set(ids)) == 16


def test_unreachable_database_gives_a_clear_one_line_error(monkeypatch):
    import db
    monkeypatch.setattr(db, "database_url", lambda: "postgresql://incident:s3cret@127.0.0.1:9/nope")
    monkeypatch.setenv("DB_CONNECT_TIMEOUT", "2")
    old = db._pool; db._pool = None
    try:
        with pytest.raises(db.DatabaseUnavailable) as e:
            db.check_connection()
    finally:
        db._pool = old
    msg = str(e.value)
    assert "Cannot connect to PostgreSQL" in msg and "incident:***@" in msg and "s3cret" not in msg      # password never printed
