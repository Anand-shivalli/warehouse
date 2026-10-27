"""PostgreSQL store for the incident UI backend.

Follows the logical data model in the architecture workbook (Data Dictionary, Session & Upload Correlation, GPS &
Location sheets). Every read returns the JSON shape incident-ui/src/mock.js uses, so the UI needs no changes.
Document chunks, RoHS records and retrieval live in doc_ingest.py / rohs_store.py.
"""
import hashlib
import json
import os
import re
import tempfile
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from psycopg.types.json import Jsonb

import db

SEED_PATH = os.getenv("INCIDENT_SEED", "seed.json")
STORAGE_DIR = Path(os.getenv("INCIDENT_STORAGE", "storage"))
SITE = os.getenv("SITE_ID", "WH-07 Columbus")
MAX_UPLOAD = int(os.getenv("MAX_UPLOAD_MB", "100")) * 1024 * 1024
PRIVILEGED_ROLES = {"safety_reviewer", "admin", "auditor"}   # may see precise coordinates
ALLOWED_EXT = {".jpg", ".jpeg", ".png", ".mp4", ".mov", ".webm", ".avi", ".mpg", ".mpeg", ".mp3", ".wav", ".m4a", ".ogg", ".aac", ".flac", ".pdf", ".json", ".txt"}
DOC_EXT = {".pdf", ".docx"}
DOC_TYPES = ("SOP", "RoHS", "Guideline")
ASSET_TYPES = {"video", "audio", "photo", "transcript", "document", "other"}


class StoreError(Exception):
    def __init__(self, msg, code=409):
        super().__init__(msg)
        self.code = code


ReviewError = StoreError  # backwards-compatible name


# ---------- helpers ----------
def now():
    return datetime.now(timezone.utc)


def J(v, default=None):
    """Wrap a Python value for a JSONB column."""
    return Jsonb(v if v is not None else ([] if default is None else default))


def parse_ts(v, field="timestamp"):
    """ISO-8601 string -> timezone-aware datetime. A timestamp with no offset is taken as UTC."""
    if v is None:
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        raise StoreError(f"{field} must be an ISO-8601 timestamp.", 422)
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def parse_day(v, field="date"):
    if v in (None, ""):
        return None
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        raise StoreError(f"{field} must be YYYY-MM-DD.", 422)


def clean(row):
    """Row dict -> JSON-friendly dict (datetimes and dates become ISO strings)."""
    return {k: (v.isoformat() if isinstance(v, (datetime, date)) else v) for k, v in row.items()}


def _audit(c, iid, actor, action, note=None, role=None, entity_type="incident", entity_id=None):
    c.execute("INSERT INTO audit_logs (incident_id,entity_type,entity_id,actor,role,action,note,at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
              (iid, entity_type, entity_id or iid, actor, role, action, note, now()))


def audit(actor, action, note=None, role=None, entity_type="document", entity_id=None, incident_id=None, conn=None):
    """Public helper for other modules (doc_ingest, rohs_store)."""
    if conn is not None:
        _audit(conn, incident_id, actor, action, note, role, entity_type, entity_id)
    else:
        with db.conn() as c:
            _audit(c, incident_id, actor, action, note, role, entity_type, entity_id)


def init_db():
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    db.migrate()        # raises db.DatabaseUnavailable with a clear message if Postgres can't be reached
    with db.conn() as c:
        empty = c.execute("SELECT COUNT(*) AS n FROM incidents").fetchone()["n"] == 0
    if empty and os.path.exists(SEED_PATH):
        try:
            _seed()
        except Exception as e:      # a bad seed file must not stop the server
            print(f"WARNING: could not load {SEED_PATH}: {type(e).__name__}: {e}. Starting with an empty database.")


# ---------- seed / insert ----------
def _insert_incident(c, inc):
    cl = inc.get("classification") or {}
    c.execute(
        "INSERT INTO incidents (incident_id,title,priority,status,incident_type,source,site_id,zone_id,camera_id,equipment_id,"
        "assigned_to,occurred_at,received_at,affected,class_category,class_confidence,class_flags) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (inc["incident_id"], inc["title"], inc["priority"], inc["status"], inc.get("incident_type"), inc.get("source"),
         inc.get("site_id", SITE), inc.get("zone_id"), inc.get("camera_id"), inc.get("equipment_id"),
         inc.get("assigned_to") or "Unassigned", parse_ts(inc.get("occurred_at")), parse_ts(inc.get("received_at")),
         J(inc.get("affected")), cl.get("category"), cl.get("confidence"), J(cl.get("flags"))))
    i = inc["incident_id"]
    for e in inc.get("evidence", []):
        c.execute("INSERT INTO assets (asset_id,incident_id,type,name,size,checksum,captured_at,uploaded_at,uploader) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                  (e["asset_id"], i, e.get("type"), e.get("name"), e.get("size"), e.get("checksum"),
                   parse_ts(e.get("captured_at")), parse_ts(e.get("uploaded_at")), e.get("uploader")))
    for d in inc.get("detections", []):
        c.execute("INSERT INTO detections (incident_id,model,event,confidence,offset_s) VALUES (%s,%s,%s,%s,%s)",
                  (i, d.get("model"), d.get("event"), d.get("confidence"), d.get("offset_s")))
    for t in inc.get("transcript", []):
        c.execute("INSERT INTO transcript (incident_id,transcript_type,t,speaker,text) VALUES (%s,%s,%s,%s,%s)",
                  (i, t.get("transcript_type") or "raw", t.get("t"), t.get("speaker"), t.get("text")))
    for l in inc.get("locations", []):
        c.execute("INSERT INTO locations (incident_id,source_type,method,lat,lon,accuracy_m,captured_at,received_at,validation) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                  (i, l.get("source_type"), l.get("method"), l.get("lat"), l.get("lon"), l.get("accuracy_m"),
                   parse_ts(l.get("captured_at")), parse_ts(l.get("received_at") or inc.get("received_at")), l.get("validation")))
    for r in inc.get("runs", []):
        c.execute("INSERT INTO agent_runs (run_id,incident_id,agent,status,started_at,duration_s,output) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                  (r["run_id"], i, r.get("agent"), r.get("status"), parse_ts(r.get("started_at")), r.get("duration_s"),
                   Jsonb(r["output"]) if r.get("output") is not None else None))
    for q in inc.get("retrievals", []):
        c.execute("INSERT INTO retrieval_events (incident_id,query,hits) VALUES (%s,%s,%s)", (i, q.get("query"), J(q.get("hits"))))
    r = inc.get("report")
    if r:
        c.execute("INSERT INTO incident_reports (report_id,incident_id,version,review_status,generated_by,summary,observed,interpretation,"
                  "unknowns,recommendations,citations,reviewed_by,review_note) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                  (r["report_id"], i, r.get("version", 1), r.get("review_status"), r.get("generated_by"), r.get("summary"),
                   J(r.get("observed")), J(r.get("interpretation")), J(r.get("unknowns")), J(r.get("recommendations")),
                   J(r.get("citations")), r.get("reviewed_by"), r.get("review_note")))
    for a in inc.get("audit", []):
        c.execute("INSERT INTO audit_logs (incident_id,entity_type,entity_id,actor,action,note,at) VALUES (%s,'incident',%s,%s,%s,%s,%s)",
                  (i, i, a.get("actor") or "system", a["action"], a.get("note"), parse_ts(a["at"])))


def _seed():
    """Load seed.json (exported from mock.js by export_seed.mjs). Timestamps are shifted so the newest data
    looks fresh relative to now."""
    with open(SEED_PATH, encoding="utf-8") as f:
        seed = json.load(f)
    gen = parse_ts(seed["generated_at"])
    shift = now() - gen

    def sh(v):
        if isinstance(v, str) and len(v) >= 20 and v[4] == "-" and "T" in v:
            try:
                return (parse_ts(v) + shift).isoformat()
            except StoreError:
                return v
        if isinstance(v, dict):
            return {k: sh(x) for k, x in v.items()}
        if isinstance(v, list):
            return [sh(x) for x in v]
        return v

    with db.conn() as c:
        for inc in seed["incidents"]:
            _insert_incident(c, sh(inc))
        for d in seed.get("documents", []):
            c.execute(
                "INSERT INTO documents (document_id,title,document_type,revision,status,effective_from,ingestion,ingest_stage,pages,warnings) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (document_id, revision) DO NOTHING",
                (d["document_id"], d["title"], d["type"], d["revision"], d.get("status"), parse_day(d.get("effective_from")),
                 d.get("ingestion", "Indexed"), "done", d.get("pages"), J([d["warning"]] if d.get("warning") else [])))


def _next_id(c):
    c.execute("SELECT pg_advisory_xact_lock(727002)")           # serialise id allocation across connections
    n = c.execute("SELECT COALESCE(MAX(substring(incident_id from 5)::int), 1000) + 1 AS n FROM incidents WHERE incident_id ~ '^INC-[0-9]+$'").fetchone()["n"]
    return f"INC-{n}"


# ---------- incidents ----------
def create_incident(body, actor="P. Natarajan", role=None):
    t = now()
    with db.conn() as c:
        iid = _next_id(c)
        _insert_incident(c, {
            "incident_id": iid, "title": body["title"].strip(), "priority": body.get("priority", "P2"), "status": "new",
            "incident_type": body.get("type"), "source": "manual", "site_id": SITE, "zone_id": body.get("zone"),
            "equipment_id": body.get("equipment") or "n/a", "assigned_to": "Unassigned", "occurred_at": t, "received_at": t,
            "affected": [body.get("zone")],
            "locations": [{"source_type": "Manual zone selection", "method": "worker choice", "lat": None, "lon": None,
                           "accuracy_m": None, "captured_at": t, "validation": "unverified"}]})
        _audit(c, iid, actor, "Incident created manually", body.get("description"), role)
    return get_incident(iid, role="admin", log_access=False)


# which pipeline state key(s) hold each agent's output, so the trace can show what every agent produced
AGENT_OUTPUT = {"ConversationTriage": ["triage"], "ExtractionAgent": ["extraction_result"], "TextExtractionAgent": ["extraction_result"],
                "VisionAgent": ["vision_result"], "ConflictCheck": ["conflict_result"], "SignalNormalizer": ["signals"],
                "ComplianceClassifier": ["category_result"], "RetrievalStep": ["retrieval_status", "retrieval_log"],
                "ReviewerPass1": ["review1_result"], "Composer": ["report_text"], "ReportValidator": ["validation_result"],
                "DeviationCheck": ["deviation_result"], "ReviewerPass2": ["review2_result"]}
_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def _runs_from_trace(n, result, t):
    """One summary row for the whole pipeline (RUN-nnnnA, carries the full state) plus one row per agent with its metrics."""
    trace = result.get("trace") or []
    state = dict(result.get("state") or {})
    state["triage"] = result.get("triage")
    sums = {k: sum(x.get(k) or 0 for x in trace) for k in ("input_tokens", "output_tokens", "total_tokens", "tool_calls")}
    start = min((x["started_at"] for x in trace), default=t)
    end = max((x["ended_at"] for x in trace), default=None)
    wall = round((parse_ts(end) - parse_ts(start)).total_seconds(), 2) if end else None
    failed = [x for x in trace if x["status"] == "failed"]
    runs = [{"run_id": f"RUN-{n}A", "agent": "IncidentPipeline", "status": "failed" if failed else "completed", "started_at": start,
             "duration_s": wall, "output": {"metrics": {"agents": len(trace), "wall_clock_s": wall, **sums}, "output": result.get("state") or {}}}]
    for k, x in enumerate(trace, start=1):
        keys = AGENT_OUTPUT.get(x["agent"], [])
        out = {key: state.get(key) for key in keys if state.get(key) is not None} or None
        runs.append({"run_id": f"RUN-{n}{_LETTERS[k]}" if k < len(_LETTERS) else f"RUN-{n}-{k}", "agent": x["agent"], "status": x["status"],
                     "started_at": x["started_at"], "duration_s": x["duration_s"],
                     "output": {"metrics": {m: x.get(m) for m in ("events", "tool_calls", "model", "input_tokens", "output_tokens", "total_tokens", "error")},
                                "output": out}})
    return runs


def _transcript_rows(result):
    """Path B: the WhisperX lines the pipeline read. Path A: the extraction agent's own transcription of the spoken note."""
    if result.get("transcript"):
        return [{**x, "transcript_type": "raw"} for x in result["transcript"]]
    text = ((result.get("extraction") or {}).get("transcript") or "").strip()
    return [{"t": "0:00", "speaker": "Reporter", "text": text, "transcript_type": "ai_generated"}] if text else []


def create_from_pipeline(result, kind, actor="Orchestrator"):
    """Turn a finished ADK pipeline job (api.py summarize() output) into an incident + draft report.
    Note: zone_id is the free-text location the extraction agent heard, not a validated zone."""
    cat = result.get("category") or "needs_review"
    flags = result.get("flags") or []
    ext = result.get("extraction") or {}
    vis = result.get("vision") or {}
    sig = result.get("signals") or {}
    high = cat in ("serious_injury", "recordable_injury") or "OSHA_recordable" in flags
    t = now()
    zone = ext.get("location") or "not stated"
    comp = result.get("composed") or {}
    rv = result.get("retrieval") or {}
    hits_by_sid = {h["sid"]: h for h in rv.get("hits") or [] if h.get("sid")}
    recs, cites, seen = [], [], set()
    for r in comp.get("recommendations") or []:
        refs = [hits_by_sid[x] for x in r.get("source_ids") or [] if x in hits_by_sid]
        recs.append(r.get("action", "") + (" (" + "; ".join(f"{h['doc']} rev {h['rev']}" for h in refs) + ")" if refs else ""))
        for h in refs:
            key = (h["doc"], h["rev"], h.get("section"), h.get("page"))
            if key not in seen:
                seen.add(key)
                cites.append({"doc": h["doc"], "rev": h["rev"], "section": h.get("section"), "page": h.get("page")})
    pc = result.get("procedure_check") or {}
    procedure = []
    for p_ in pc.get("points") or []:
        h = hits_by_sid.get(p_.get("source_id")) or {}
        procedure.append({**{k: p_.get(k) for k in ("requirement", "status", "evidence_quote", "explanation")},
                          "source": {"doc": h.get("doc"), "rev": h.get("rev"), "section": h.get("section"), "page": h.get("page")}})
    unknowns = list(comp.get("unknowns") or [])
    if pc.get("dropped"):
        unknowns.append(f"{len(pc['dropped'])} procedure-check point(s) were left out because their evidence could not be verified.")
    if result.get("needs_human_review"):
        val = result.get("validation") or {}
        unknowns.append("Automated review did not pass." + (f" Validation: {val['notes']}" if val.get("notes") else ""))
    if rv.get("status") and rv["status"] != "ok":
        unknowns.append(f"Document retrieval: {rv['status']}")
    with db.conn() as c:
        iid = _next_id(c)
        n = iid[4:]
        hz = vis.get("hazard_type")
        title = (hz if hz not in (None, "not available") else cat.replace("_", " ").title()) + f" - {zone}"
        _insert_incident(c, {
            "incident_id": iid, "title": title, "priority": "P1" if high else ("P2" if sig.get("potential_severity") == "high" else "P3"),
            "status": "new", "incident_type": hz, "source": "worker" if kind == "A" else "ambient",
            "site_id": SITE, "zone_id": zone, "equipment_id": "n/a", "occurred_at": t, "received_at": t, "affected": [zone],
            "classification": {"category": cat, "confidence": {"high": 0.9, "medium": 0.7, "low": 0.5}.get(sig.get("confidence"), 0.7), "flags": flags},
            "locations": [{"source_type": "Manual zone selection", "method": "extracted from report", "lat": None, "lon": None,
                           "accuracy_m": None, "captured_at": t, "validation": "unverified"}],
            "runs": _runs_from_trace(n, result, t),
            "transcript": _transcript_rows(result),
            "report": {"report_id": f"RPT-{n}", "version": 1, "review_status": "draft", "generated_by": "ADK pipeline",
                       "summary": result.get("report") or ext.get("narrative_summary") or "",
                       "observed": comp.get("observed") or [x for x in [ext.get("narrative_summary"), vis.get("description")] if x],
                       "interpretation": comp.get("interpretation") or [f"Category: {cat}"],
                       "unknowns": unknowns,
                       "recommendations": recs, "citations": cites, "reviewed_by": None, "review_note": None},
            "retrievals": [{"query": q.get("query"), "hits": q.get("hits") or []} for q in rv.get("log") or []]})
        c.execute("UPDATE incident_reports SET procedure_check=%s WHERE incident_id=%s", (Jsonb(procedure), iid))
        _audit(c, iid, actor, "Classified and draft report v1 generated",
               "Flagged for human review by the pipeline." if result.get("needs_human_review") else None)
    return iid


TRANSITIONS = {"start_review": ("new", "in_review"), "approve": ("in_review", "approved"),
               "reject": ("in_review", "rejected"), "close": ("approved", "closed")}
LABELS = {"start_review": "Review started", "approve": "Approved report", "reject": "Rejected report", "close": "Closed incident"}


def review(iid, action, comment, actor="P. Natarajan", role=None):
    if action not in TRANSITIONS:
        raise StoreError(f"Unknown action: {action}", 400)
    need, nxt = TRANSITIONS[action]
    with db.conn() as c:
        row = c.execute("SELECT status FROM incidents WHERE incident_id=%s FOR UPDATE", (iid,)).fetchone()
        if not row:
            raise StoreError("Incident not found", 404)
        if row["status"] != need:
            raise StoreError(f"Cannot {action.replace('_', ' ')} an incident that is {row['status']}.")
        has_report = c.execute("SELECT 1 FROM incident_reports WHERE incident_id=%s", (iid,)).fetchone()
        if action in ("start_review", "approve", "reject") and not has_report:
            raise StoreError("No report to review yet.")
        if action == "reject" and not (comment or "").strip():
            raise StoreError("A comment is required to reject.", 400)
        c.execute("UPDATE incidents SET status=%s WHERE incident_id=%s", (nxt, iid))
        if action == "start_review":
            c.execute("UPDATE incidents SET assigned_to=%s WHERE incident_id=%s", (actor, iid))
        if has_report:
            if action == "start_review":
                c.execute("UPDATE incident_reports SET review_status='in_review' WHERE incident_id=%s", (iid,))
            else:
                c.execute("UPDATE incident_reports SET review_status=%s, reviewed_by=%s, review_note=%s WHERE incident_id=%s",
                          (nxt, actor, comment or None, iid))
        _audit(c, iid, actor, LABELS[action], comment or None, role)
    return get_incident(iid, role="admin", log_access=False)


# ---------- sessions, evidence, locations ----------
def _require_incident(c, iid):
    if not c.execute("SELECT 1 FROM incidents WHERE incident_id=%s", (iid,)).fetchone():
        raise StoreError("Incident not found", 404)


def _check_session(c, iid, sid):
    """Upload correlation rule: reject a session that does not belong to this incident."""
    if not sid:
        return
    row = c.execute("SELECT incident_id, status FROM reporting_sessions WHERE reporting_session_id=%s", (sid,)).fetchone()
    if not row or row["incident_id"] != iid:
        raise StoreError("reporting_session_id does not belong to this incident.", 422)
    if row["status"] != "open":
        raise StoreError("Reporting session is closed.", 409)


def create_session(iid, created_by, channel="worker_ui", role=None):
    sid = str(uuid.uuid4())
    with db.conn() as c:
        _require_incident(c, iid)
        c.execute("INSERT INTO reporting_sessions (reporting_session_id,incident_id,opened_at,created_by,channel,status) VALUES (%s,%s,%s,%s,%s,'open')",
                  (sid, iid, now(), created_by, channel))
        _audit(c, iid, created_by, "Reporting session opened", f"session {sid} via {channel}", role, "reporting_session", sid)
    return {"reporting_session_id": sid, "incident_id": iid, "created_by": created_by, "channel": channel, "status": "open"}


def close_session(iid, sid, actor, role=None):
    with db.conn() as c:
        _check_session(c, iid, sid)
        c.execute("UPDATE reporting_sessions SET status='closed', closed_at=%s WHERE reporting_session_id=%s", (now(), sid))
        _audit(c, iid, actor, "Reporting session closed", None, role, "reporting_session", sid)
    return {"reporting_session_id": sid, "status": "closed"}


def safe_name(name):
    name = os.path.basename(name or "file").replace("\x00", "")
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name)[:120] or "file"


def _human(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


def stream_to_disk(fileobj, dest_dir: Path):
    """Copy an upload to a temp file in dest_dir, enforcing MAX_UPLOAD and computing sha256."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    h, total = hashlib.sha256(), 0
    fd, tmp = tempfile.mkstemp(dir=dest_dir, suffix=".part")
    try:
        with os.fdopen(fd, "wb") as out:
            while chunk := fileobj.read(1024 * 1024):
                total += len(chunk)
                if total > MAX_UPLOAD:
                    raise StoreError(f"File exceeds the {MAX_UPLOAD // (1024 * 1024)} MB limit.", 413)
                h.update(chunk)
                out.write(chunk)
        if total == 0:
            raise StoreError("Empty file.", 400)
    except Exception:
        Path(tmp).unlink(missing_ok=True)
        raise
    return tmp, h.hexdigest(), total


def add_evidence(iid, fileobj, filename, content_type, asset_type, uploader, captured_at=None,
                 reporting_session_id=None, role=None):
    ext = Path(filename or "").suffix.lower()
    if ext not in ALLOWED_EXT:
        raise StoreError(f"Unsupported file type: {ext or 'none'}", 400)
    if asset_type not in ASSET_TYPES:
        raise StoreError(f"asset_type must be one of {sorted(ASSET_TYPES)}", 400)
    captured = parse_ts(captured_at, "captured_at")
    with db.conn() as c:        # validate before touching disk
        _require_incident(c, iid)
        _check_session(c, iid, reporting_session_id)
    asset_id = "AST-" + uuid.uuid4().hex[:10].upper()
    rel_dir = Path("evidence") / iid
    tmp, digest, size = stream_to_disk(fileobj, STORAGE_DIR / rel_dir)
    key = str(rel_dir / f"{asset_id}_{safe_name(filename)}")
    os.replace(tmp, STORAGE_DIR / key)
    uploaded = now()
    try:
        with db.conn() as c:
            c.execute("INSERT INTO assets (asset_id,incident_id,reporting_session_id,type,name,size,size_bytes,mime_type,storage_key,checksum,captured_at,uploaded_at,uploader) "
                      "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                      (asset_id, iid, reporting_session_id, asset_type, safe_name(filename), _human(size), size, content_type,
                       key, digest, captured or uploaded, uploaded, uploader))
            _audit(c, iid, uploader, "Evidence uploaded", f"{asset_id} {safe_name(filename)} sha256={digest[:12]}", role, "asset", asset_id)
    except Exception:
        (STORAGE_DIR / key).unlink(missing_ok=True)
        raise
    return next(e for e in get_incident(iid, role="admin", log_access=False)["evidence"] if e["asset_id"] == asset_id)


def evidence_file(iid, asset_id, actor, role=None, inline=False):
    with db.conn() as c:
        row = c.execute("SELECT storage_key,name,mime_type FROM assets WHERE asset_id=%s AND incident_id=%s", (asset_id, iid)).fetchone()
        if not row:
            raise StoreError("Asset not found for this incident", 404)
        if not row["storage_key"]:
            raise StoreError("No file is stored for this asset (metadata only).", 404)
        path = (STORAGE_DIR / row["storage_key"]).resolve()
        if STORAGE_DIR.resolve() not in path.parents or not path.is_file():
            raise StoreError("Stored file is missing.", 404)
        if not inline:
            _audit(c, iid, actor, "Evidence downloaded", asset_id, role, "asset", asset_id)
        elif not c.execute("SELECT 1 FROM audit_logs WHERE entity_id=%s AND actor=%s AND action='Evidence viewed' AND at > now() - interval '10 minutes'",
                           (asset_id, actor)).fetchone():       # a player makes many requests; log one view per 10 minutes
            _audit(c, iid, actor, "Evidence viewed", asset_id, role, "asset", asset_id)
    return path, row["name"], row["mime_type"] or "application/octet-stream"


def get_run_output(iid, run_id):
    with db.conn() as c:
        r = c.execute("SELECT run_id,agent,status,started_at,duration_s,output FROM agent_runs WHERE incident_id=%s AND run_id=%s", (iid, run_id)).fetchone()
    if not r:
        raise StoreError("Run not found", 404)
    return clean(r)


def add_location(iid, body, actor, role=None):
    """Append a location observation (never overwrites). Validates WGS84 ranges per the GPS & Location sheet."""
    lat, lon, acc = body.get("lat"), body.get("lon"), body.get("accuracy_m")
    notes = []
    if (lat is None) != (lon is None):
        raise StoreError("lat and lon must be given together.", 400)
    if lat is not None:
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise StoreError("Latitude must be -90..90 and longitude -180..180.", 422)
        if acc is not None and acc < 0:
            raise StoreError("accuracy_m cannot be negative.", 422)
    captured = parse_ts(body.get("captured_at"), "captured_at") or now()
    validation = "unverified" if lat is None else "valid"
    if lat is not None and (now() - captured).total_seconds() > 3600:
        validation = "stale"
        notes.append("captured more than 1 h before receipt")
    with db.conn() as c:
        _require_incident(c, iid)
        _check_session(c, iid, body.get("reporting_session_id"))
        if body.get("asset_id") and not c.execute("SELECT 1 FROM assets WHERE asset_id=%s AND incident_id=%s", (body["asset_id"], iid)).fetchone():
            raise StoreError("asset_id does not belong to this incident.", 422)
        c.execute("INSERT INTO locations (incident_id,reporting_session_id,asset_id,source_type,method,lat,lon,accuracy_m,captured_at,received_at,validation) "
                  "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                  (iid, body.get("reporting_session_id"), body.get("asset_id"), body["source_type"], body.get("method"),
                   lat, lon, acc, captured, now(), validation))
        _audit(c, iid, actor, "Location observation added", f"{body['source_type']} ({validation}{'; ' + ', '.join(notes) if notes else ''})", role, "location")
    return {"validation": validation, "notes": notes}


# ---------- reads ----------
def _build(c, r, role):
    i = r["incident_id"]
    q = lambda sql: [clean(x) for x in c.execute(sql, (i,)).fetchall()]
    cls = {"category": r["class_category"], "confidence": r["class_confidence"], "flags": r["class_flags"]} if r["class_category"] else None
    rep = c.execute("SELECT * FROM incident_reports WHERE incident_id=%s", (i,)).fetchone()
    report = None
    if rep:
        report = {k: rep[k] for k in ("report_id", "version", "review_status", "generated_by", "summary", "reviewed_by", "review_note",
                                       "observed", "interpretation", "unknowns", "recommendations", "citations", "procedure_check")}
    evidence = q("SELECT asset_id,type,name,size,checksum,captured_at,uploaded_at,uploader,mime_type,reporting_session_id,"
                 "(storage_key IS NOT NULL) AS has_file FROM assets WHERE incident_id=%s ORDER BY uploaded_at, asset_id")
    locations = q("SELECT source_type,method,lat,lon,accuracy_m,captured_at,received_at,validation,asset_id,reporting_session_id "
                  "FROM locations WHERE incident_id=%s ORDER BY id")
    if role not in PRIVILEGED_ROLES:
        for l in locations:
            l["lat"] = l["lon"] = None
            l["restricted"] = True
    return {
        "incident_id": i, "title": r["title"], "priority": r["priority"], "status": r["status"], "incident_type": r["incident_type"],
        "source": r["source"], "site_id": r["site_id"], "zone_id": r["zone_id"], "camera_id": r["camera_id"],
        "equipment_id": r["equipment_id"], "assigned_to": r["assigned_to"],
        "occurred_at": r["occurred_at"].isoformat() if r["occurred_at"] else None,
        "received_at": r["received_at"].isoformat() if r["received_at"] else None,
        "affected": r["affected"], "classification": cls,
        "evidence": evidence,
        "detections": q("SELECT model,event,confidence,offset_s FROM detections WHERE incident_id=%s ORDER BY id"),
        "transcript": q("SELECT t,speaker,text,transcript_type FROM transcript WHERE incident_id=%s ORDER BY id"),
        "locations": locations,
        "runs": q("SELECT run_id,agent,status,started_at,duration_s,output->'metrics' AS metrics FROM agent_runs WHERE incident_id=%s ORDER BY started_at, run_id"),
        "retrievals": [{"query": x["query"], "hits": x["hits"]} for x in c.execute("SELECT query,hits FROM retrieval_events WHERE incident_id=%s ORDER BY id", (i,))],
        "report": report,
        "audit": q("SELECT actor,action,note,at FROM audit_logs WHERE incident_id=%s AND entity_type IN ('incident','asset','location','reporting_session') ORDER BY at, id"),
    }


def list_incidents(role="safety_reviewer"):
    with db.conn() as c:
        return [_build(c, r, role) for r in c.execute("SELECT * FROM incidents ORDER BY received_at DESC").fetchall()]


def get_incident(iid, role="safety_reviewer", actor=None, log_access=True):
    with db.conn() as c:
        r = c.execute("SELECT * FROM incidents WHERE incident_id=%s", (iid,)).fetchone()
        if not r:
            return None
        out = _build(c, r, role)
        if log_access and role in PRIVILEGED_ROLES and any(l["lat"] is not None for l in out["locations"]):
            _audit(c, iid, actor or "unknown", "Viewed precise location", None, role, "location")
        return out


def list_sessions(iid):
    with db.conn() as c:
        return [clean(x) for x in c.execute("SELECT * FROM reporting_sessions WHERE incident_id=%s ORDER BY opened_at", (iid,)).fetchall()]


# ---------- documents (register + list + lifecycle; parsing/indexing is in doc_ingest.py) ----------
DOC_LIST_SQL = ("SELECT document_id, title, document_type AS type, revision, status, effective_from, effective_to, ingestion, ingest_stage, "
                "pages, parser, uploaded_at, "
                "(SELECT string_agg(w, ' ') FROM jsonb_array_elements_text(warnings) w) AS warning FROM documents")


def list_documents():
    with db.conn() as c:
        return [clean(x) for x in c.execute(DOC_LIST_SQL + " ORDER BY document_id, revision DESC").fetchall()]


def register_document(fileobj, filename, document_id, doc_type, title, revision, effective_from, uploader, role=None, owner=None):
    """Step 1 of the Document Ingestion sheet: validate, checksum, store the immutable original, create the row.
    Returns the new row's numeric id (doc_pk) so the caller can queue indexing."""
    ext = Path(filename or "").suffix.lower()
    if ext not in DOC_EXT:
        raise StoreError(f"Unsupported document type: {ext or 'none'} (use .pdf or .docx)", 400)
    if doc_type not in DOC_TYPES:
        raise StoreError(f"type must be one of {', '.join(DOC_TYPES)}", 400)
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,60}", document_id or ""):
        raise StoreError("document_id may contain only letters, digits, '.', '_' and '-'.", 400)
    if not (revision or "").strip():
        raise StoreError("revision is required.", 400)
    eff = parse_day(effective_from, "effective_from")
    with db.conn() as c:
        if c.execute("SELECT 1 FROM documents WHERE document_id=%s AND revision=%s", (document_id, revision)).fetchone():
            raise StoreError(f"{document_id} revision {revision} already exists; upload a new revision instead.", 409)
    rel_dir = Path("documents") / document_id
    tmp, digest, size = stream_to_disk(fileobj, STORAGE_DIR / rel_dir)
    key = str(rel_dir / f"rev{safe_name(revision)}_{safe_name(filename)}")
    os.replace(tmp, STORAGE_DIR / key)
    status = "Pending verification" if doc_type == "RoHS" else "Draft"
    try:
        with db.conn() as c:
            row = c.execute(
                "INSERT INTO documents (document_id,title,document_type,revision,status,effective_from,owner,original_filename,storage_key,checksum,"
                "uploader,uploaded_at,ingestion,ingest_stage) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'Processing','queued') RETURNING id",
                (document_id, title, doc_type, revision, status, eff, owner, safe_name(filename), key, digest, uploader, now())).fetchone()
            _audit(c, None, uploader, "Document uploaded", f"{document_id} rev {revision} sha256={digest[:12]}", role, "document", f"{document_id}@{revision}")
    except Exception:
        (STORAGE_DIR / key).unlink(missing_ok=True)
        raise
    return {"doc_pk": row["id"], "document_id": document_id, "revision": revision, "type": doc_type, "status": status,
            "ingestion": "Processing", "checksum": digest, "size": _human(size)}


def doc_pk(document_id, revision):
    with db.conn() as c:
        row = c.execute("SELECT id FROM documents WHERE document_id=%s AND revision=%s", (document_id, revision)).fetchone()
    if not row:
        raise StoreError("Document revision not found", 404)
    return row["id"]


def set_document_status(document_id, revision, status, actor, role=None):
    """Only an Effective revision is used as current guidance. Making one Effective supersedes the previous
    Effective revision (kept, with effective_to set) instead of overwriting it."""
    if status not in ("Effective", "Superseded", "Draft"):
        raise StoreError("status must be Effective, Superseded or Draft", 400)
    t = now().date()
    with db.conn() as c:
        row = c.execute("SELECT id FROM documents WHERE document_id=%s AND revision=%s FOR UPDATE", (document_id, revision)).fetchone()
        if not row:
            raise StoreError("Document revision not found", 404)
        if status == "Effective":
            c.execute("UPDATE documents SET status='Superseded', effective_to=%s WHERE document_id=%s AND status='Effective' AND revision<>%s", (t, document_id, revision))
            c.execute("UPDATE documents SET status='Effective', effective_from=COALESCE(effective_from,%s), effective_to=NULL WHERE id=%s", (t, row["id"]))
        else:
            c.execute("UPDATE documents SET status=%s WHERE id=%s", (status, row["id"]))
        _audit(c, None, actor, f"Document marked {status}", f"{document_id} rev {revision}", role, "document", f"{document_id}@{revision}")
    return {"document_id": document_id, "revision": revision, "status": status}


# ---------- overview ----------
def _fmt_minutes(m):
    return "n/a" if m is None else (f"{m:.0f} min" if m < 120 else f"{m / 60:.1f} h")


def overview(days=12):
    """KPIs and 12-day sparklines computed from incidents + audit_logs."""
    n = now()
    buckets = [(n - timedelta(days=days - 1 - k)).date() for k in range(days)]
    idx = {d: k for k, d in enumerate(buckets)}
    day = lambda d: d.astimezone(timezone.utc).date()
    opened, review_n, resolved = [0] * days, [0] * days, [0] * days
    tta_s, tta_n, ttr_s, ttr_n = [0.0] * days, [0] * days, [0.0] * days, [0] * days
    all_tta, all_ttr, resolved30 = [], [], 0
    with db.conn() as c:
        recv = {r["incident_id"]: r["received_at"] for r in c.execute("SELECT incident_id, received_at FROM incidents")}
        for rcv in recv.values():
            if rcv and day(rcv) in idx:
                opened[idx[day(rcv)]] += 1
        for a in c.execute("SELECT incident_id, action, at FROM audit_logs WHERE action IN ('Review started','Closed incident') AND incident_id IS NOT NULL"):
            rcv = recv.get(a["incident_id"])
            if not rcv:
                continue
            mins = (a["at"] - rcv).total_seconds() / 60
            k = idx.get(day(a["at"]))
            if a["action"] == "Review started":
                all_tta.append(mins)
                if k is not None:
                    review_n[k] += 1; tta_s[k] += mins; tta_n[k] += 1
            else:
                all_ttr.append(mins)
                if (n - a["at"]).days < 30:
                    resolved30 += 1
                if k is not None:
                    resolved[k] += 1; ttr_s[k] += mins / 60; ttr_n[k] += 1
        needs_doc = c.execute("SELECT COUNT(*) AS n FROM documents WHERE ingestion IN ('Needs review','Failed') OR status='Pending verification'").fetchone()["n"]
    avg = lambda xs: sum(xs) / len(xs) if xs else None
    per = lambda s, m: [round(s[k] / m[k], 1) if m[k] else 0 for k in range(days)]
    return {
        "sparks": {"open": opened, "review": review_n, "resolved": resolved, "tta": per(tta_s, tta_n), "ttr": per(ttr_s, ttr_n)},
        "resolved30d": resolved30, "meanReview": _fmt_minutes(avg(all_tta)), "meanClose": _fmt_minutes(avg(all_ttr)),
        # Static "ok" for the four services: this backend cannot observe the edge/agent processes. Replace with real health checks.
        "pipeline": [{"name": x, "state": "ok"} for x in ("Edge detection", "Ingestion API", "Classifier agent", "Report agent")]
                    + [{"name": "Document indexer", "state": "warn" if needs_doc else "ok",
                        **({"note": f"{needs_doc} document{'s' if needs_doc > 1 else ''} need review"} if needs_doc else {})}],
    }
