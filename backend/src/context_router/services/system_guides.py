from __future__ import annotations

import re
from typing import Any

from context_router.repositories.system_guide_repository import (
    SystemGuideRecord,
    SystemGuideRepositoryError,
    SystemGuideStore,
)
from context_router.schemas.system_guides import (
    SystemGuideContentWrite,
    SystemGuideDetail,
    SystemGuideWrite,
)

GUIDE_DOCUMENT_PREFIX = "system-guide:"
_KEY_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_MAX_DOCUMENT_BYTES = 64 * 1024


class SystemGuideError(ValueError):
    pass


class SystemGuideService:
    def __init__(self, repository: SystemGuideStore) -> None:
        self._repository = repository

    def list_guides(self) -> list[SystemGuideDetail]:
        try:
            return [self._detail(item) for item in self._repository.list_guides()]
        except SystemGuideRepositoryError as exc:
            raise SystemGuideError(str(exc)) from exc

    def get_guide(self, guide_id: str) -> SystemGuideDetail:
        try:
            return self._detail(self._repository.get_guide(guide_id))
        except SystemGuideRepositoryError as exc:
            raise SystemGuideError(str(exc)) from exc

    def get_by_document_id(self, document_id: str) -> SystemGuideDetail:
        if not document_id.startswith(GUIDE_DOCUMENT_PREFIX):
            raise SystemGuideError("系统文档 ID 不正确")
        try:
            return self._detail(
                self._repository.get_guide_by_key(document_id[len(GUIDE_DOCUMENT_PREFIX) :])
            )
        except SystemGuideRepositoryError as exc:
            raise SystemGuideError(str(exc)) from exc

    def create_guide(self, payload: SystemGuideWrite) -> SystemGuideDetail:
        guide_key, document = self._validate(payload)
        try:
            record = self._repository.create_guide(
                guide_key=guide_key,
                document=document,
                include_in_prepare=payload.include_in_prepare,
                sort_order=payload.sort_order,
            )
        except SystemGuideRepositoryError as exc:
            raise SystemGuideError(str(exc)) from exc
        return self._detail(record)

    def update_guide(self, guide_id: str, payload: SystemGuideWrite) -> SystemGuideDetail:
        guide_key, document = self._validate(payload)
        try:
            record = self._repository.update_guide(
                guide_id,
                guide_key=guide_key,
                document=document,
                include_in_prepare=payload.include_in_prepare,
                sort_order=payload.sort_order,
            )
        except SystemGuideRepositoryError as exc:
            raise SystemGuideError(str(exc)) from exc
        return self._detail(record)

    def update_content(
        self,
        guide_id: str,
        payload: SystemGuideContentWrite,
    ) -> SystemGuideDetail:
        current = self.get_guide(guide_id)
        write = SystemGuideWrite(
            guide_key=current.guide_key,
            document=payload.document,
            include_in_prepare=current.include_in_prepare,
            sort_order=current.sort_order,
        )
        return self.update_guide(guide_id, write)

    def delete_guide(self, guide_id: str) -> None:
        try:
            self._repository.delete_guide(guide_id)
        except SystemGuideRepositoryError as exc:
            raise SystemGuideError(str(exc)) from exc

    @staticmethod
    def _validate(payload: SystemGuideWrite) -> tuple[str, dict[str, Any]]:
        guide_key = payload.guide_key.strip()
        if not _KEY_PATTERN.fullmatch(guide_key):
            raise SystemGuideError("guide_key 只能使用小写字母、数字和单个连字符")
        document = payload.document
        if document.get("schema_version") != 1:
            raise SystemGuideError("JSON 的 schema_version 必须为 1")
        if document.get("key") != guide_key:
            raise SystemGuideError("JSON 的 key 必须与 guide_key 一致")
        title = document.get("title")
        summary = document.get("summary")
        sections = document.get("sections")
        if not isinstance(title, str) or not title.strip() or len(title.strip()) > 120:
            raise SystemGuideError("JSON 的 title 必须是 1 到 120 个字符")
        if not isinstance(summary, str) or not summary.strip() or len(summary.strip()) > 500:
            raise SystemGuideError("JSON 的 summary 必须是 1 到 500 个字符")
        if not isinstance(sections, list):
            raise SystemGuideError("JSON 的 sections 必须是数组")
        import json

        if len(json.dumps(document, ensure_ascii=False).encode("utf-8")) > _MAX_DOCUMENT_BYTES:
            raise SystemGuideError("单篇系统文档不能超过 64 KiB")
        return guide_key, document

    @staticmethod
    def _detail(record: SystemGuideRecord) -> SystemGuideDetail:
        return SystemGuideDetail(
            id=record.id,
            document_id=f"{GUIDE_DOCUMENT_PREFIX}{record.guide_key}",
            guide_key=record.guide_key,
            title=str(record.document["title"]),
            summary=str(record.document["summary"]),
            document=record.document,
            include_in_prepare=record.include_in_prepare,
            sort_order=record.sort_order,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )
