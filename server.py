"""Entry point: your existing api.py (pipeline jobs) + the incident UI routes, one app.

    uvicorn server:app --reload --port 8000        # UI: VITE_API_URL=http://localhost:8000 npm run dev

Needs DATABASE_URL (see .env.example). Finished pipeline jobs (/api/path-a, /api/path-b + confirm) are saved as
incidents with a draft report, without editing api.py: run_report is wrapped here and api.py looks it up by name
at call time.
"""
import asyncio
import io
import threading

from dotenv import load_dotenv

load_dotenv()      # DATABASE_URL etc. from .env, before the store modules read their settings

from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

import api  # noqa: E402
import db  # noqa: E402
import doc_ingest  # noqa: E402
import incident_routes  # noqa: E402
import incident_store as store  # noqa: E402

store.init_db()

_orig_run_report = api.run_report


def _persist(job, result, files):
    """Save the incident, then keep the uploaded photo / audio / video / transcript file as its evidence."""
    iid = store.create_from_pipeline(result, job["kind"])
    job["incident_id"] = iid
    for asset_type, name, raw, mime in files:
        try:
            store.add_evidence(iid, io.BytesIO(raw), name, mime, asset_type, "Orchestrator")
        except Exception as e:      # the incident is already saved; report the evidence problem instead of failing the job
            job.setdefault("evidence_errors", []).append(f"{name}: {type(e).__name__}: {e}")


async def run_report(job, pipeline, state, parts):
    await _orig_run_report(job, pipeline, state, parts)
    files = job.pop("_files", [])          # free the uploaded bytes whatever happens
    result = job.get("result") or {}
    if job["status"] == "completed" and not result.get("no_incident") and result.get("category"):
        try:
            await asyncio.to_thread(_persist, job, result, files)
        except Exception as e:      # never fail the job because persistence failed
            job["incident_error"] = f"{type(e).__name__}: {e}"


api.run_report = run_report
api.app.add_middleware(CORSMiddleware, allow_origin_regex=r"http://(localhost|127\.0\.0\.1):\d+",
                       allow_methods=["*"], allow_headers=["*"])      # any local dev port, not just 5173
api.app.include_router(incident_routes.router)
app = api.app


@app.on_event("startup")
def _resume_indexing():
    """Documents left 'Processing' by a stopped server are indexed again, in the background."""
    threading.Thread(target=doc_ingest.requeue_stuck, daemon=True).start()


@app.on_event("shutdown")
def _close_db():
    db.close_pool()
