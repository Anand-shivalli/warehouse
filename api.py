import asyncio, json, uuid

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from google.adk.agents import SequentialAgent, ParallelAgent
from google.adk.sessions import InMemorySessionService
from google.adk.runners import Runner
from google.genai import types

from agents.extraction_agent import extraction_agent
from agents.vision_agent import vision_agent
from agents.classifier_pipeline import classification_pipeline
from agents.review_compose_pipeline import reviewer_pass1, composer_agent, reviewer_pass2
from agents.review_gate import ReviewGate
from agents.retrieval_step import RetrievalStep
from agents.report_validator import ReportValidator
from agents.deviation_check import deviation_check_agent
from agents.triage_agent import triage_agent
from agents.extraction_agent_text import text_extraction_agent
from tools.transcript_loader import format_transcript, build_incident_text, slice_span
from trace_recorder import TraceRecorder, record_event

APP = "incident_ui"
NO_PHOTO = {"hazard_type": "not available", "visible_injury_severity": "not available",
            "visible_damage": "not available", "description": "No photo was provided (audio-only report)."}

app = FastAPI(title="Incident Reporter API")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                   allow_methods=["*"], allow_headers=["*"])


# ---- fresh pipeline per job (agents allow one parent, so clone the module-level templates) ----
def _review_chain():
    g2 = ReviewGate(name="Gate_Pass2", review_key="review2_result", extra_keys=["validation_result"], next_agent=None, stage_name="Final report")
    cv = SequentialAgent(name="ComposeAndVerify", sub_agents=[composer_agent.clone(), deviation_check_agent.clone(), ReportValidator(name="ReportValidator"), reviewer_pass2.clone(), g2])
    g1 = ReviewGate(name="Gate_Pass1", review_key="review1_result", next_agent=cv, stage_name="Pre-composition review")
    return SequentialAgent(name="ReviewAndCompose", sub_agents=[RetrievalStep(name="RetrievalStep"), reviewer_pass1.clone(), g1])

def pipeline_a():
    capture = ParallelAgent(name="CaptureAnalysis", sub_agents=[extraction_agent.clone(), vision_agent.clone()])
    return SequentialAgent(name="PathA", sub_agents=[capture, classification_pipeline.clone(), _review_chain()])

def pipeline_b():
    return SequentialAgent(name="PathB", sub_agents=[text_extraction_agent.clone(), classification_pipeline.clone(), _review_chain()])


async def run_agent(agent, state, parts, on_event=None, trace=None):
    ss = InMemorySessionService()
    runner = Runner(agent=agent, app_name=APP, session_service=ss)
    sid = str(uuid.uuid4())
    await ss.create_session(app_name=APP, user_id="ui", session_id=sid, state=state)
    if trace is not None:
        trace.begin()
    async for ev in runner.run_async(user_id="ui", session_id=sid, new_message=types.Content(role="user", parts=parts)):
        record_event(trace, ev)       # per-agent timing, tokens and tool calls for the Agent trace tab
        if on_event and ev.is_final_response() and ev.content and ev.content.parts and ev.content.parts[0].text:
            on_event(ev.author, ev.content.parts[0].text)
    return (await ss.get_session(app_name=APP, user_id="ui", session_id=sid)).state

def audio_part(raw): return types.Part.from_bytes(data=raw, mime_type="audio/mpeg")
TEXT_GO = [types.Part(text="Process the data in the session state.")]

MEDIA = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".mp4": "video/mp4", ".mov": "video/quicktime",
         ".webm": "video/webm", ".avi": "video/x-msvideo", ".mpg": "video/mpeg", ".mpeg": "video/mpeg"}
VIDEO_EXT = (".mp4", ".mov", ".webm", ".avi", ".mpg", ".mpeg")
MAX_MEDIA = 18 * 1024 * 1024   # stays under Gemini's ~20 MB inline request limit

def media_part(raw, filename):
    ext = "." + filename.lower().rsplit(".", 1)[-1]
    if ext not in MEDIA:
        raise HTTPException(400, f"Unsupported file type: {ext}")
    if len(raw) > MAX_MEDIA:
        raise HTTPException(413, "File is too large. Use a clip under about 18 MB (trim or compress it).")
    return types.Part.from_bytes(data=raw, mime_type=MEDIA[ext])


# ---- jobs ----
JOBS = {}

def new_job(kind):
    job = {"id": uuid.uuid4().hex[:8], "kind": kind, "status": "queued", "events": [],
           "triage": None, "result": None, "error": None, "_ctx": {}, "_trace": TraceRecorder(), "_files": []}
    JOBS[job["id"]] = job
    return job

def logger(job):
    return lambda author, text: job["events"].append({"author": author, "text": text})

def transcript_lines(data, triage):
    """Segments of the flagged span (plus padding), same selection the pipeline used; the whole dialogue if no span was given."""
    start, end = float(triage.get("start_sec") or 0), float(triage.get("end_sec") or 0)
    segs = slice_span(data, start, end)["segments"] if end > start else data["segments"]
    return [{"t": f"{int(x['start'] // 60)}:{int(x['start'] % 60):02d}", "speaker": x.get("speaker", "UNKNOWN"), "text": x["text"]} for x in segs]


def summarize(state):
    def d(k):
        v = state.get(k)
        return v if isinstance(v, dict) else None
    rep, r1, r2, val = d("report_text"), d("review1_result"), d("review2_result"), d("validation_result")
    cat = d("category_result") or {}
    return {
        "report": rep["report_text"] if rep else None,
        "category": cat.get("category"), "flags": cat.get("flags", []),
        "signals": d("signals"), "extraction": d("extraction_result"), "vision": d("vision_result"),
        "review1": r1, "review2": r2, "validation": val, "composed": rep, "procedure_check": d("deviation_checked"),
        "retrieval": {"status": state.get("retrieval_status"), "hits": state.get("retrieval_hits") or [], "log": state.get("retrieval_log") or []},
        "needs_human_review": not (rep and r2 and r2.get("review_pass") and val and val.get("review_pass")),
        "state": json.loads(json.dumps(state, default=str)),
    }

async def run_report(job, pipeline, state, parts):
    try:
        job["status"] = "running"
        res = summarize(await run_agent(pipeline, state, parts, logger(job), trace=job["_trace"]))
        res["trace"] = job["_trace"].summary()
        res["triage"] = job.get("triage")
        if job["kind"] == "B" and job["_ctx"].get("data"):       # the dialogue the pipeline actually read, as transcript lines
            res["transcript"] = transcript_lines(job["_ctx"]["data"], job.get("triage") or {})
        job["result"] = res
        job["status"] = "completed"
    except Exception as e:
        job["status"], job["error"] = "failed", f"{type(e).__name__}: {e}"

async def run_b_triage(job, data, clip=None):
    try:
        job["status"] = "running"
        log = logger(job)
        vision = None
        if clip is not None:   # the existing vision agent reads the clip
            vision = (await run_agent(vision_agent.clone(), {}, [clip], log, trace=job["_trace"])).get("vision_result")
        st = await run_agent(triage_agent.clone(), {"conversation_text": format_transcript(data)}, TEXT_GO, log, trace=job["_trace"])
        triage = st.get("triage_result")
        job["triage"], job["_ctx"] = triage, {"data": data, "vision": vision}
        if triage and triage.get("incident_detected"):
            job["status"] = "awaiting_confirmation"
        else:
            job["status"], job["result"] = "completed", {"no_incident": True}
    except Exception as e:
        job["status"], job["error"] = "failed", f"{type(e).__name__}: {e}"


# ---- endpoints ----
@app.post("/api/trigger")
async def trigger(file: UploadFile = File(...)):
    """Takes the YAMNet events JSON produced in Colab."""
    try:
        out = json.loads(await file.read())
        assert isinstance(out["events"], list)
    except Exception:
        raise HTTPException(400, "Upload the YAMNet events JSON from Colab (it needs an 'events' list).")
    return {**out, "anomaly_detected": bool(out.get("anomaly_detected", out["events"]))}

@app.post("/api/path-a")
async def path_a(audio: UploadFile = File(...), image: UploadFile = File(None), video: UploadFile = File(None)):
    media = image or video
    if not media:
        raise HTTPException(400, "Provide a photo or a video clip")
    raw_media, raw_audio = await media.read(), await audio.read()
    part = media_part(raw_media, media.filename)
    job = new_job("A")
    job["_files"] = [("audio", audio.filename, raw_audio, audio.content_type),                  # kept as evidence once the incident exists
                     ("video" if media.filename.lower().endswith(VIDEO_EXT) else "photo", media.filename, raw_media, media.content_type)]
    asyncio.create_task(run_report(job, pipeline_a(), {}, [audio_part(raw_audio), part]))
    return {"id": job["id"]}

@app.post("/api/path-b")
async def path_b(dialogue: UploadFile = File(...), video: UploadFile = File(None)):
    """Takes the WhisperX + pyannote transcript JSON produced in Colab (and an optional video clip)."""
    try:
        raw_dialogue = await dialogue.read()
        data = json.loads(raw_dialogue)
        assert isinstance(data["segments"], list)
    except Exception:
        raise HTTPException(400, "Upload the WhisperX transcript JSON from Colab (it needs a 'segments' list).")
    raw_clip = await video.read() if video else None
    clip = media_part(raw_clip, video.filename) if video else None
    job = new_job("B")
    job["_files"] = [("transcript", dialogue.filename, raw_dialogue, "application/json")] + ([("video", video.filename, raw_clip, video.content_type)] if video else [])
    asyncio.create_task(run_b_triage(job, data, clip))
    return {"id": job["id"]}

@app.post("/api/jobs/{job_id}/confirm")
async def confirm(job_id: str):
    job = JOBS.get(job_id)
    if not job or job["status"] != "awaiting_confirmation":
        raise HTTPException(409, "Job is not waiting for confirmation")
    text = build_incident_text(job["_ctx"]["data"], job["triage"])
    job["status"] = "queued"
    asyncio.create_task(run_report(job, pipeline_b(), {"incident_text": text, "vision_result": job["_ctx"].get("vision") or NO_PHOTO}, TEXT_GO))
    return {"ok": True}

@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "Unknown job")
    return {k: v for k, v in job.items() if not k.startswith("_")}