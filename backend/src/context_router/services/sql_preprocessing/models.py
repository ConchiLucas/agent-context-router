from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatchcase


@dataclass(frozen=True, slots=True)
class SqlPreprocessorConfig:
    processor_type: str
    options: dict[str, object]


@dataclass(frozen=True, slots=True)
class SqlPreprocessProfile:
    profile_id: str
    profile_hash: str
    project_patterns: tuple[str, ...]
    path_patterns: tuple[str, ...]
    dialects: tuple[str, ...]
    processors: tuple[SqlPreprocessorConfig, ...]
    max_candidates: int
    exclude_path_patterns: tuple[str, ...] = ()

    def matches(self, *, project_name: str, source_path: str, dialect: str) -> bool:
        return (
            any(fnmatchcase(project_name, pattern) for pattern in self.project_patterns)
            and any(fnmatchcase(source_path, pattern) for pattern in self.path_patterns)
            and not any(fnmatchcase(source_path, pattern) for pattern in self.exclude_path_patterns)
            and dialect.casefold() in self.dialects
        )

    def excludes(self, *, project_name: str, source_path: str, dialect: str) -> bool:
        return (
            any(fnmatchcase(project_name, pattern) for pattern in self.project_patterns)
            and any(fnmatchcase(source_path, pattern) for pattern in self.exclude_path_patterns)
            and dialect.casefold() in self.dialects
        )


@dataclass(frozen=True, slots=True)
class SqlPreprocessorProfiles:
    profiles: tuple[SqlPreprocessProfile, ...]

    def match(
        self,
        *,
        project_name: str,
        source_path: str,
        dialect: str,
    ) -> SqlPreprocessProfile | None:
        return next(
            (
                profile
                for profile in self.profiles
                if profile.matches(
                    project_name=project_name,
                    source_path=source_path,
                    dialect=dialect,
                )
            ),
            None,
        )

    def excluded_by(
        self,
        *,
        project_name: str,
        source_path: str,
        dialect: str,
    ) -> SqlPreprocessProfile | None:
        return next(
            (
                profile
                for profile in self.profiles
                if profile.excludes(
                    project_name=project_name,
                    source_path=source_path,
                    dialect=dialect,
                )
            ),
            None,
        )


@dataclass(frozen=True, slots=True)
class SqlPreprocessCandidate:
    candidate_id: str
    sql: str
    applied_rules: tuple[str, ...] = ()
    template_derived: bool = False


@dataclass(frozen=True, slots=True)
class SqlPreprocessDiagnostic:
    code: str
    message: str
    expression: str | None = None


@dataclass(frozen=True, slots=True)
class SqlPreprocessResult:
    candidates: tuple[SqlPreprocessCandidate, ...]
    diagnostics: tuple[SqlPreprocessDiagnostic, ...]
    profile_id: str | None = None
    profile_hash: str | None = None
