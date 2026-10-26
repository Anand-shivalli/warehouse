"""Entry point: your existing api.py (pipeline jobs) + the incident UI routes, one app.

    uvicorn server:app --reload --port 8000        # UI: VITE_API_URL=http://localhost:8000 npm run dev

Needs DATABASE_URL (see .env.example). Finished pipeline jobs (/api/path-a, /api/path-b + confirm) are saved as
incidents with a draft report, without editing api.py: run_report is wrapped here and api.py looks it up by name
at call time.
"""
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


async def run_report(job, pipeline, state, parts):
    await _orig_run_report(job, pipeline, state, parts)
    result = job.get("result") or {}
    if job["status"] == "completed" and not result.get("no_incident") and result.get("category"):
        try:
            job["incident_id"] = store.create_from_pipeline(result, job["kind"])
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
