-- RoHS candidate records proposed by extraction; a human reviewer verifies them.
CREATE TABLE rohs_records (
  rohs_record_id bigserial PRIMARY KEY,
  doc_id        bigint NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  supplier      text,
  part_number   text,
  product_scope text,
  declaration_date date,
  valid_until   date,
  exemptions    jsonb NOT NULL DEFAULT '[]',
  source_page   integer,
  source_excerpt text,
  extraction_confidence real,
  field_confidence jsonb NOT NULL DEFAULT '{}',
  validation_status text NOT NULL DEFAULT 'Pending verification',   -- Pending verification | Verified | Rejected
  verified_by   text,
  verified_at   timestamptz,
  review_note   text,
  created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_rohs_doc    ON rohs_records(doc_id);
CREATE INDEX ix_rohs_lookup ON rohs_records (lower(supplier), lower(part_number));
