from __future__ import annotations

import hashlib
import re

from context_router.services.sql_preprocessing.models import (
    SqlPreprocessCandidate,
    SqlPreprocessDiagnostic,
    SqlPreprocessorConfig,
    SqlPreprocessProfile,
    SqlPreprocessResult,
)


class SqlPreprocessorPipeline:
    _COMMENT_RE = re.compile(r"<#--.*?-->", re.DOTALL)
    _PLACEHOLDER_RE = re.compile(r"\$\{[^{}]+}")
    _DYNAMIC_IDENTIFIER_RE = re.compile(
        r"(?is)(?:\b(?:from|join|update|into|table)\s+[^\s,;()]*\$\{|"
        r"[A-Za-z0-9_$]+\$\{|\$\{[^{}]+}[A-Za-z0-9_$]+)"
    )
    _UNKNOWN_DIRECTIVE_RE = re.compile(r"</?#(?:if|else|elseif|list)\b|</?#\w+", re.I)
    _IF_DIRECTIVE = r"<#if\b(?:[^()>'\"]+|'[^']*'|\"[^\"]*\"|\([^()]*\))*?>"
    _ELSEIF_DIRECTIVE = r"<#elseif\b(?:[^()>'\"]+|'[^']*'|\"[^\"]*\"|\([^()]*\))*?>"
    _IF_OPEN_RE = re.compile(_IF_DIRECTIVE, re.I)
    _IF_TOKEN_RE = re.compile(
        rf"{_IF_DIRECTIVE}|{_ELSEIF_DIRECTIVE}|<#else\s*>|</#if\s*>",
        re.I,
    )
    _LIST_RE = re.compile(r"<#list\b[^>]*>.*?</#list\s*>", re.I | re.DOTALL)
    _ANGLE_RE = re.compile(r"<<(?P<body>.*?)>>", re.DOTALL)
    _STRUCTURAL_VALUE_PREFIX_RE = re.compile(
        r"(?is)\b(?:from|join|update|into|table|order\s+by|group\s+by|as)\s*$"
    )

    def process(self, statement: str, profile: SqlPreprocessProfile) -> SqlPreprocessResult:
        candidates = [SqlPreprocessCandidate(candidate_id="base", sql=statement)]
        diagnostics: list[SqlPreprocessDiagnostic] = []
        for config in profile.processors:
            candidates, processor_diagnostics = self._apply(candidates, config, profile)
            diagnostics.extend(processor_diagnostics)
            candidates = self._deduplicate(candidates)
            if len(candidates) > profile.max_candidates:
                candidates = candidates[: profile.max_candidates]
                diagnostics.append(
                    SqlPreprocessDiagnostic(
                        code="template_candidate_limit_exceeded",
                        message=(f"模板候选超过 {profile.max_candidates} 条，只保留有界候选"),
                    )
                )
        safe_candidates: list[SqlPreprocessCandidate] = []
        for candidate in candidates:
            if self._UNKNOWN_DIRECTIVE_RE.search(candidate.sql):
                diagnostics.append(
                    SqlPreprocessDiagnostic(
                        code="template_directive_unsupported",
                        message="仍包含无法安全处理的模板指令，候选未进入 SQL 解析",
                    )
                )
                continue
            if candidate.sql.strip():
                safe_candidates.append(candidate)
        return SqlPreprocessResult(
            candidates=tuple(safe_candidates),
            diagnostics=tuple(diagnostics),
            profile_id=profile.profile_id,
            profile_hash=profile.profile_hash,
        )

    def _apply(
        self,
        candidates: list[SqlPreprocessCandidate],
        config: SqlPreprocessorConfig,
        profile: SqlPreprocessProfile,
    ) -> tuple[list[SqlPreprocessCandidate], list[SqlPreprocessDiagnostic]]:
        processor_type = config.processor_type
        if processor_type == "freemarker_comments":
            return self._map_text(candidates, processor_type, self._remove_comments), []
        if processor_type == "freemarker_lists":
            return self._remove_lists(candidates, processor_type)
        if processor_type == "freemarker_conditions":
            strategy = str(config.options.get("strategy") or "cartesian").strip().casefold()
            relation_only = config.options.get("relation_only") is True
            return self._expand_conditions(
                candidates,
                processor_type,
                profile.max_candidates,
                strategy=strategy,
                relation_only=relation_only,
            )
        if processor_type == "angle_conditionals":
            mode = str(config.options.get("mode") or "exclude").strip().casefold()
            return self._angle_conditionals(candidates, processor_type, mode=mode), []
        if processor_type == "known_wrapper":
            names = config.options.get("names")
            wrappers = tuple(str(item) for item in names) if isinstance(names, list) else ()
            return self._unwrap_known(candidates, processor_type, wrappers), []
        if processor_type == "dynamic_identifier_guard":
            return self._guard_dynamic_identifiers(candidates)
        if processor_type == "value_placeholders":
            strict = config.options.get("strict") is True
            return self._replace_value_placeholders(candidates, processor_type, strict=strict)
        if processor_type == "named_order_direction":
            names = config.options.get("names")
            allowed = tuple(str(item) for item in names) if isinstance(names, list) else ()
            return self._replace_order_directions(candidates, processor_type, allowed), []
        return candidates, []

    def _remove_comments(self, sql: str) -> tuple[str, bool]:
        return self._COMMENT_RE.subn(" ", sql)[0], bool(self._COMMENT_RE.search(sql))

    def _replace_values(self, sql: str) -> tuple[str, bool]:
        return self._PLACEHOLDER_RE.subn("0", sql)[0], bool(self._PLACEHOLDER_RE.search(sql))

    def _replace_value_placeholders(
        self,
        candidates: list[SqlPreprocessCandidate],
        rule: str,
        *,
        strict: bool,
    ) -> tuple[list[SqlPreprocessCandidate], list[SqlPreprocessDiagnostic]]:
        output: list[SqlPreprocessCandidate] = []
        diagnostics: list[SqlPreprocessDiagnostic] = []
        for candidate in candidates:
            matches = list(self._PLACEHOLDER_RE.finditer(candidate.sql))
            if strict:
                unsafe = next(
                    (
                        match
                        for match in matches
                        if not self._is_value_placeholder(candidate.sql, match)
                    ),
                    None,
                )
                if unsafe is not None:
                    diagnostics.append(
                        SqlPreprocessDiagnostic(
                            code="template_expression_unsupported",
                            message="模板表达式不在可证明的值位置，候选未进入 SQL 解析",
                            expression=unsafe.group(0),
                        )
                    )
                    continue
            sql, changed = self._replace_values(candidate.sql)
            output.append(self._derived(candidate, sql, rule) if changed else candidate)
        return output, diagnostics

    def _is_value_placeholder(self, sql: str, match: re.Match[str]) -> bool:
        before = sql[: match.start()]
        after = sql[match.end() :]
        if self._STRUCTURAL_VALUE_PREFIX_RE.search(before[-120:]):
            return False
        if before.endswith("'") and after.startswith("'"):
            return True
        return bool(
            re.search(
                r"(?is)(?:=|<>|!=|<=|>=|<|>|\blike|\bregexp|\bbetween|\bthen|\belse|,|\()\s*$",
                before[-120:],
            )
        )

    def _remove_lists(
        self,
        candidates: list[SqlPreprocessCandidate],
        rule: str,
    ) -> tuple[list[SqlPreprocessCandidate], list[SqlPreprocessDiagnostic]]:
        output: list[SqlPreprocessCandidate] = []
        diagnostics: list[SqlPreprocessDiagnostic] = []
        for candidate in candidates:
            sql, count = self._LIST_RE.subn(" ", candidate.sql)
            if count:
                output.append(self._derived(candidate, sql, rule))
                diagnostics.append(
                    SqlPreprocessDiagnostic(
                        code="template_loop_ignored",
                        message="循环模板依赖运行时集合，已忽略循环块且未从块内建立关系",
                    )
                )
            else:
                output.append(candidate)
        return output, diagnostics

    def _angle_conditionals(
        self,
        candidates: list[SqlPreprocessCandidate],
        rule: str,
        *,
        mode: str,
    ) -> list[SqlPreprocessCandidate]:
        if mode not in {"exclude", "include"}:
            return []
        output: list[SqlPreprocessCandidate] = []
        for candidate in candidates:
            replacement = r" \g<body> " if mode == "include" else " "
            sql, count = self._ANGLE_RE.subn(replacement, candidate.sql)
            output.append(self._derived(candidate, sql, rule) if count else candidate)
        return output

    def _replace_order_directions(
        self,
        candidates: list[SqlPreprocessCandidate],
        rule: str,
        names: tuple[str, ...],
    ) -> list[SqlPreprocessCandidate]:
        safe_names = tuple(name for name in names if re.fullmatch(r"[A-Za-z_]\w*", name))
        if not safe_names:
            return candidates
        name_pattern = "|".join(re.escape(name) for name in safe_names)
        pattern = re.compile(
            rf"(?is)(\border\s+by\s+(?:[A-Za-z_`]\w*`?\.)?[A-Za-z_`]\w*`?\s+):(?:{name_pattern})(?=\s*(?:,|limit\b|$))"
        )
        output: list[SqlPreprocessCandidate] = []
        for candidate in candidates:
            sql, count = pattern.subn(r"\1ASC", candidate.sql)
            output.append(self._derived(candidate, sql, rule) if count else candidate)
        return output

    def _unwrap_known(
        self,
        candidates: list[SqlPreprocessCandidate],
        rule: str,
        wrappers: tuple[str, ...],
    ) -> list[SqlPreprocessCandidate]:
        output: list[SqlPreprocessCandidate] = []
        for candidate in candidates:
            sql = candidate.sql
            changed = False
            for wrapper in wrappers:
                escaped = re.escape(wrapper)
                match = re.search(rf"(?is){escaped}\s*\([^)]*\)\s*\{{", sql)
                if match is None:
                    continue
                closing_match = re.search(r"@?}\s*(?![\s\S]*@?})", sql)
                if closing_match is None or closing_match.start() <= match.end():
                    continue
                sql = (
                    sql[: match.start()]
                    + sql[match.end() : closing_match.start()]
                    + sql[closing_match.end() :]
                )
                changed = True
            output.append(self._derived(candidate, sql, rule) if changed else candidate)
        return output

    def _guard_dynamic_identifiers(
        self,
        candidates: list[SqlPreprocessCandidate],
    ) -> tuple[list[SqlPreprocessCandidate], list[SqlPreprocessDiagnostic]]:
        output: list[SqlPreprocessCandidate] = []
        diagnostics: list[SqlPreprocessDiagnostic] = []
        for candidate in candidates:
            match = self._DYNAMIC_IDENTIFIER_RE.search(candidate.sql)
            if match is None:
                output.append(candidate)
                continue
            diagnostics.append(
                SqlPreprocessDiagnostic(
                    code="dynamic_identifier_unsupported",
                    message="SQL 包含动态表名或字段名，无法安全确认真实数据库对象",
                    expression=match.group(0)[:1000],
                )
            )
        return output, diagnostics

    def _expand_conditions(
        self,
        candidates: list[SqlPreprocessCandidate],
        rule: str,
        max_candidates: int,
        *,
        strategy: str,
        relation_only: bool,
    ) -> tuple[list[SqlPreprocessCandidate], list[SqlPreprocessDiagnostic]]:
        output: list[SqlPreprocessCandidate] = []
        diagnostics: list[SqlPreprocessDiagnostic] = []
        for candidate in candidates:
            if strategy == "baseline_and_single":
                expanded, error = self._expand_baseline_and_single(
                    candidate.sql,
                    max_candidates,
                    relation_only=relation_only,
                )
            else:
                expanded, error = self._expand_first_if(candidate.sql, max_candidates)
            if error:
                diagnostics.append(
                    SqlPreprocessDiagnostic(
                        code="template_block_unclosed",
                        message="FreeMarker 条件块未闭合或分支结构不合法",
                    )
                )
                continue
            if len(expanded) == 1 and expanded[0] == candidate.sql:
                output.append(candidate)
                continue
            output.extend(self._derived(candidate, sql, rule) for sql in expanded)
        return output[:max_candidates], diagnostics

    def _expand_baseline_and_single(
        self,
        sql: str,
        limit: int,
        *,
        relation_only: bool,
    ) -> tuple[list[str], bool]:
        baseline, error = self._collapse_conditions(sql, prefer_then=False)
        if error:
            return [], True
        activations, error = self._single_activations(
            sql,
            relation_only=relation_only,
        )
        if error:
            return [], True
        output: list[str] = []
        seen: set[str] = set()
        for candidate in (baseline, *activations):
            normalized = " ".join(candidate.split())
            if normalized in seen:
                continue
            seen.add(normalized)
            output.append(candidate)
            if len(output) >= limit:
                break
        return output, False

    def _collapse_conditions(
        self,
        sql: str,
        *,
        prefer_then: bool,
    ) -> tuple[str, bool]:
        split, error = self._split_first_if(sql)
        if error:
            return "", True
        if split is None:
            return sql, bool(re.search(r"<#elseif\b|<#else\s*>|</#if\s*>", sql, re.I))
        before, branches, after = split
        selected = branches[0] if prefer_then else branches[-1]
        selected_sql, selected_error = self._collapse_conditions(
            selected,
            prefer_then=prefer_then,
        )
        after_sql, after_error = self._collapse_conditions(after, prefer_then=prefer_then)
        return before + selected_sql + after_sql, selected_error or after_error

    def _single_activations(
        self,
        sql: str,
        *,
        relation_only: bool,
    ) -> tuple[list[str], bool]:
        split, error = self._split_first_if(sql)
        if error:
            return [], True
        if split is None:
            return [], bool(re.search(r"<#elseif\b|<#else\s*>|</#if\s*>", sql, re.I))
        before, branches, after = split
        baseline_branch, branch_error = self._collapse_conditions(
            branches[-1],
            prefer_then=False,
        )
        baseline_after, after_error = self._collapse_conditions(after, prefer_then=False)
        if branch_error or after_error:
            return [], True
        output: list[str] = []
        for branch in branches:
            if not branch:
                continue
            branch_sql, branch_error = self._collapse_conditions(branch, prefer_then=True)
            if branch_error:
                return [], True
            if not relation_only or self._contains_relation_structure(branch_sql):
                output.append(before + branch_sql + baseline_after)
            nested, nested_error = self._single_activations(
                branch,
                relation_only=relation_only,
            )
            if nested_error:
                return [], True
            output.extend(before + candidate + baseline_after for candidate in nested)
        tail, tail_error = self._single_activations(
            after,
            relation_only=relation_only,
        )
        if tail_error:
            return [], True
        output.extend(before + baseline_branch + candidate for candidate in tail)
        return output, False

    @staticmethod
    def _contains_relation_structure(sql: str) -> bool:
        return bool(re.search(r"(?is)\b(?:from|join|update|into|delete)\b", sql))

    def _split_first_if(
        self,
        sql: str,
    ) -> tuple[tuple[str, tuple[str, ...], str] | None, bool]:
        opening = self._IF_OPEN_RE.search(sql)
        if opening is None:
            return None, False
        depth = 0
        branch_tokens: list[tuple[str, re.Match[str]]] = []
        closing: re.Match[str] | None = None
        saw_else = False
        for token in self._IF_TOKEN_RE.finditer(sql, opening.start()):
            value = token.group(0).casefold()
            if value.startswith("<#if"):
                depth += 1
            elif value.startswith("</#if"):
                depth -= 1
                if depth == 0:
                    closing = token
                    break
            elif depth == 1 and value.startswith("<#elseif"):
                if saw_else:
                    return None, True
                branch_tokens.append(("elseif", token))
            elif depth == 1 and value.startswith("<#else"):
                if saw_else:
                    return None, True
                saw_else = True
                branch_tokens.append(("else", token))
        if closing is None:
            return None, True
        branches: list[str] = []
        body_start = opening.end()
        for _, token in branch_tokens:
            branches.append(sql[body_start : token.start()])
            body_start = token.end()
        branches.append(sql[body_start : closing.start()])
        if not saw_else:
            branches.append("")
        return (
            sql[: opening.start()],
            tuple(branches),
            sql[closing.end() :],
        ), False

    def _expand_first_if(self, sql: str, limit: int) -> tuple[list[str], bool]:
        split, error = self._split_first_if(sql)
        if error:
            return [], True
        if split is None:
            return [sql], bool(re.search(r"<#elseif\b|<#else\s*>|</#if\s*>", sql, re.I))
        before, branches_to_expand, after = split
        branches: list[str] = []
        for branch in branches_to_expand:
            branch_expanded, branch_error = self._expand_first_if(branch, limit)
            if branch_error:
                return [], True
            for branch_sql in branch_expanded:
                tail_expanded, tail_error = self._expand_first_if(after, limit)
                if tail_error:
                    return [], True
                for tail_sql in tail_expanded:
                    branches.append(before + branch_sql + tail_sql)
                    if len(branches) >= limit:
                        return branches, False
        return branches, False

    def _map_text(
        self,
        candidates: list[SqlPreprocessCandidate],
        rule: str,
        transform: object,
    ) -> list[SqlPreprocessCandidate]:
        output: list[SqlPreprocessCandidate] = []
        for candidate in candidates:
            sql, changed = transform(candidate.sql)  # type: ignore[operator]
            output.append(self._derived(candidate, sql, rule) if changed else candidate)
        return output

    @staticmethod
    def _derived(
        candidate: SqlPreprocessCandidate,
        sql: str,
        rule: str,
    ) -> SqlPreprocessCandidate:
        rules = (*candidate.applied_rules, rule)
        digest = hashlib.sha256(("\n".join(rules) + "\n" + sql).encode("utf-8")).hexdigest()[:16]
        return SqlPreprocessCandidate(
            candidate_id=digest,
            sql=sql,
            applied_rules=rules,
            template_derived=True,
        )

    @staticmethod
    def _deduplicate(candidates: list[SqlPreprocessCandidate]) -> list[SqlPreprocessCandidate]:
        seen: set[str] = set()
        output: list[SqlPreprocessCandidate] = []
        for candidate in candidates:
            normalized = " ".join(candidate.sql.split())
            if normalized in seen:
                continue
            seen.add(normalized)
            output.append(candidate)
        return output
