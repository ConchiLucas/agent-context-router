from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from context_router.repositories.managed_rule_repository import (
    ManagedRuleRecord,
    ManagedRuleRepositoryError,
    ManagedRuleStore,
    new_managed_rule_id,
    touch_rule,
)
from context_router.schemas.context import WorkspaceRule
from context_router.schemas.managed_rules import ManagedRule, ManagedRuleList, ManagedRuleWrite


class ManagedRulesError(ValueError):
    def __init__(self, message: str, *, not_found: bool = False) -> None:
        super().__init__(message)
        self.not_found = not_found


@dataclass(frozen=True, slots=True)
class SeedSpec:
    slug: str
    title: str
    body: str
    sort_order: int


SEED_RULES: tuple[SeedSpec, ...] = (
    SeedSpec(
        slug="workspace-rules",
        title="工作空间规则",
        body=(
            "## 受管目录只经控制面更新\n\n"
            "`docs/`、`script/` 和 `deploy/` 是 Context Router 控制面同步下来的受管目录。\n\n"
            "- 不要在业务工作空间里直接改这些目录来充当正式更新\n"
            "- 需要改时走配置管理或对应同步脚本，由数据库当前版本单向写到磁盘\n\n"
            "## AGENTS.md 只作规则指针\n\n"
            "各项目 `AGENTS.md` 不要复制完整控制面规则正文。\n\n"
            "- 只写一句：遵守本次 `prepare_task_context` 返回的 `workspace_rules`\n"
            "- 规则以控制面当前版本为准\n\n"
            "## 完成功能后保持精简\n\n"
            "在完成功能前提下，以精简并删除冗余代码为荣，以堆砌重复实现为耻。"
        ),
        sort_order=10,
    ),
)


class ManagedRulesService:
    def __init__(self, repository: ManagedRuleStore) -> None:
        self._repository = repository

    def list_rules(self) -> ManagedRuleList:
        return ManagedRuleList(rules=[self._schema(item) for item in self._records()])

    def list_prepare_rules(self) -> list[WorkspaceRule]:
        return [
            WorkspaceRule(id=item.id, title=item.title, body=item.body) for item in self._records()
        ]

    def create_rule(self, payload: ManagedRuleWrite) -> ManagedRule:
        title, body = self._normalize(payload)
        now = datetime.now(UTC)
        next_order = max((item.sort_order for item in self._records()), default=90) + 10
        record = self._repository.insert(
            ManagedRuleRecord(
                id=new_managed_rule_id(),
                slug=f"user-{new_managed_rule_id()[:16]}",
                title=title,
                body=body,
                sort_order=next_order,
                created_at=now,
                updated_at=now,
            )
        )
        return self._schema(record)

    def update_rule(self, rule_id: str, payload: ManagedRuleWrite) -> ManagedRule:
        title, body = self._normalize(payload)
        current = self._require(rule_id)
        return self._schema(self._repository.update(touch_rule(current, title=title, body=body)))

    def delete_rule(self, rule_id: str) -> None:
        self._require(rule_id)
        self._repository.delete(rule_id)

    def _records(self) -> list[ManagedRuleRecord]:
        records = self._repository.list_all()
        if records:
            return records
        now = datetime.now(UTC)
        seeded: list[ManagedRuleRecord] = []
        for spec in SEED_RULES:
            seeded.append(
                self._repository.insert(
                    ManagedRuleRecord(
                        id=new_managed_rule_id(),
                        slug=spec.slug,
                        title=spec.title,
                        body=spec.body,
                        sort_order=spec.sort_order,
                        created_at=now,
                        updated_at=now,
                    )
                )
            )
        return seeded

    def _require(self, rule_id: str) -> ManagedRuleRecord:
        record = self._repository.get(rule_id)
        if record is None:
            raise ManagedRulesError("找不到规则", not_found=True)
        return record

    @staticmethod
    def _normalize(payload: ManagedRuleWrite) -> tuple[str, str]:
        title = payload.title.strip()
        body = payload.body.strip()
        if not title or not body:
            raise ManagedRulesError("标题和正文不能为空")
        return title, body

    @staticmethod
    def _schema(record: ManagedRuleRecord) -> ManagedRule:
        return ManagedRule(
            id=record.id,
            slug=record.slug,
            title=record.title,
            body=record.body,
            sort_order=record.sort_order,
        )


def http_status_for_rules_error(exc: ManagedRulesError | ManagedRuleRepositoryError) -> int:
    if isinstance(exc, ManagedRulesError) and exc.not_found:
        return 404
    if isinstance(exc, ManagedRuleRepositoryError) and str(exc) == "找不到规则":
        return 404
    return 400
