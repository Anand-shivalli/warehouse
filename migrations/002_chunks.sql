-- Document chunks (searchable passages). The vector size comes from EMBED_DIM when this migration first runs.
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE document_chunks (
  chunk_id     bigserial PRIMARY KEY,
  doc_id       bigint NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  chunk_index  integer NOT NULL,
  section_title text,
  page_start   integer,
  page_end     integer,
  content      text NOT NULL,
  embedding    vector({{EMBED_DIM}}) NOT NULL,
  embed_model  text NOT NULL,
  chunker_version text,
  created_at   timestamptz NOT NULL DEFAULT now(),
  -- stemmed text search for prose, plus an unstemmed one so IDs / part numbers / dates match exactly
  tsv          tsvector GENERATED ALWAYS AS (to_tsvector('english', coalesce(section_title,'') || ' ' || content)) STORED,
  tsv_exact    tsvector GENERATED ALWAYS AS (to_tsvector('simple',  coalesce(section_title,'') || ' ' || content)) STORED,
  UNIQUE (doc_id, chunk_index)
);
CREATE INDEX ix_chunks_doc   ON document_chunks(doc_id);
CREATE INDEX ix_chunks_tsv   ON document_chunks USING gin(tsv);
CREATE INDEX ix_chunks_exact ON document_chunks USING gin(tsv_exact);
CREATE INDEX ix_chunks_emb   ON document_chunks USING hnsw (embedding vector_cosine_ops);

