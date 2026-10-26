"""Settings for parsing, chunking and embedding. All read from environment variables at call time."""
import os

CHUNKER_VERSION = "1"          # bump when chunking logic changes; stored per chunk so stale chunks are detectable


def _env(name, default):
    return os.getenv(name, default)


def embed_dim() -> int:
    return int(_env("EMBED_DIM", "768"))            # embeddinggemma = 768; must match the model


def embed_model() -> str:
    return _env("EMBED_MODEL", "embeddinggemma")


def ollama_url() -> str:
    return _env("OLLAMA_URL", "http://localhost:11434").rstrip("/")


def embedder_kind() -> str:
    return _env("EMBEDDER", "ollama")               # ollama | fake (tests / offline dev only)


def parser_pref() -> str:
    return _env("PARSER", "auto")                   # auto | docling | pypdf


def ocr_enabled() -> bool:
    return _env("OCR", "0") == "1"                  # OCR is slow on CPU; off unless you have scanned PDFs


def chunk_max_tokens() -> int:
    return int(_env("CHUNK_MAX_TOKENS", "512"))


def embed_batch() -> int:
    return int(_env("EMBED_BATCH", "16"))
