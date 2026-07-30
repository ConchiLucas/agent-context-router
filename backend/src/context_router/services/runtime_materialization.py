from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path, PurePosixPath
from uuid import uuid4

from context_router.repositories.runtime_config_repository import RuntimeConfigFileRecord

MAX_MATERIALIZED_BYTES = 20_000_000
MANIFEST_FILE_NAME = ".runtime-manifest.json"


class RuntimeMaterializationError(RuntimeError):
    """Raised when a runtime configuration cannot be materialized safely."""


@dataclass(frozen=True)
class MaterializedRuntimeConfig:
    snapshot_id: str
    project_id: str
    mode: str
    materialized_path: str
    file_count: int
    total_bytes: int
    manifest_sha256: str
    created_at: datetime


class RuntimeMaterializationService:
    def __init__(self, runtime_root: Path) -> None:
        self._runtime_root = runtime_root.resolve()

    def materialize(
        self,
        project_id: str,
        mode: str,
        files: list[RuntimeConfigFileRecord],
    ) -> MaterializedRuntimeConfig:
        if mode not in {"fast", "full"}:
            raise RuntimeMaterializationError("不支持的更新模式")
        if not project_id.isalnum():
            raise RuntimeMaterializationError("项目 ID 不合法")
        if not files:
            raise RuntimeMaterializationError("当前更新模式还没有部署文件")

        total_bytes = sum(len(item.content.encode("utf-8")) for item in files)
        if total_bytes > MAX_MATERIALIZED_BYTES:
            raise RuntimeMaterializationError("部署文件总大小不能超过 20 MB")

        created_at = datetime.now(timezone.utc)
        snapshot_id = (
            created_at.strftime("%Y%m%dT%H%M%S%fZ") + "-" + uuid4().hex[:8]
        )
        mode_root = self._runtime_root / "projects" / project_id / mode
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
                "project_id": project_id,
                "mode": mode,
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
            project_id=project_id,
            mode=mode,
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
