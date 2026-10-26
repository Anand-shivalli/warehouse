# Backend: PostgreSQL + document ingestion (Part A)

Put every file from the zip in the project root (next to `api.py`); `migrations/` goes there as a folder.
Run with `uvicorn server:app --reload --port 8000` from that root.

## One-time setup
1. PostgreSQL 16 with the pgvector extension, a database `incidents`, user `incident` (the apt steps from the chat).
2. `cp .env.example .env` and set `DATABASE_URL`.
3. `pip install -r requirements-backend.txt`
4. Embeddings: `ollama pull embeddinggemma` (Ollama must be running).
5. Start the server. Tables are created automatically (`migrations/*.sql`, applied once each).
6. Check everything: open `http://localhost:8000/api/rag/health`. You want `embedder_ok: true`, and `table_dim` equal to `embed_dim`.

Optional, better parsing: `pip install torch --index-url https://download.pytorch.org/whl/cpu` then `pip install docling`.
Without it the pypdf / python-docx fallback is used and documents are marked "Needs review" with a note (under `PARSER=auto`).

## Try it
```bash
curl -F "file=@spill_sop.pdf" -F document_id=SOP-014 -F type=SOP -F title="Chemical spill response" -F revision=C \
     http://localhost:8000/api/documents
curl http://localhost:8000/api/documents                      # ingestion: Processing -> Indexed / Needs review / Failed
curl "http://localhost:8000/api/documents/SOP-014/C/chunks"   # see exactly what was indexed (text, page, section)
curl -X POST http://localhost:8000/api/documents/SOP-014/C/status -H 'Content-Type: application/json' -d '{"status":"Effective"}'
```
`type` is `SOP`, `RoHS` or `Guideline`. A new document starts as Draft (RoHS: Pending verification). Only an **Effective**
revision should be treated as current guidance; marking one Effective supersedes the previous one (kept, with an end date).

RoHS: after upload, `GET /api/rohs` lists the proposed records. A reviewer calls `POST /api/rohs/{id}/verify`
(optionally correcting fields; supplier, part number and declaration date must be filled) or `/reject` (note required).

## Changing the embedding model
The vector size is fixed when the chunks table is created. If the new model has a different size:
```sql
DROP TABLE document_chunks;
DELETE FROM schema_migrations WHERE version = '002_chunks.sql';
```
Set `EMBED_MODEL` and `EMBED_DIM`, restart the server (recreates the table), then `python doc_ingest.py --all`.

## Settings
| Variable | Default | Meaning |
|---|---|---|
| DATABASE_URL | postgresql://incident:incident@localhost:5432/incidents | Postgres connection |
| EMBED_MODEL / EMBED_DIM | embeddinggemma / 768 | Ollama model and its vector size |
| OLLAMA_URL | http://localhost:11434 | |
| PARSER | auto | auto, docling or pypdf |
| OCR | 0 | 1 turns on OCR for scanned PDFs (slow on CPU) |
| CHUNK_MAX_TOKENS | 512 | Target chunk size |
| EMBED_BATCH | 16 | Chunks per Ollama call (lower it if Ollama times out) |
| EMBED_DOC_PREFIX / EMBED_QUERY_PREFIX | per model | Override the model's text prefixes |

## Tests
Use an empty database whose name ends in `_test` (its schema is wiped every run):
```bash
sudo -u postgres createdb -O incident incidents_test
sudo -u postgres psql -d incidents_test -c "CREATE EXTENSION vector;"
export TEST_DATABASE_URL=postgresql://incident:CHANGE_ME@localhost:5432/incidents_test
pip install pytest reportlab && python -m pytest -q
```
The tests use a fake embedder and the pypdf parser, so they need neither Ollama nor Docling.

## Not covered yet
- Searching (`search_sops`, `lookup_rohs`) and wiring retrieval into the agents: Part B.
- Real Docling and Ollama runs: not exercised by the tests; use `/api/rag/health` and upload a real SOP to check them.
- Authentication: `X-User` / `X-Role` headers are trusted as sent. Not safe to expose beyond a local demo.
