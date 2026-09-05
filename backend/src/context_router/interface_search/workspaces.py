from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class WorkspaceTerm(BaseModel):
    dimension: str = Field(min_length=1, max_length=80)
    canonical_value: str = Field(min_length=1, max_length=240)
    aliases: list[str] = Field(default_factory=list, max_length=100)
    mapped_values: dict[str, list[str]] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    priority: int = Field(default=0, ge=-100, le=100)
    source: str = Field(default="workspace_config", max_length=80)
    confidence: float = Field(default=1.0, ge=0, le=1)
    active: bool = True


class WorkspaceProfile(BaseModel):
    workspace_id: str = Field(min_length=1, max_length=120)
    name: str = Field(min_length=1, max_length=240)
    source_root: str = Field(default="", max_length=1000)
    semantic_profile_version: str = Field(default="v1", max_length=80)
    metadata: dict[str, Any] = Field(default_factory=dict)
    terms: list[WorkspaceTerm] = Field(default_factory=list)

    def mapping(self, dimension: str) -> dict[str, tuple[str, ...]]:
        result: dict[str, tuple[str, ...]] = {}
        for term in self.terms:
            if not term.active or term.dimension != dimension:
                continue
            result[term.canonical_value] = tuple(
                dict.fromkeys([term.canonical_value, *term.aliases])
            )
        return result

    def match(self, text: str, dimension: str) -> list[str]:
        lowered = _normalize(text)
        matches: list[tuple[int, int, str]] = []
        for term in self.terms:
            if not term.active or term.dimension != dimension:
                continue
            aliases = [term.canonical_value, *term.aliases]
            longest = max(
                (len(_normalize(alias)) for alias in aliases if _normalize(alias) in lowered),
                default=0,
            )
            if longest:
                matches.append((term.priority, longest, term.canonical_value))
        matches.sort(reverse=True)
        return list(dict.fromkeys(item[2] for item in matches))

    def match_occurrences(self, text: str, dimension: str) -> list[tuple[str, int, int, int, str]]:
        """Return canonical term matches with normalized spans for role analysis."""

        lowered = _normalize(text)
        matches: list[tuple[str, int, int, int, str]] = []
        for term in self.terms:
            if not term.active or term.dimension != dimension:
                continue
            for alias in dict.fromkeys([term.canonical_value, *term.aliases]):
                needle = _normalize(alias)
                if not needle:
                    continue
                cursor = 0
                exact_match = False
                while (position := lowered.find(needle, cursor)) >= 0:
                    exact_match = True
                    matches.append(
                        (
                            term.canonical_value,
                            position,
                            position + len(needle),
                            term.priority,
                            alias,
                        )
                    )
                    cursor = position + max(1, len(needle))
                if not exact_match and dimension == "resource":
                    span = _dense_ordered_span(needle, lowered)
                    if span:
                        matches.append(
                            (
                                term.canonical_value,
                                span[0],
                                span[1],
                                term.priority,
                                alias,
                            )
                        )
        matches.sort(key=lambda item: (item[1], -len(_normalize(item[4])), -item[3]))
        return matches

    def canonicalize(
        self, value: str, dimension: str, *, preserve_unknown: bool = True
    ) -> str | None:
        normalized = value.strip()
        if not normalized:
            return None
        needle = _normalize(normalized)
        for canonical, aliases in self.mapping(dimension).items():
            if any(needle == _normalize(alias) for alias in aliases):
                return canonical
        return normalized if preserve_unknown else None

    def synonym_groups(
        self, dimensions: tuple[str, ...] | None = None
    ) -> tuple[tuple[str, ...], ...]:
        allowed = set(dimensions) if dimensions else None
        return tuple(
            tuple(dict.fromkeys([term.canonical_value, *term.aliases]))
            for term in self.terms
            if term.active and (allowed is None or term.dimension in allowed)
        )

    def expand_text(self, text: str, dimensions: tuple[str, ...] | None = None) -> str:
        expanded = [text]
        normalized_text = _normalize(text)
        allowed = set(dimensions) if dimensions else None
        for term in self.terms:
            if not term.active or (allowed is not None and term.dimension not in allowed):
                continue
            group = tuple(dict.fromkeys([term.canonical_value, *term.aliases]))
            canonical_match = _normalize(term.canonical_value) in normalized_text
            alias_match = any(
                (
                    _matches_normalized_alias(_normalize(alias), normalized_text)
                    if term.dimension == "endpoint_alias"
                    else _normalize(alias) in normalized_text
                )
                for alias in term.aliases
            )
            if canonical_match or alias_match:
                expanded.extend(group)
        return " ".join(dict.fromkeys(item for item in expanded if item))

    def term(self, dimension: str, canonical_value: str) -> WorkspaceTerm | None:
        return next(
            (
                term
                for term in self.terms
                if term.active
                and term.dimension == dimension
                and term.canonical_value == canonical_value
            ),
            None,
        )


def load_workspace_profile(path: Path) -> WorkspaceProfile:
    return WorkspaceProfile.model_validate_json(path.read_text(encoding="utf-8"))


def dump_workspace_profile(profile: WorkspaceProfile) -> str:
    return json.dumps(profile.model_dump(mode="json"), ensure_ascii=False, indent=2)


def _normalize(value: str) -> str:
    return re.sub(r"[\s_\-]+", "", value).lower()


def _matches_normalized_alias(alias: str, text: str) -> bool:
    """Match long phrases with small inserted modifiers, without fuzzy short terms.

    Chinese users often insert audience or service qualifiers inside a configured
    phrase (for example, ``公路[服务运营端]撤回承运订单``).  A constrained ordered
    match preserves the phrase order and requires a dense span, so it does not
    turn the workspace lexicon into unrestricted fuzzy matching.
    """

    return _dense_ordered_span(alias, text) is not None


def _dense_ordered_span(alias: str, text: str) -> tuple[int, int] | None:
    if not alias:
        return None
    if alias in text:
        start = text.index(alias)
        return start, start + len(alias)
    if len(alias) < 6:
        return None
    best: tuple[int, int] | None = None
    start = text.find(alias[0])
    while start >= 0:
        positions = [start]
        cursor = start + 1
        for character in alias[1:]:
            position = text.find(character, cursor)
            if position < 0:
                positions = []
                break
            positions.append(position)
            cursor = position + 1
        if positions:
            candidate = (positions[0], positions[-1] + 1)
            if best is None or candidate[1] - candidate[0] < best[1] - best[0]:
                best = candidate
        start = text.find(alias[0], start + 1)
    if best is None:
        return None
    span = best[1] - best[0]
    return best if len(alias) / span >= 0.63 else None
