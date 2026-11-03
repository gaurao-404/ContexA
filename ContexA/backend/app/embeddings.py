"""Embedding adapters for offline/demo and optional local Ollama semantic retrieval.

The fallback hashed-token vector keeps exact/lexical retrieval available without an AI
service. When Ollama embeddings are enabled, callers must rebuild stored vectors before
mixing the new model with previously indexed vectors.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import urllib.error
import urllib.request
from collections import Counter

DIMENSIONS = 1536
TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_'-]*", re.I)


def embedding_model_label() -> str:
    """Configured semantic embedder; actual fallback is reported by embed_with_model."""
    if os.getenv("OLLAMA_EMBEDDINGS_ENABLED", "false").lower() in {"1", "true", "yes"}:
        return f"ollama:{os.getenv('OLLAMA_EMBEDDING_MODEL', 'nomic-embed-text')}"
    return "hashed-token-v1"


def _hashed_embed(text: str, dims: int) -> list[float]:
    vector = [0.0] * dims
    tokens = TOKEN_RE.findall((text or "").lower())
    for token, count in Counter(tokens).items():
        raw = hashlib.blake2b(token.encode(), digest_size=8).digest()
        number = int.from_bytes(raw, "big")
        index = number % dims
        sign = 1.0 if (number >> 9) & 1 else -1.0
        vector[index] += sign * (1.0 + math.log(1 + count))
    norm = math.sqrt(sum(v * v for v in vector)) or 1.0
    return [v / norm for v in vector]


def _ollama_embed(text: str, dims: int) -> list[float] | None:
    base = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
    model = os.getenv("OLLAMA_EMBEDDING_MODEL", "nomic-embed-text")
    timeout = float(os.getenv("OLLAMA_EMBEDDING_TIMEOUT", "25"))
    payload = json.dumps({"model": model, "input": text[:12000]}).encode("utf-8")
    request = urllib.request.Request(base + "/api/embed", data=payload,
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
        vectors = data.get("embeddings")
        vector = vectors[0] if isinstance(vectors, list) and vectors and isinstance(vectors[0], list) else data.get("embedding")
        if not isinstance(vector, list) or not vector:
            return None
        values = [float(v) for v in vector]
        # Keep the existing vector(1536) schema compatible. The source dimension is
        # recorded in the model label; zero-padding preserves its original dot product.
        values = values[:dims] + [0.0] * max(0, dims - len(values))
        norm = math.sqrt(sum(v * v for v in values)) or 1.0
        return [v / norm for v in values]
    except (OSError, ValueError, KeyError, TypeError, urllib.error.URLError):
        return None


def embed_with_model(text: str, dims: int = DIMENSIONS) -> tuple[list[float], str]:
    """Return a vector and the model that actually produced it (including fallback)."""
    if os.getenv("OLLAMA_EMBEDDINGS_ENABLED", "false").lower() in {"1", "true", "yes"}:
        result = _ollama_embed(text, dims)
        if result is not None:
            return result, f"ollama:{os.getenv('OLLAMA_EMBEDDING_MODEL', 'nomic-embed-text')}"
    return _hashed_embed(text, dims), "hashed-token-v1"


def embed(text: str, dims: int = DIMENSIONS) -> list[float]:
    return embed_with_model(text, dims)[0]

def cosine(a: list[float] | None, b: list[float] | None) -> float:
    if not a or not b:
        return 0.0
    return sum(x * y for x, y in zip(a, b))


def hybrid_score(query: str, rule_text: str, rule_embedding: list[float] | None,
                 query_embedding: list[float] | None = None) -> float:
    q_tokens = set(TOKEN_RE.findall((query or "").lower()))
    r_tokens = set(TOKEN_RE.findall((rule_text or "").lower()))
    overlap = len(q_tokens & r_tokens) / max(1, len(q_tokens))
    vector = query_embedding if query_embedding is not None else embed(query)
    return 0.70 * max(0, cosine(vector, rule_embedding)) + 0.30 * overlap
