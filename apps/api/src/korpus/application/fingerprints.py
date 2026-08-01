from __future__ import annotations

import hashlib
from collections import Counter

from korpus.application.retrieval import tokenize


def simhash64(text: str) -> str:
    tokens = tokenize(text)
    if not tokens:
        return "0" * 16
    vector = [0] * 64
    for token, weight in Counter(tokens).items():
        digest = int.from_bytes(hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest(), "big")
        for bit in range(64):
            vector[bit] += weight if digest & (1 << bit) else -weight
    value = sum((1 << bit) for bit, score in enumerate(vector) if score >= 0)
    return f"{value:016x}"


def simhash_similarity(left: str, right: str) -> float:
    if len(left) != 16 or len(right) != 16:
        raise ValueError("simhash values must be 64-bit hexadecimal strings")
    distance = (int(left, 16) ^ int(right, 16)).bit_count()
    return 1.0 - distance / 64.0
