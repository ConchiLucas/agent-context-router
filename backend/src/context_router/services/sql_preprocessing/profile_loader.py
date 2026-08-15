from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml

from context_router.services.sql_preprocessing.models import (
    SqlPreprocessorConfig,
    SqlPreprocessorProfiles,
    SqlPreprocessProfile,
)


class SqlPreprocessorProfileError(RuntimeError):
    pass


class SqlPreprocessorProfileLoader:
    RELATIVE_PATH = Path("deploy/context-router/sql-preprocessors.yaml")
    _ALLOWED_PROCESSORS = frozenset(
        {
            "freemarker_comments",
            "freemarker_conditions",
            "freemarker_lists",
            "angle_conditionals",
            "known_wrapper",
            "value_placeholders",
            "dynamic_identifier_guard",
            "named_order_direction",
        }
    )

    def load(self, workspace_root: Path) -> SqlPreprocessorProfiles:
        path = workspace_root / self.RELATIVE_PATH
        if not path.is_file():
            return SqlPreprocessorProfiles(profiles=())
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, yaml.YAMLError) as exc:
            raise SqlPreprocessorProfileError(f"SQL 预处理配置无法读取：{exc}") from exc
        if not isinstance(raw, dict) or raw.get("version") != 1:
            raise SqlPreprocessorProfileError("SQL 预处理配置 version 必须为 1")
        defaults = raw.get("defaults") or {}
        if not isinstance(defaults, dict):
            raise SqlPreprocessorProfileError("SQL 预处理 defaults 必须是对象")
        default_limit = self._candidate_limit(defaults.get("max_candidates_per_file", 12))
        raw_profiles = raw.get("profiles") or []
        if not isinstance(raw_profiles, list):
            raise SqlPreprocessorProfileError("SQL 预处理 profiles 必须是数组")
        profiles: list[SqlPreprocessProfile] = []
        identifiers: set[str] = set()
        for index, item in enumerate(raw_profiles, start=1):
            if not isinstance(item, dict):
                raise SqlPreprocessorProfileError(f"第 {index} 个 Profile 必须是对象")
            profile_id = str(item.get("id") or "").strip()
            if not profile_id or len(profile_id) > 128:
                raise SqlPreprocessorProfileError(f"第 {index} 个 Profile id 无效")
            if profile_id in identifiers:
                raise SqlPreprocessorProfileError(f"Profile id 重复：{profile_id}")
            identifiers.add(profile_id)
            match = item.get("match") or {}
            if not isinstance(match, dict):
                raise SqlPreprocessorProfileError(f"Profile {profile_id} 的 match 必须是对象")
            projects = self._patterns(match.get("projects"), default=("*",))
            paths = self._patterns(match.get("paths"), default=("**/*.sql", "*.sql"))
            exclude_paths = self._optional_patterns(match.get("exclude_paths"))
            dialects = tuple(
                value.casefold()
                for value in self._patterns(match.get("dialects"), default=("mysql",))
            )
            raw_processors = item.get("processors") or []
            if not isinstance(raw_processors, list) or not raw_processors:
                raise SqlPreprocessorProfileError(f"Profile {profile_id} 至少需要一个 processor")
            processors: list[SqlPreprocessorConfig] = []
            for raw_processor in raw_processors:
                if not isinstance(raw_processor, dict):
                    raise SqlPreprocessorProfileError(
                        f"Profile {profile_id} 的 processor 必须是对象"
                    )
                processor_type = str(raw_processor.get("type") or "").strip()
                if processor_type not in self._ALLOWED_PROCESSORS:
                    raise SqlPreprocessorProfileError(
                        f"Profile {profile_id} 使用未知 processor：{processor_type}"
                    )
                options = {str(key): value for key, value in raw_processor.items() if key != "type"}
                self._validate_processor_options(profile_id, processor_type, options)
                processors.append(
                    SqlPreprocessorConfig(
                        processor_type=processor_type,
                        options=options,
                    )
                )
            canonical = {
                "id": profile_id,
                "match": {
                    "projects": projects,
                    "paths": paths,
                    "exclude_paths": exclude_paths,
                    "dialects": dialects,
                },
                "processors": raw_processors,
                "max_candidates": item.get("max_candidates", default_limit),
            }
            profile_hash = hashlib.sha256(
                json.dumps(canonical, ensure_ascii=False, sort_keys=True).encode("utf-8")
            ).hexdigest()
            profiles.append(
                SqlPreprocessProfile(
                    profile_id=profile_id,
                    profile_hash=profile_hash,
                    project_patterns=projects,
                    path_patterns=paths,
                    dialects=dialects,
                    processors=tuple(processors),
                    max_candidates=self._candidate_limit(item.get("max_candidates", default_limit)),
                    exclude_path_patterns=exclude_paths,
                )
            )
        return SqlPreprocessorProfiles(profiles=tuple(profiles))

    @staticmethod
    def _patterns(value: object, *, default: tuple[str, ...]) -> tuple[str, ...]:
        if value is None:
            return default
        if not isinstance(value, list) or not value:
            raise SqlPreprocessorProfileError("Profile 匹配条件必须是非空字符串数组")
        patterns = tuple(str(item).strip() for item in value)
        if any(not item or len(item) > 500 for item in patterns):
            raise SqlPreprocessorProfileError("Profile 匹配条件包含无效模式")
        return patterns

    @staticmethod
    def _candidate_limit(value: object) -> int:
        if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 64:
            raise SqlPreprocessorProfileError("max_candidates 必须在 1 到 64 之间")
        return value

    @classmethod
    def _optional_patterns(cls, value: object) -> tuple[str, ...]:
        if value is None:
            return ()
        return cls._patterns(value, default=())

    @staticmethod
    def _validate_processor_options(
        profile_id: str,
        processor_type: str,
        options: dict[str, object],
    ) -> None:
        if processor_type == "freemarker_conditions" and options.get(
            "strategy", "cartesian"
        ) not in {"cartesian", "baseline_and_single"}:
            raise SqlPreprocessorProfileError(
                f"Profile {profile_id} 的 freemarker_conditions strategy 无效"
            )
        if (
            processor_type == "freemarker_conditions"
            and "relation_only" in options
            and not isinstance(options["relation_only"], bool)
        ):
            raise SqlPreprocessorProfileError(
                f"Profile {profile_id} 的 freemarker_conditions relation_only 必须是布尔值"
            )
        if processor_type == "angle_conditionals" and options.get("mode", "exclude") not in {
            "exclude",
            "include",
        }:
            raise SqlPreprocessorProfileError(
                f"Profile {profile_id} 的 angle_conditionals mode 无效"
            )
        if (
            processor_type == "value_placeholders"
            and "strict" in options
            and not isinstance(options["strict"], bool)
        ):
            raise SqlPreprocessorProfileError(
                f"Profile {profile_id} 的 value_placeholders strict 必须是布尔值"
            )
        if processor_type == "named_order_direction":
            names = options.get("names")
            if (
                not isinstance(names, list)
                or not names
                or any(
                    not isinstance(item, str) or not item.strip() or len(item) > 128
                    for item in names
                )
            ):
                raise SqlPreprocessorProfileError(
                    f"Profile {profile_id} 的 named_order_direction names 无效"
                )
