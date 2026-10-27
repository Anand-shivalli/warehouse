-- Procedure check: what happened compared with the retrieved SOP requirements (advisory, shown to the reviewer).
ALTER TABLE incident_reports ADD COLUMN IF NOT EXISTS procedure_check jsonb NOT NULL DEFAULT '[]';
