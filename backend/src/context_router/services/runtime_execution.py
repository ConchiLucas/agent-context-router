from __future__ import annotations

import os
import signal
import subprocess
from pathlib import Path, PurePosixPath
from threading import RLock, Thread

from context_router.config import Settings
from context_router.repositories.runtime_config_repository import (
    RuntimeConfigRepositoryError,
    RuntimeConfigStore,
)
from context_router.repositories.runtime_run_repository import (
    RuntimeRunRecord,
    RuntimeRunRepositoryError,
    RuntimeRunStore,
)
from context_router.services.project_registry import ProjectRegistry, ProjectRegistryError
from context_router.services.runtime_materialization import (
    RuntimeMaterializationError,
    RuntimeMaterializationService,
)

RUNTIME_ENTRY_FILE = "deploy.sh"
FULL_BUILD_FILE_NAMES = {
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
    "settings.gradle",
    "settings.gradle.kts",
    "go.mod",
    "go.sum",
    "pyproject.toml",
    "uv.lock",
    "poetry.lock",
    "package.json",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "bun.lock",
    "bun.lockb",
    "requirements.txt",
    "docker-compose.yml",
    "docker-compose.yaml",
    "compose.yml",
    "compose.yaml",
}


class RuntimeExecutionError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class RuntimeExecutionService:
    def __init__(
        self,
        *,
        settings: Settings,
        registry: ProjectRegistry,
        config_repository: RuntimeConfigStore,
        run_repository: RuntimeRunStore,
        materialization_service: RuntimeMaterializationService,
    ) -> None:
        self._settings = settings
        self._registry = registry
        self._config_repository = config_repository
        self._run_repository = run_repository
        self._materialization_service = materialization_service
        self._active_projects: set[str] = set()
        self._active_lock = RLock()

    def select_mode(self, changed_files: list[str]) -> tuple[str, str]:
        for raw_path in changed_files:
            normalized = raw_path.strip().replace("\\", "/")
            path = PurePosixPath(normalized)
            lower_name = path.name.lower()
            if (
                lower_name in FULL_BUILD_FILE_NAMES
                or lower_name.startswith("dockerfile")
                or normalized.startswith(".mvn/")
                or normalized.startswith("gradle/")
            ):
                return "full", f"依赖或构建文件发生变化：{normalized}"
        return "fast", "仅业务代码或资源文件发生变化"

    def start(
        self,
        *,
        project_id: str,
        mode: str,
        trigger: str,
        changed_files: list[str] | None = None,
        decision_reason: str,
    ) -> RuntimeRunRecord:
        if not self._settings.runtime_execution_enabled:
            raise RuntimeExecutionError("runtime_execution_disabled", "运行执行功能尚未启用")
        if not self._settings.runtime_docker_socket.exists():
            raise RuntimeExecutionError(
                "docker_socket_unavailable",
                "Docker Socket 当前不可用",
            )
        if mode not in {"fast", "full"}:
            raise RuntimeExecutionError("invalid_runtime_mode", "不支持的更新模式")
        if trigger not in {"ui", "mcp"}:
            raise RuntimeExecutionError("invalid_runtime_trigger", "不支持的触发来源")
        with self._active_lock:
            if project_id in self._active_projects:
                raise RuntimeExecutionError(
                    "project_run_in_progress",
                    "这个项目已有运行中的更新任务",
                )

        try:
            project = self._registry.get_project_summary(project_id)
            files = self._config_repository.list_files(project_id, mode)
        except ProjectRegistryError as exc:
            raise RuntimeExecutionError("project_not_found", "项目不存在") from exc
        except RuntimeConfigRepositoryError as exc:
            raise RuntimeExecutionError("runtime_config_unavailable", str(exc)) from exc

        if not any(item.relative_path == RUNTIME_ENTRY_FILE for item in files):
            raise RuntimeExecutionError(
                "runtime_entry_missing",
                f"当前模式缺少固定执行入口 {RUNTIME_ENTRY_FILE}",
            )

        try:
            snapshot = self._materialization_service.materialize(project_id, mode, files)
        except RuntimeMaterializationError as exc:
            raise RuntimeExecutionError("materialization_failed", str(exc)) from exc

        (
            project_root,
            project_host_root,
            workspace_root,
            workspace_host_root,
        ) = self._resolve_project_paths(project)
        log_directory = self._settings.runtime_root / "runs" / snapshot.snapshot_id
        log_directory.mkdir(parents=True, exist_ok=True, mode=0o750)
        log_path = log_directory / "execution.log"
        normalized_changed_files = [
            item.strip().replace("\\", "/")[:1000] for item in (changed_files or []) if item.strip()
        ][:500]
        try:
            run = self._run_repository.create_run(
                project_id=project_id,
                mode=mode,
                trigger=trigger,
                snapshot_id=snapshot.snapshot_id,
                materialized_path=snapshot.materialized_path,
                project_root=str(project_root),
                entry_file=RUNTIME_ENTRY_FILE,
                log_path=str(log_path),
                changed_files=normalized_changed_files,
                decision_reason=decision_reason,
            )
        except RuntimeRunRepositoryError as exc:
            raise RuntimeExecutionError("runtime_run_unavailable", str(exc)) from exc

        with self._active_lock:
            self._active_projects.add(project_id)
        Thread(
            target=self._execute,
            kwargs={
                "run": run,
                "project_root": project_root,
                "project_host_root": project_host_root,
                "workspace_root": workspace_root,
                "workspace_host_root": workspace_host_root,
            },
            name=f"runtime-run-{run.id[:8]}",
            daemon=True,
        ).start()
        return run

    def get_run(self, run_id: str) -> RuntimeRunRecord:
        try:
            run = self._run_repository.get_run(run_id)
        except RuntimeRunRepositoryError as exc:
            raise RuntimeExecutionError("runtime_run_unavailable", str(exc)) from exc
        if run is None:
            raise RuntimeExecutionError("runtime_run_not_found", "运行任务不存在")
        return run

    def list_runs(self, project_id: str, limit: int = 20) -> list[RuntimeRunRecord]:
        try:
            return self._run_repository.list_runs(project_id, limit)
        except RuntimeRunRepositoryError as exc:
            raise RuntimeExecutionError("runtime_run_unavailable", str(exc)) from exc

    def read_log(self, run_id: str, max_characters: int = 50_000) -> tuple[str, bool]:
        run = self.get_run(run_id)
        log_path = Path(run.log_path)
        if not log_path.exists():
            return "", False
        max_bytes = min(max(max_characters, 1), 200_000) * 4
        try:
            with log_path.open("rb") as stream:
                stream.seek(0, os.SEEK_END)
                size = stream.tell()
                truncated = size > max_bytes
                stream.seek(
                    -max_bytes if truncated else 0,
                    os.SEEK_END if truncated else os.SEEK_SET,
                )
                content = stream.read().decode("utf-8", errors="replace")
        except OSError as exc:
            raise RuntimeExecutionError("runtime_log_unavailable", "运行日志读取失败") from exc
        return content[-max_characters:], truncated

    def reconcile_interrupted(self) -> int:
        try:
            return self._run_repository.reconcile_interrupted()
        except RuntimeRunRepositoryError:
            return 0

    def _execute(
        self,
        *,
        run: RuntimeRunRecord,
        project_root: Path,
        project_host_root: str,
        workspace_root: Path,
        workspace_host_root: str,
    ) -> None:
        process: subprocess.Popen[bytes] | None = None
        try:
            self._run_repository.mark_running(run.id)
            snapshot_path = Path(run.materialized_path)
            entry_path = snapshot_path / run.entry_file
            environment = os.environ.copy()
            environment.update(
                {
                    "RUNTIME_RUN_ID": run.id,
                    "RUNTIME_PROJECT_ID": run.project_id,
                    "RUNTIME_DEPLOY_MODE": run.mode,
                    "RUNTIME_SNAPSHOT_DIR": str(snapshot_path),
                    "PROJECT_ROOT": str(project_root),
                    "PROJECT_HOST_ROOT": project_host_root,
                    "WORKSPACE_ROOT": str(workspace_root),
                    "WORKSPACE_HOST_ROOT": workspace_host_root,
                    "DOCKER_HOST": f"unix://{self._settings.runtime_docker_socket}",
                }
            )
            Path(run.log_path).parent.mkdir(parents=True, exist_ok=True, mode=0o750)
            with Path(run.log_path).open("wb") as log_stream:
                header = (
                    f"[runtime] run={run.id} mode={run.mode} project={run.project_id}\n"
                    f"[runtime] source={project_root}\n"
                    f"[runtime] snapshot={snapshot_path}\n"
                    f"[runtime] entry={run.entry_file}\n"
                )
                log_stream.write(header.encode("utf-8"))
                log_stream.flush()
                process = subprocess.Popen(
                    ["/bin/sh", str(entry_path)],
                    cwd=str(snapshot_path),
                    env=environment,
                    stdout=log_stream,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
                try:
                    exit_code = process.wait(
                        timeout=self._settings.runtime_execution_timeout_seconds
                    )
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait()
                    self._run_repository.finish_run(
                        run.id,
                        status="failed",
                        exit_code=124,
                        error_message="运行任务执行超时",
                    )
                    return
            self._run_repository.finish_run(
                run.id,
                status="succeeded" if exit_code == 0 else "failed",
                exit_code=exit_code,
                error_message=None if exit_code == 0 else f"deploy.sh 退出码为 {exit_code}",
            )
        except (OSError, RuntimeRunRepositoryError) as exc:
            if process is not None and process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
            try:
                self._run_repository.finish_run(
                    run.id,
                    status="failed",
                    exit_code=None,
                    error_message="Runtime Runner 执行失败",
                )
            except RuntimeRunRepositoryError:
                pass
            try:
                with Path(run.log_path).open("ab") as log_stream:
                    log_stream.write(f"\n[runtime] error={type(exc).__name__}\n".encode())
            except OSError:
                pass
        finally:
            with self._active_lock:
                self._active_projects.discard(run.project_id)

    def _resolve_project_paths(self, project: object) -> tuple[Path, str, Path, str]:
        agents_path = PurePosixPath(str(project.agents_path))
        document_path = PurePosixPath(str(project.document_relative_path))
        workspace_host_path = agents_path
        for _ in document_path.parts:
            workspace_host_path = workspace_host_path.parent
        project_host_path = workspace_host_path.joinpath(PurePosixPath(str(project.relative_path)))
        mounted_host_root = PurePosixPath(self._settings.workspace_host_root.as_posix())
        try:
            workspace_relative = workspace_host_path.relative_to(mounted_host_root)
            project_relative = project_host_path.relative_to(mounted_host_root)
        except ValueError as exc:
            raise RuntimeExecutionError(
                "project_path_unavailable",
                "项目源码不在 Runtime Runner 的工作区挂载范围内",
            ) from exc
        workspace_root = self._settings.workspace_container_root.joinpath(*workspace_relative.parts)
        project_root = self._settings.workspace_container_root.joinpath(*project_relative.parts)
        if not project_root.is_dir():
            raise RuntimeExecutionError(
                "project_path_unavailable",
                "项目源码目录在 Runtime Runner 容器中不可访问",
            )
        return (
            project_root,
            project_host_path.as_posix(),
            workspace_root,
            workspace_host_path.as_posix(),
        )
