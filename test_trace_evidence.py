"""Agent trace, evidence + transcript saved from a pipeline run, procedure check. Real Postgres (see conftest.py)."""
import io
import types

import incident_store as store
from agents.report_validator import check_procedure, facts_text
from trace_recorder import TraceRecorder, record_event


def _ev(author, ts, usage=None, calls=0, partial=False, error=None):
    e = types.SimpleNamespace(author=author, timestamp=ts, usage_metadata=usage, partial=partial, error_message=error, model_version="m-1")
    e.get_function_calls = lambda: [object()] * calls
    return e


def U(i, o):
    return types.SimpleNamespace(prompt_token_count=i, candidates_token_count=o, total_token_count=i + o)


def test_trace_recorder_timing_tokens_and_parallel():
    r = TraceRecorder()
    r.t0 = r.last = 100.0
    for ev in (_ev("VisionAgent", 103.0, U(10, 5)), _ev("ExtractionAgent", 105.0, U(20, 8)), _ev("ConflictCheck", 106.0, U(7, 1), calls=1),
               _ev("ConflictCheck", 107.5, U(3, 1)), _ev("RetrievalStep", 107.6), _ev("Composer", 109.0, partial=True)):
        record_event(r, ev)
    rows = {x["agent"]: x for x in r.summary()}
    assert "Composer" not in rows                                              # partial streaming chunks are ignored
    assert rows["VisionAgent"]["duration_s"] == 3.0 and rows["ExtractionAgent"]["duration_s"] == 5.0   # parallel: both start at run start
    cc = rows["ConflictCheck"]
    assert cc["duration_s"] == 2.5 and cc["events"] == 2 and cc["tool_calls"] == 1 and cc["input_tokens"] == 10 and cc["total_tokens"] == 12
    assert rows["RetrievalStep"]["input_tokens"] is None and rows["RetrievalStep"]["status"] == "completed"   # code step: no token data
    assert [x["agent"] for x in r.summary()][0] in ("VisionAgent", "ExtractionAgent")
    r.add("Bad", 110.0, error="boom")
    assert {x["agent"]: x for x in r.summary()}["Bad"]["status"] == "failed"


RESULT = {"category": "no_classification_needed", "flags": [], "report": "R", "needs_human_review": False,
          "extraction": {"location": "Bay 4", "narrative_summary": "drum tipped", "transcript": "A drum fell over at bay four."},
          "vision": {"hazard_type": "Spill", "description": "d"}, "signals": {"potential_severity": "low", "confidence": "high"},
          "composed": {"report_text": "R", "observed": ["o"], "interpretation": [], "unknowns": [], "recommendations": []},
          "state": {"extraction_result": {"location": "Bay 4"}, "category_result": {"category": "x"}, "retrieval_status": "ok"},
          "retrieval": {"status": "ok", "hits": [{"sid": "S1", "doc": "WHS-CH-001", "rev": "A", "section": "7. Spill", "page": 2}], "log": []},
          "procedure_check": {"points": [{"requirement": "Isolate the area", "source_id": "S1", "status": "followed", "evidence_quote": "cones", "explanation": "e"}],
                              "dropped": ["x"]},
          "trace": [{"agent": "ExtractionAgent", "status": "completed", "started_at": "2026-10-27T01:00:00+00:00", "ended_at": "2026-10-27T01:00:04+00:00",
                     "duration_s": 4.0, "events": 1, "tool_calls": 0, "model": "m", "error": None, "input_tokens": 100, "output_tokens": 20, "total_tokens": 120},
                    {"agent": "RetrievalStep", "status": "completed", "started_at": "2026-10-27T01:00:04+00:00", "ended_at": "2026-10-27T01:00:05+00:00",
                     "duration_s": 1.0, "events": 1, "tool_calls": 0, "model": None, "error": None, "input_tokens": None, "output_tokens": None, "total_tokens": None}]}


def test_pipeline_run_saved_with_per_agent_runs_transcript_and_procedure(client):
    iid = store.create_from_pipeline(RESULT, "A")
    d = client.get(f"/api/incidents/{iid}").json()
    n = iid[4:]
    runs = {r["run_id"]: r for r in d["runs"]}
    assert set(runs) == {f"RUN-{n}A", f"RUN-{n}B", f"RUN-{n}C"}
    assert runs[f"RUN-{n}A"]["agent"] == "IncidentPipeline" and runs[f"RUN-{n}A"]["duration_s"] == 5.0
    assert runs[f"RUN-{n}A"]["metrics"]["total_tokens"] == 120 and runs[f"RUN-{n}A"]["metrics"]["agents"] == 2
    assert runs[f"RUN-{n}B"]["agent"] == "ExtractionAgent" and runs[f"RUN-{n}B"]["metrics"]["input_tokens"] == 100 and runs[f"RUN-{n}B"]["duration_s"] == 4.0
    out = client.get(f"/api/incidents/{iid}/runs/RUN-{n}B").json()
    assert out["output"]["output"] == {"extraction_result": {"location": "Bay 4"}}
    assert client.get(f"/api/incidents/{iid}/runs/NOPE").status_code == 404
    assert d["transcript"] == [{"t": "0:00", "speaker": "Reporter", "text": "A drum fell over at bay four.", "transcript_type": "ai_generated"}]
    pc = d["report"]["procedure_check"]
    assert pc[0]["status"] == "followed" and pc[0]["source"]["doc"] == "WHS-CH-001" and pc[0]["source"]["section"] == "7. Spill"
    assert any("left out" in u for u in d["report"]["unknowns"])
    b = store.create_from_pipeline({**RESULT, "transcript": [{"t": "1:02", "speaker": "SPEAKER_00", "text": "Hello"}], "trace": []}, "B")
    tb = client.get(f"/api/incidents/{b}").json()
    assert tb["transcript"][0]["transcript_type"] == "raw" and [r["agent"] for r in tb["runs"]] == ["IncidentPipeline"]


def test_evidence_inline_playback_and_view_audit(client):
    iid = store.create_from_pipeline(RESULT, "A")
    audio = b"ID3" + b"\x00" * 500
    a = store.add_evidence(iid, io.BytesIO(audio), "note.mp3", "audio/mpeg", "audio", "Orchestrator")
    store.add_evidence(iid, io.BytesIO(b"\xff\xd8jpg" * 10), "drum.JPG", "image/jpeg", "photo", "Orchestrator")
    store.add_evidence(iid, io.BytesIO(b"RIFF" + b"0" * 50), "x.ogg", "audio/ogg", "audio", "Orchestrator")             # newly allowed types
    u = f"/api/incidents/{iid}/evidence/{a['asset_id']}/download"
    r = client.get(u + "?inline=1")
    assert r.status_code == 200 and r.content == audio and r.headers["content-disposition"].startswith("inline")
    client.get(u + "?inline=1")
    assert client.get(u).headers["content-disposition"].startswith("attachment")
    acts = [x["action"] for x in store.get_incident(iid, role="admin", log_access=False)["audit"]]
    assert acts.count("Evidence viewed") == 1 and acts.count("Evidence downloaded") == 1      # one view logged, not one per request
    assert {e["type"] for e in client.get(f"/api/incidents/{iid}").json()["evidence"]} == {"audio", "photo"}


def test_procedure_check_drops_unverifiable_points():
    hits = [{"sid": "S1"}, {"sid": "S2"}]
    facts = facts_text({"extraction_result": {"narrative_summary": "Orange cones were placed; a worker held a broom."},
                        "vision_result": {"description": "Blue liquid."}})
    P = lambda **k: {"requirement": "r", "source_id": "S1", "status": "followed", "evidence_quote": "orange cones were placed", "explanation": "", **k}
    dev = {"points": [P(), P(source_id="S9"), P(evidence_quote="they locked the door"), P(status="possible_deviation", evidence_quote="a worker held a BROOM"),
                      P(status="cannot_tell", evidence_quote=""), P(evidence_quote="ok"), P(status="maybe")]}
    out = check_procedure(dev, hits, facts)
    assert [p["status"] for p in out["points"]] == ["followed", "possible_deviation", "cannot_tell"]
    assert len(out["dropped"]) == 4 and any("not retrieved" in x for x in out["dropped"]) and any("quote not found" in x for x in out["dropped"])
    assert check_procedure(None, hits, facts) == {"points": [], "dropped": []}
