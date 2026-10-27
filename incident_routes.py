"""FastAPI router for the incident UI. Matches incident-ui/src/api.js, plus the upload / session / location /
document-ingestion / RoHS-review endpoints the architecture workbook calls for.

  GET  /api/incidents                                   list (full objects)
  GET  /api/incidents/{id}                              detail (logs precise-location views)
  POST /api/incidents                                   manual create
  POST /api/incidents/{id}/review                       {action: start_review|approve|reject|close, comment}
  POST /api/incidents/{id}/sessions                     open a reporting session
  POST /api/incidents/{id}/sessions/{sid}/close
  POST /api/incidents/{id}/evidence                     multipart upload (incident + optional session validated)
  GET  /api/incidents/{id}/evidence/{asset_id}/download
  POST /api/incidents/{id}/locations                    append a location observation
  GET  /api/overview
  GET  /api/documents
  POST /api/documents                                   multipart upload of an SOP / RoHS / Guideline revision (indexing runs in background)
  POST /api/documents/{document_id}/{revision}/status   Effective | Superseded | Draft
  POST /api/documents/{document_id}/{revision}/reindex
  GET  /api/documents/{document_id}/{revision}/chunks   inspect what was indexed
  GET  /api/rohs                                        RoHS candidate records (?status=&document_id=)
  POST /api/rohs/{id}/verify                            confirm, optionally correcting fields
  POST /api/rohs/{id}/reject
  GET  /api/rag/health                                  embedder / parser / table-size diagnostics

Identity: X-User / X-Role headers are TRUSTED AS SENT. That is a placeholder, not authentication. Put real
auth (JWT/SSO) in front before exposing this beyond a local demo.
"""
from typing import Literal, Optional

from fastapi import APIRouter, BackgroundTasks, File, Form, Header, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

import doc_ingest
import incident_store as store
import rohs_store

router = APIRouter(prefix="/api")
DEFAULT_USER = "P. Natarajan"
DEFAULT_ROLE = "safety_reviewer"


def _wrap(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except store.StoreError as e:
        raise HTTPException(e.code, str(e))


class CreateIncident(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    priority: Literal["P1", "P2", "P3"] = "P2"
    zone: str
    type: str
    equipment: Optional[str] = ""
    description: Optional[str] = ""


class ReviewBody(BaseModel):
    action: Literal["start_review", "approve", "reject", "close"]
    comment: Optional[str] = ""


class SessionBody(BaseModel):
    channel: str = "worker_ui"


class LocationBody(BaseModel):
    source_type: str = Field(min_length=1)       # e.g. "Mobile GPS", "Photo EXIF", "Camera registry", "Manual zone selection"
    method: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None
    accuracy_m: Optional[float] = None
    captured_at: Optional[str] = None
    reporting_session_id: Optional[str] = None
    asset_id: Optional[str] = None


class StatusBody(BaseModel):
    status: Literal["Effective", "Superseded", "Draft"]


class RohsVerifyBody(BaseModel):
    supplier: Optional[str] = None
    part_number: Optional[str] = None
    product_scope: Optional[str] = None
    declaration_date: Optional[str] = None
    valid_until: Optional[str] = None
    exemptions: Optional[list[str]] = None
    note: Optional[str] = None


class RohsRejectBody(BaseModel):
    note: str = Field(min_length=1)


# ---- incidents ----
@router.get("/incidents")
def list_incidents(x_role: str = Header(DEFAULT_ROLE)):
    return store.list_incidents(role=x_role)


@router.get("/incidents/{incident_id}")
def get_incident(incident_id: str, x_user: str = Header(DEFAULT_USER), x_role: str = Header(DEFAULT_ROLE)):
    inc = store.get_incident(incident_id, role=x_role, actor=x_user)
    if not inc:
        raise HTTPException(404, "Incident not found")
    return inc


@router.post("/incidents", status_code=201)
def create_incident(body: CreateIncident, x_user: str = Header(DEFAULT_USER), x_role: str = Header(DEFAULT_ROLE)):
    return store.create_incident(body.model_dump(), actor=x_user, role=x_role)


@router.post("/incidents/{incident_id}/review")
def review_incident(incident_id: str, body: ReviewBody, x_user: str = Header(DEFAULT_USER), x_role: str = Header(DEFAULT_ROLE)):
    return _wrap(store.review, incident_id, body.action, body.comment, actor=x_user, role=x_role)


# ---- sessions / evidence / locations ----
@router.post("/incidents/{incident_id}/sessions", status_code=201)
def open_session(incident_id: str, body: SessionBody = SessionBody(), x_user: str = Header(DEFAULT_USER), x_role: str = Header(DEFAULT_ROLE)):
    return _wrap(store.create_session, incident_id, x_user, body.channel, x_role)


@router.post("/incidents/{incident_id}/sessions/{session_id}/close")
def close_session(incident_id: str, session_id: str, x_user: str = Header(DEFAULT_USER), x_role: str = Header(DEFAULT_ROLE)):
    return _wrap(store.close_session, incident_id, session_id, x_user, x_role)


@router.post("/incidents/{incident_id}/evidence", status_code=201)
def upload_evidence(incident_id: str, file: UploadFile = File(...), asset_type: str = Form(...),
                    captured_at: Optional[str] = Form(None), reporting_session_id: Optional[str] = Form(None),
                    x_user: str = Header(DEFAULT_USER), x_role: str = Header(DEFAULT_ROLE)):
    return _wrap(store.add_evidence, incident_id, file.file, file.filename, file.content_type, asset_type, x_user,
                 captured_at, reporting_session_id, x_role)


@router.get("/incidents/{incident_id}/evidence/{asset_id}/download")
def download_evidence(incident_id: str, asset_id: str, inline: bool = False, x_user: str = Header(DEFAULT_USER), x_role: str = Header(DEFAULT_ROLE)):
    """inline=1 lets the browser show the photo / play the audio or video in the page instead of downloading it."""
    path, name, mime = _wrap(store.evidence_file, incident_id, asset_id, x_user, x_role, inline)
    return FileResponse(path, filename=name, media_type=mime, content_disposition_type="inline" if inline else "attachment")


@router.get("/incidents/{incident_id}/runs/{run_id}")
def run_output(incident_id: str, run_id: str):
    """What one agent produced, plus its metrics (the Agent trace tab loads this when a row is opened)."""
    return _wrap(store.get_run_output, incident_id, run_id)


@router.post("/incidents/{incident_id}/locations", status_code=201)
def add_location(incident_id: str, body: LocationBody, x_user: str = Header(DEFAULT_USER), x_role: str = Header(DEFAULT_ROLE)):
    return _wrap(store.add_location, incident_id, body.model_dump(), x_user, x_role)


# ---- overview / documents ----
@router.get("/overview")
def get_overview():
    return store.overview()


@router.get("/documents")
def get_documents():
    return store.list_documents()


@router.post("/documents", status_code=201)
def upload_document(background: BackgroundTasks, file: UploadFile = File(...), document_id: str = Form(...), type: str = Form(...),
                    title: str = Form(...), revision: str = Form(...), effective_from: Optional[str] = Form(None),
                    x_user: str = Header(DEFAULT_USER), x_role: str = Header(DEFAULT_ROLE)):
    doc = _wrap(store.register_document, file.file, file.filename, document_id, type, title, revision, effective_from, x_user, x_role)
    background.add_task(doc_ingest.ingest_document, doc.pop("doc_pk"))      # parse / chunk / embed / index after the response
    return doc


@router.post("/documents/{document_id}/{revision}/status")
def document_status(document_id: str, revision: str, body: StatusBody, x_user: str = Header(DEFAULT_USER), x_role: str = Header(DEFAULT_ROLE)):
    return _wrap(store.set_document_status, document_id, revision, body.status, x_user, x_role)


@router.post("/documents/{document_id}/{revision}/reindex", status_code=202)
def reindex_document(document_id: str, revision: str, background: BackgroundTasks):
    pk = _wrap(store.doc_pk, document_id, revision)
    doc_ingest.mark_queued(pk)
    background.add_task(doc_ingest.ingest_document, pk)
    return {"document_id": document_id, "revision": revision, "ingestion": "Processing"}


@router.get("/documents/{document_id}/{revision}/chunks")
def document_chunks(document_id: str, revision: str, limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0)):
    return doc_ingest.list_chunks(_wrap(store.doc_pk, document_id, revision), limit, offset)


# ---- RoHS review ----
@router.get("/rohs")
def list_rohs(status: Optional[str] = None, document_id: Optional[str] = None):
    return rohs_store.list_records(status, document_id)


@router.post("/rohs/{record_id}/verify")
def verify_rohs(record_id: int, body: RohsVerifyBody, x_user: str = Header(DEFAULT_USER), x_role: str = Header(DEFAULT_ROLE)):
    edits = body.model_dump(exclude={"note"})
    return _wrap(rohs_store.verify, record_id, x_user, edits, body.note, x_role)


@router.post("/rohs/{record_id}/reject")
def reject_rohs(record_id: int, body: RohsRejectBody, x_user: str = Header(DEFAULT_USER), x_role: str = Header(DEFAULT_ROLE)):
    return _wrap(rohs_store.reject, record_id, x_user, body.note, x_role)


@router.get("/rag/health")
def rag_health():
    return doc_ingest.health()
