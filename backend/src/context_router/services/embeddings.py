from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Protocol


class EmbeddingProvider(Protocol):
    def embed(self, texts: Sequence[str]) -> list[list[float] | None]:
        """Return embeddings for texts, or None when embeddings are unavailable."""


class NoopEmbeddingProvider:
    def embed(self, texts: Sequence[str]) -> list[list[float] | None]:
        return [None for _ in texts]


def cosine_similarity(left: Sequence[float] | None, right: Sequence[float] | None) -> float:
    if left is None or right is None or len(left) != len(right) or not left:
        return 0.0

    numerator = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return numerator / (left_norm * right_norm)
