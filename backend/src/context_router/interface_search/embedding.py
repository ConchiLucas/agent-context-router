from __future__ import annotations

import hashlib
import math
import re
from typing import Protocol

import httpx

TOKEN_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9_./:-]*|[\u4e00-\u9fff]+")

SYNONYM_GROUPS = (
    (
        "查询",
        "搜索",
        "列表",
        "获取",
        "查看",
        "get",
        "search",
        "list",
        "query",
    ),
    ("新增", "创建", "录入", "添加", "create", "add", "insert"),
    ("修改", "更新", "编辑", "update", "edit"),
    ("删除", "作废", "取消", "delete", "cancel"),
)


class EmbeddingProvider(Protocol):
    dimensions: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...


def tokenize(text: str) -> list[str]:
    raw = [item.lower() for item in TOKEN_RE.findall(text)]
    tokens: list[str] = []
    for token in raw:
        tokens.append(token)
        if re.fullmatch(r"[\u4e00-\u9fff]+", token) and len(token) > 1:
            tokens.extend(token[index : index + 2] for index in range(len(token) - 1))
    return tokens


def expand_synonyms(text: str) -> str:
    lowered = text.lower()
    additions: list[str] = []
    for group in SYNONYM_GROUPS:
        if any(term.lower() in lowered for term in group):
            additions.extend(group)
    return f"{text} {' '.join(additions)}".strip()


class LocalFeatureEmbedding:
    """Deterministic development embedding; production should use a semantic model."""

    def __init__(self, dimensions: int = 1024) -> None:
        self.dimensions = dimensions

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(expand_synonyms(text)) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        values = [0.0] * self.dimensions
        for token in tokenize(text):
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=16).digest()
            index = int.from_bytes(digest[:8], "big") % self.dimensions
            sign = 1.0 if digest[8] % 2 == 0 else -1.0
            values[index] += sign
        norm = math.sqrt(sum(value * value for value in values)) or 1.0
        return [value / norm for value in values]


class OpenAICompatibleEmbedding:
    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str,
        dimensions: int,
        timeout: float = 30.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.dimensions = dimensions
        self.timeout = timeout

    def embed(self, texts: list[str]) -> list[list[float]]:
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        payload = {"model": self.model, "input": texts, "dimensions": self.dimensions}
        response = httpx.post(
            f"{self.base_url}/embeddings",
            headers=headers,
            json=payload,
            timeout=self.timeout,
        )
        response.raise_for_status()
        items = sorted(response.json()["data"], key=lambda item: item["index"])
        vectors = [item["embedding"] for item in items]
        if any(len(vector) != self.dimensions for vector in vectors):
            raise ValueError("embedding_dimensions_mismatch")
        return vectors


def create_embedding_provider(
    *,
    provider: str,
    dimensions: int,
    base_url: str = "",
    model: str = "",
    api_key: str = "",
) -> EmbeddingProvider:
    """Build an embedding provider and fail early on incomplete production config."""
    if provider == "local":
        return LocalFeatureEmbedding(dimensions)
    if provider != "openai_compatible":
        raise ValueError(f"unsupported_embedding_provider:{provider}")
    if not base_url.strip() or not model.strip():
        raise ValueError(
            "openai_compatible embeddings require EMBEDDING_BASE_URL and EMBEDDING_MODEL"
        )
    return OpenAICompatibleEmbedding(
        base_url=base_url,
        model=model,
        api_key=api_key,
        dimensions=dimensions,
    )


def cosine_similarity(left: list[float] | None, right: list[float]) -> float:
    if not left or len(left) != len(right):
        return 0.0
    return max(0.0, min(1.0, sum(a * b for a, b in zip(left, right, strict=True))))
