"""Small deterministic embeddings for local/demo mode. Can be replaced by a hosted embedder."""
from __future__ import annotations

import hashlib
import math
import re
from collections import Counter

DIMENSIONS = 1536
TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_'-]*", re.I)


def embed(text: str, dims: int = DIMENSIONS) -> list[float]:
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


def cosine(a: list[float] | None, b: list[float] | None) -> float:
    if not a or not b:
        return 0.0
    return sum(x * y for x, y in zip(a, b))


def hybrid_score(query: str, rule_text: str, rule_embedding: list[float] | None) -> float:
    q_tokens = set(TOKEN_RE.findall((query or "").lower()))
    r_tokens = set(TOKEN_RE.findall((rule_text or "").lower()))
    overlap = len(q_tokens & r_tokens) / max(1, len(q_tokens))
    return 0.70 * max(0, cosine(embed(query), rule_embedding)) + 0.30 * overlap
