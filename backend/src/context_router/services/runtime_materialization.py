from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path, PurePosixPath
from uuid import uuid4

from context_router.repositories.runtime_config_repository import RuntimeConfigFileRecord
from context_router.repositories.workspace_runtime_repository import WorkspaceRuntimeFileRecord

MAX_MATERIALIZED_BYTES = 20_000_000
MANIFEST_FILE_NAME = ".runtime-manifest.json"


class RuntimeMaterializationError(RuntimeError):
    """Raised when a runtime configuration cannot be materialized safely."""


@dataclass(frozen=True)
class MaterializedRuntimeConfig:
    snapshot_id: str
    owner_type: str
    owner_id: str
    profile: str
    snapshot_relative_path: str
    materialized_path: str
    file_count: int
    total_bytes: int
    manifest_sha256: str
    created_at: datetime

    @property
    def project_id(self) -> str:
        return self.owner_id

    @property
    def mode(self) -> str:
        return self.profile


class RuntimeMaterializationService:
    def __init__(self, runtime_root: Path) -> None:
        self._runtime_root = runtime_root.resolve()

    @property
    def runtime_root(self) -> Path:
        return self._runtime_root

    def materialize(
        self,
        project_id: str,
        mode: str,
        files: list[RuntimeConfigFileRecord],
    ) -> MaterializedRuntimeConfig:
        return self.materialize_owner(
            owner_type="project",
            owner_id=project_id,
            profile=mode,
            files=files,
        )

    def materialize_workspace(
        self,
        workspace_id: str,
        files: list[WorkspaceRuntimeFileRecord],
    ) -> MaterializedRuntimeConfig:
        return self.materialize_owner(
            owner_type="workspace",
            owner_id=workspace_id,
            profile="start",
            files=files,
        )

    def materialize_owner(
        self,
        *,
        owner_type: str,
        owner_id: str,
        profile: str,
        files: list[RuntimeConfigFileRecord] | list[WorkspaceRuntimeFileRecord],
    ) -> MaterializedRuntimeConfig:
        allowed_profiles = {"project": {"fast", "full"}, "workspace": {"start"}}
        if owner_type not in allowed_profiles or profile not in allowed_profiles[owner_type]:
            raise RuntimeMaterializationError("不支持的运行配置类型")
        if not owner_id.isalnum():
            raise RuntimeMaterializationError("运行配置所有者 ID 不合法")
        if not files:
            raise RuntimeMaterializationError("当前运行配置还没有部署文件")

        total_bytes = sum(len(item.content.encode("utf-8")) for item in files)
        if total_bytes > MAX_MATERIALIZED_BYTES:
            raise RuntimeMaterializationError("部署文件总大小不能超过 20 MB")

        created_at = datetime.now(UTC)
        snapshot_id = created_at.strftime("%Y%m%dT%H%M%S%fZ") + "-" + uuid4().hex[:8]
        owner_directory = "projects" if owner_type == "project" else "workspaces"
        mode_root = self._runtime_root / owner_directory / owner_id / profile
        temporary_path = mode_root / f".{snapshot_id}.tmp"
        target_path = mode_root / snapshot_id

        try:
            mode_root.mkdir(parents=True, exist_ok=True, mode=0o750)
            temporary_path.mkdir(mode=0o750)
            manifest_files: list[dict[str, object]] = []
            for item in files:
                relative_path = self._safe_relative_path(item.relative_path)
                file_path = temporary_path.joinpath(*relative_path.parts)
                file_path.parent.mkdir(parents=True, exist_ok=True, mode=0o750)
                encoded_content = item.content.encode("utf-8")
                file_path.write_bytes(encoded_content)
                file_path.chmod(0o750 if item.executable else 0o640)
                manifest_files.append(
                    {
                        "relative_path": relative_path.as_posix(),
                        "executable": item.executable,
                        "size_bytes": len(encoded_content),
                        "sha256": sha256(encoded_content).hexdigest(),
                    }
                )

            manifest = {
                "schema_version": 1,
                "snapshot_id": snapshot_id,
                "owner_type": owner_type,
                "owner_id": owner_id,
                "profile": profile,
                "created_at": created_at.isoformat(),
                "file_count": len(files),
                "total_bytes": total_bytes,
                "files": manifest_files,
            }
            canonical_manifest = json.dumps(
                manifest,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            manifest_digest = sha256(canonical_manifest).hexdigest()
            manifest["manifest_sha256"] = manifest_digest
            manifest_path = temporary_path / MANIFEST_FILE_NAME
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            manifest_path.chmod(0o640)
            temporary_path.rename(target_path)
        except OSError as exc:
            shutil.rmtree(temporary_path, ignore_errors=True)
            raise RuntimeMaterializationError("运行配置写入磁盘失败") from exc

        return MaterializedRuntimeConfig(
            snapshot_id=snapshot_id,
            owner_type=owner_type,
            owner_id=owner_id,
            profile=profile,
            snapshot_relative_path=target_path.relative_to(self._runtime_root).as_posix(),
            materialized_path=str(target_path),
            file_count=len(files),
            total_bytes=total_bytes,
            manifest_sha256=manifest_digest,
            created_at=created_at,
        )

    @staticmethod
    def _safe_relative_path(value: str) -> PurePosixPath:
        relative_path = PurePosixPath(value)
        if (
            relative_path.is_absolute()
            or any(part in {"", ".", ".."} for part in relative_path.parts)
            or relative_path.as_posix() == MANIFEST_FILE_NAME
        ):
            raise RuntimeMaterializationError("部署文件包含不安全的相对路径")
        return relative_path
