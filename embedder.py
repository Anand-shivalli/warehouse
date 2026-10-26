"""Embedding clients. Ollama (default) for real use; a deterministic hashing embedder for tests / offline dev.

Models differ in how they want text prefixed. The prefixes below are from each model's published usage as I
know it (not verified against your Ollama build); override with EMBED_DOC_PREFIX / EMBED_QUERY_PREFIX if the
retrieval quality looks off. The SAME model and prefixes must be used for indexing and for querying.
"""
import hashlib
import math
import os
import re

import httpx

import rag_config


class EmbedError(Exception):
    pass


# model-name prefix -> (document template, query template). {title} / {text} are filled in.
PREFIXES = {
    "embeddinggemma": ("title: {title} | text: {text}", "task: search result | query: {text}"),
    "nomic-embed-text": ("search_document: {text}", "search_query: {text}"),
}


def _templates(model: str):
    doc_t = os.getenv("EMBED_DOC_PREFIX")
    qry_t = os.getenv("EMBED_QUERY_PREFIX")
    base = next((v for k, v in PREFIXES.items() if model.startswith(k)), ("{text}", "{text}"))
    return (doc_t + "{text}" if doc_t is not None else base[0]), (qry_t + "{text}" if qry_t is not None else base[1])


class OllamaEmbedder:
    def __init__(self, model=None, url=None, dim=None, batch=None):
        self.model = model or rag_config.embed_model()
        self.url = url or rag_config.ollama_url()
        self.dim = dim or rag_config.embed_dim()
        self.batch = batch or rag_config.embed_batch()
        self.doc_tpl, self.qry_tpl = _templates(self.model)

    def _embed(self, inputs):
        try:
            r = httpx.post(f"{self.url}/api/embed", json={"model": self.model, "input": inputs}, timeout=300)
        except httpx.ConnectError:
            raise EmbedError(f"Cannot reach Ollama at {self.url}. Start it with `ollama serve`.")
        except httpx.TimeoutException:
            raise EmbedError("Ollama timed out while embedding (CPU-only machines are slow; try a smaller EMBED_BATCH).")
        if r.status_code == 404:
            raise EmbedError(f"Ollama has no model '{self.model}'. Run `ollama pull {self.model}`.")
        if r.status_code != 200:
            raise EmbedError(f"Ollama returned {r.status_code}: {r.text[:200]}")
        vecs = r.json().get("embeddings")
        if not vecs or len(vecs) != len(inputs):
            raise EmbedError("Ollama returned an unexpected number of embeddings.")
        if len(vecs[0]) != self.dim:
            raise EmbedError(f"Model '{self.model}' returns {len(vecs[0])}-dim vectors but EMBED_DIM={self.dim}. "
                             "Set EMBED_DIM to the model's size (and recreate the chunks table if it already exists).")
        return vecs

    def embed_documents(self, texts, titles=None):
        titles = titles or [""] * len(texts)
        prepared = [self.doc_tpl.format(title=(t or "none"), text=x) for x, t in zip(texts, titles)]
        out = []
        for i in range(0, len(prepared), self.batch):
            out.extend(self._embed(prepared[i:i + self.batch]))
        return out

    def embed_query(self, text):
        return self._embed([self.qry_tpl.format(title="none", text=text)])[0]

    def ping(self):
        return len(self._embed(["ping"])[0])


class FakeEmbedder:
    """Bag-of-words hashing into `dim` buckets, L2-normalised. Texts that share words get similar vectors, so
    retrieval tests behave sensibly. NOT a semantic model."""
    model = "fake-hash"

    def __init__(self, dim=None):
        self.dim = dim or rag_config.embed_dim()

    def _vec(self, text):
        v = [0.0] * self.dim
        for w in re.findall(r"[a-z0-9]+", text.lower()):
            v[int(hashlib.md5(w.encode()).hexdigest(), 16) % self.dim] += 1.0
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / n for x in v]

    def embed_documents(self, texts, titles=None):
        return [self._vec(t) for t in texts]

    def embed_query(self, text):
        return self._vec(text)

    def ping(self):
        return self.dim


def get_embedder():
    return FakeEmbedder() if rag_config.embedder_kind() == "fake" else OllamaEmbedder()
