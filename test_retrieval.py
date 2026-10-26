"""Part B: retrieval, report validation, and the pipeline->store hook. Real Postgres, fake embedder (see conftest.py)."""
import sys
import types

import pytest

import db
import incident_store as store
import retrieval
from conftest import doc_row, upload_doc

# the validator module imports google.adk, which may be absent where tests run; stub just enough to import validate_report
try:
    import google.adk  # noqa: F401
except ImportError:
    for name in ("google", "google.adk", "google.adk.agents", "google.adk.events", "google.genai"):
        sys.modules.setdefault(name, types.ModuleType(name))
    sys.modules["google.adk.agents"].BaseAgent = type("BaseAgent", (), {})
    sys.modules["google.adk.events"].Event = sys.modules["google.adk.events"].Event = type("Event", (), {})
    sys.modules["google.adk.events"].EventActions = type("EventActions", (), {})
    sys.modules["google.genai"].types = types.SimpleNamespace()
    sys.modules["google"].genai = sys.modules["google.genai"]
import os  # noqa: E402
if not os.path.isdir("agents"):                      # running from the sandbox layout instead of the project root
    sys.path.insert(0, "anand-shivalli/warehouse")
from agents.report_validator import validate_report  # noqa: E402


@pytest.fixture
def docs(client, pdf):
    sop = pdf([["1 Drum handling", "Never roll a leaking drum. Isolate the area and call the supervisor.", "2 Forklift", "Keep loads low while travelling."]])
    gl = pdf([["1 Skin contact", "Rinse skin with water for fifteen minutes and seek medical help."]])
    rohs = pdf([["Supplier: Acme Parts", "Part number: AP-100", "Declaration date: 2026-01-15", "Valid until: 2027-01-15"]])
    with db.conn() as c:                                   # the database persists between tests: start each from a clean slate
        c.execute("DELETE FROM documents")
    for doc_id, typ, data in (("SOP-T1", "SOP", sop), ("GL-T1", "Guideline", gl), ("ROHS-T1", "RoHS", rohs)):
        assert upload_doc(client, doc_id, "A", data, typ=typ).status_code == 201
        assert doc_row(client, doc_id, "A")["ingestion"] in ("Indexed", "Needs review")
    return client


def _effective(client, doc_id):
    assert client.post(f"/api/documents/{doc_id}/A/status", json={"status": "Effective"}).status_code == 200


def test_only_effective_indexed_documents_are_retrieved(docs):
    assert retrieval.search("leaking drum", ["SOP"])[0] == []                  # Draft revisions are never retrieved
    _effective(docs, "SOP-T1")
    hits, info = retrieval.search("leaking drum isolate area", ["SOP"], k=3)
    assert hits and hits[0]["doc"] == "SOP-T1" and hits[0]["lexical"] and info["degraded"] is None
    assert retrieval.search("leaking drum", ["Guideline"])[0] == []            # document type filter
    assert retrieval.search("leaking drum", ["SOP"], site="Some Other Site")[0] != [] # no site restriction on this doc


def test_site_restriction_and_fallback_when_embedder_fails(docs):
    _effective(docs, "SOP-T1")
    with db.conn() as c:
        c.execute("UPDATE documents SET applies_to_sites=ARRAY['Site X'] WHERE document_id='SOP-T1'")
    assert retrieval.search("leaking drum", ["SOP"], site="Site Y")[0] == []
    assert retrieval.search("leaking drum", ["SOP"], site="Site X")[0]

    class Broken:
        def embed_query(self, t):
            raise ConnectionError("ollama down")
    hits, info = retrieval.search("leaking drum", ["SOP"], site="Site X", embedder=Broken())
    assert hits and "text search only" in info["degraded"]                     # still answers, and says it degraded


def test_run_retrieval_state_and_context(docs):
    for d in ("SOP-T1", "GL-T1"):
        _effective(docs, d)
    state = {"extraction_result": {"narrative_summary": "A drum was leaking near the dock and the area was isolated", "treatment_described": "none"},
             "vision_result": {"hazard_type": "chemical leak", "description": "leaking drum"}, "category_result": {"category": "near_miss"}}
    d = retrieval.run_retrieval(state, site="x")
    assert d["retrieval_status"] == "ok" and d["retrieval_hits"]
    assert [h["sid"] for h in d["retrieval_hits"]] == [f"S{i}" for i in range(1, len(d["retrieval_hits"]) + 1)]
    assert "[S1]" in d["retrieved_context"] and "SOP-T1" in d["retrieved_context"]
    assert all(set(h) >= {"doc", "rev", "section", "page", "score"} for e in d["retrieval_log"] for h in e["hits"])   # UI shape
    assert retrieval.run_retrieval({}, site="x")["retrieved_context"] == retrieval.EMPTY_CONTEXT      # nothing to search with
    assert "retrieved_context" in retrieval.empty_delta("unavailable: x")


def test_rohs_lookup_uses_only_verified_records(docs):
    _effective(docs, "ROHS-T1")
    with db.conn() as c:
        pk = c.execute("SELECT id FROM documents WHERE document_id='ROHS-T1'").fetchone()["id"]
        c.execute("DELETE FROM rohs_records WHERE doc_id=%s", (pk,))
        for part, status, until in (("AP-100", "Verified", "2999-01-01"), ("AP-200", "Pending verification", "2999-01-01"), ("AP-300", "Verified", "2000-01-01")):
            c.execute("INSERT INTO rohs_records (doc_id,supplier,part_number,declaration_date,valid_until,validation_status) "
                      "VALUES (%s,'Acme Parts',%s,'1999-01-01',%s,%s)", (pk, part, until, status))
    ok = retrieval.lookup_rohs("ap-100", "ACME parts")
    assert ok["found"] and ok["records"][0]["expired"] is False and ok["records"][0]["doc"] == "ROHS-T1"
    pend = retrieval.lookup_rohs("AP-200")
    assert pend["found"] is False and pend["unverified_candidates"] == 1 and pend["records"] == []   # extracted but unverified: not evidence
    assert retrieval.lookup_rohs("AP-300")["records"][0]["expired"] is True
    assert retrieval.lookup_rohs("NOPE")["found"] is False
    assert retrieval.lookup_rohs("AP-100", "Other Supplier")["found"] is False


GOOD = {"report_text": "A drum leaked.", "observed": ["Drum leaked"], "interpretation": ["near miss"], "unknowns": [],
        "recommendations": [{"action": "Isolate the area", "source_ids": ["S1"]}]}
HITS = [{"sid": "S1"}]


def test_validator_checks():
    assert validate_report(GOOD, HITS)["review_pass"]
    assert not validate_report({**GOOD, "recommendations": [{"action": "x", "source_ids": []}]}, HITS)["review_pass"]
    assert "not retrieved" in validate_report({**GOOD, "recommendations": [{"action": "x", "source_ids": ["S9"]}]}, HITS)["notes"]
    assert not validate_report(GOOD, [])["review_pass"]                         # a recommendation with nothing retrieved is ungrounded
    assert validate_report({**GOOD, "recommendations": []}, [])["review_pass"]   # no guidance + nothing retrieved is fine
    assert not validate_report({**GOOD, "observed": []}, HITS)["review_pass"]
    assert "verdict" in validate_report({**GOOD, "report_text": "The part is RoHS compliant."}, HITS)["notes"]
    assert not validate_report(None, HITS)["review_pass"]


def test_pipeline_result_saved_with_citations_and_retrievals(client):
    hit = {"sid": "S1", "doc": "WHS-CH-001", "rev": "A", "section": "4. Drum handling procedure", "page": 1, "score": 0.8}
    result = {"category": "near_miss", "flags": [], "report": "R", "extraction": {"location": "Dock 2", "narrative_summary": "n"},
              "vision": {"hazard_type": "Leak", "description": "d"}, "signals": {"potential_severity": "low", "confidence": "high"},
              "composed": GOOD, "validation": {"review_pass": True, "notes": ""}, "needs_human_review": False, "state": {},
              "retrieval": {"status": "ok", "hits": [hit], "log": [{"query": "[SOP] leak", "hits": [{k: hit[k] for k in ("doc", "rev", "section", "page", "score")}]}]}}
    iid = store.create_from_pipeline(result, "A")
    d = client.get(f"/api/incidents/{iid}").json()
    assert d["report"]["citations"] == [{"doc": "WHS-CH-001", "rev": "A", "section": "4. Drum handling procedure", "page": 1}]
    assert d["report"]["recommendations"] == ["Isolate the area (WHS-CH-001 rev A)"]
    assert d["retrievals"][0]["hits"][0]["doc"] == "WHS-CH-001" and d["report"]["observed"] == ["Drum leaked"]
    bad = store.create_from_pipeline({**result, "needs_human_review": True, "validation": {"review_pass": False, "notes": "Recommendation 1 cites no source."},
                                      "retrieval": {"status": "unavailable: boom", "hits": [], "log": []}}, "A")
    u = client.get(f"/api/incidents/{bad}").json()["report"]["unknowns"]
    assert any("cites no source" in x for x in u) and any("unavailable: boom" in x for x in u)
