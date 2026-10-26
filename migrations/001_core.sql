-- Core incident tables (workbook: Data Dictionary + Session & Upload Correlation sheets).
-- Timestamps are timestamptz (UTC); structured payloads are JSONB.

CREATE TABLE incidents (
  incident_id     text PRIMARY KEY,
  title           text NOT NULL,
  priority        text NOT NULL,
  status          text NOT NULL,
  incident_type   text,
  source          text,
  site_id         text,
  zone_id         text,
  camera_id       text,
  equipment_id    text,
  assigned_to     text NOT NULL DEFAULT 'Unassigned',
  occurred_at     timestamptz,
  received_at     timestamptz,
  created_at      timestamptz NOT NULL DEFAULT now(),
  affected        jsonb NOT NULL DEFAULT '[]',
  class_category  text,
  class_confidence real,
  class_flags     jsonb NOT NULL DEFAULT '[]'
);

CREATE TABLE reporting_sessions (
  reporting_session_id text PRIMARY KEY,
  incident_id  text NOT NULL REFERENCES incidents(incident_id),
  opened_at    timestamptz,
  closed_at    timestamptz,
  created_by   text,
  channel      text,
  status       text NOT NULL DEFAULT 'open'
);

CREATE TABLE assets (
  asset_id     text PRIMARY KEY,
  incident_id  text NOT NULL REFERENCES incidents(incident_id),
  reporting_session_id text REFERENCES reporting_sessions(reporting_session_id),
  type         text,
  name         text,
  size         text,
  size_bytes   bigint,
  mime_type    text,
  storage_key  text,
  checksum     text,
  captured_at  timestamptz,
  uploaded_at  timestamptz,
  uploader     text
);
CREATE INDEX ix_assets_inc ON assets(incident_id);

CREATE TABLE detections (
  id          bigserial PRIMARY KEY,
  incident_id text NOT NULL REFERENCES incidents(incident_id),
  model       text, event text, confidence real, offset_s real
);

CREATE TABLE transcript (
  id          bigserial PRIMARY KEY,
  incident_id text NOT NULL REFERENCES incidents(incident_id),
  source_asset_id text,
  transcript_type text NOT NULL DEFAULT 'raw',
  t text, speaker text, text text
);

CREATE TABLE locations (
  id          bigserial PRIMARY KEY,
  incident_id text NOT NULL REFERENCES incidents(incident_id),
  reporting_session_id text,
  asset_id    text,
  source_type text, method text,
  lat double precision, lon double precision, accuracy_m double precision,
  captured_at timestamptz, received_at timestamptz,
  validation  text
);
CREATE INDEX ix_loc_inc ON locations(incident_id);

CREATE TABLE agent_runs (
  run_id      text PRIMARY KEY,
  incident_id text NOT NULL REFERENCES incidents(incident_id),
  reporting_session_id text,
  agent       text, status text,
  started_at  timestamptz, duration_s real,
  output      jsonb
);
CREATE INDEX ix_runs_inc ON agent_runs(incident_id);

CREATE TABLE retrieval_events (
  id          bigserial PRIMARY KEY,
  incident_id text NOT NULL REFERENCES incidents(incident_id),
  query       text,
  hits        jsonb NOT NULL DEFAULT '[]',
  created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE incident_reports (
  report_id   text PRIMARY KEY,
  incident_id text NOT NULL UNIQUE REFERENCES incidents(incident_id),
  version     integer NOT NULL DEFAULT 1,
  review_status text,
  generated_by  text,
  summary     text,
  observed        jsonb NOT NULL DEFAULT '[]',
  interpretation  jsonb NOT NULL DEFAULT '[]',
  unknowns        jsonb NOT NULL DEFAULT '[]',
  recommendations jsonb NOT NULL DEFAULT '[]',
  citations       jsonb NOT NULL DEFAULT '[]',
  reviewed_by text,
  review_note text
);

CREATE TABLE audit_logs (
  id          bigserial PRIMARY KEY,
  incident_id text REFERENCES incidents(incident_id),
  entity_type text NOT NULL DEFAULT 'incident',
  entity_id   text,
  actor       text,
  role        text,
  action      text NOT NULL,
  note        text,
  at          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_audit_inc ON audit_logs(incident_id);

CREATE FUNCTION audit_logs_immutable() RETURNS trigger AS $$
BEGIN RAISE EXCEPTION 'audit_logs is append-only'; END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER audit_no_change BEFORE UPDATE OR DELETE ON audit_logs
  FOR EACH ROW EXECUTE FUNCTION audit_logs_immutable();

-- One row per file revision (workbook: "do not overwrite history"). document_id is the business ID (e.g. SOP-014).
CREATE TABLE documents (
  id             bigserial PRIMARY KEY,
  document_id    text NOT NULL,
  document_type  text NOT NULL CHECK (document_type IN ('SOP','RoHS','Guideline')),
  title          text NOT NULL,
  revision       text NOT NULL,
  status         text,                       -- Draft | Effective | Superseded | Pending verification
  effective_from date,
  effective_to   date,
  owner          text,
  applies_to_sites text[],                   -- NULL = all sites (extension: the workbook says filter by site but names no column)
  original_filename text,
  storage_key    text,
  checksum       text,
  uploader       text,
  uploaded_at    timestamptz,
  ingestion      text NOT NULL DEFAULT 'Processing',   -- Processing | Indexed | Needs review | Failed (UI vocabulary)
  ingest_stage   text,                       -- queued | parsing | embedding | done | failed
  parser         text,
  parser_version text,
  ocr_used       boolean,
  pages          integer,
  chunker_version text,
  embed_model    text,
  indexed_at     timestamptz,
  warnings       jsonb NOT NULL DEFAULT '[]',
  UNIQUE (document_id, revision)
);
