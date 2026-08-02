#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import hmac
import http.client
import json
import os
import platform
import signal
import socket
import stat
import subprocess
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path, PurePosixPath
from typing import Protocol

RUNNER_VERSION = "1"
MANIFEST_FILE = ".runtime-manifest.json"
ENTRY_FILE = "deploy.sh"
EXIT_VALIDATION_FAILED = 126
EXIT_TIMEOUT = 124


class RunnerError(RuntimeError):
    pass


class RunnerSecurityError(RunnerError):
    pass


class RunnerApi(Protocol):
    def started_operation(self, operation_id: str, lease_token: str) -> None: ...
    def heartbeat_operation(self, operation_id: str, lease_token: str) -> None: ...
    def complete_step(
        self,
        operation_id: str,
        step_id: str,
        lease_token: str,
        exit_code: int,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None: ...


class RunnerApiClient:
    def __init__(self, base_url: str, token: str) -> None:
        parsed = urllib.parse.urlparse(base_url.rstrip("/"))
        if parsed.scheme not in {"http", "https"} or parsed.hostname not in {
            "127.0.0.1",
            "localhost",
            "::1",
        }:
            raise RunnerSecurityError("Runner 控制面地址必须使用本机回环 HTTP(S)")
        self._base_url = base_url.rstrip("/")
        self._token = token

    def register(self, runner_id: str) -> dict[str, object]:
        return self._post(
            "/api/runtime-runner/register",
            {
                "runner_id": runner_id,
                "hostname": socket.gethostname(),
                "platform": platform.system().lower(),
                "version": RUNNER_VERSION,
                "capabilities": ["docker", "posix-shell"],
            },
        )

    def heartbeat_runner(self, runner_id: str) -> dict[str, object]:
        return self._post("/api/runtime-runner/heartbeat", {"runner_id": runner_id})

    def lease(self, runner_id: str) -> dict[str, object]:
        return self._post("/api/runtime-runner/lease", {"runner_id": runner_id})

    def started_operation(self, operation_id: str, lease_token: str) -> None:
        self._post(
            f"/api/runtime-runner/operations/{operation_id}/started",
            {"lease_token": lease_token},
        )

    def heartbeat_operation(self, operation_id: str, lease_token: str) -> None:
        self._post(
            f"/api/runtime-runner/operations/{operation_id}/heartbeat",
            {"lease_token": lease_token},
        )

    def complete_step(
        self,
        operation_id: str,
        step_id: str,
        lease_token: str,
        exit_code: int,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None:
        self._post(
            f"/api/runtime-runner/operations/{operation_id}/steps/{step_id}/complete",
            {
                "lease_token": lease_token,
                "exit_code": exit_code,
                "error_code": error_code,
                "error_message": error_message,
            },
        )

    def _post(self, path: str, payload: dict[str, object]) -> dict[str, object]:
        request = urllib.request.Request(
            self._base_url + path,
            data=json.dumps(payload, separators=(",", ":")).encode(),
            headers={
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
                "User-Agent": f"context-router-host-runner/{RUNNER_VERSION}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                body = response.read()
        except (urllib.error.URLError, http.client.HTTPException, TimeoutError) as exc:
            raise RunnerError(f"控制面请求失败：{path}") from exc
        try:
            value = json.loads(body)
        except json.JSONDecodeError as exc:
            raise RunnerError("控制面返回了无效 JSON") from exc
        if not isinstance(value, dict):
            raise RunnerError("控制面返回格式无效")
        return value


class HostRuntimeRunner:
    def __init__(
        self,
        *,
        api: RunnerApi,
        allowed_workspace_root: Path,
        runtime_root: Path,
        heartbeat_seconds: float = 10,
    ) -> None:
        self._api = api
        self._allowed_workspace_root = allowed_workspace_root.resolve()
        self._runtime_root = runtime_root.resolve()
        self._heartbeat_seconds = max(0.25, heartbeat_seconds)

    def execute_lease(self, lease: dict[str, object]) -> None:
        operation = _required_dict(lease, "operation")
        operation_id = _required_string(operation, "id")
        lease_token = _required_string(lease, "lease_token")
        steps = lease.get("steps")
        if not isinstance(steps, list) or not steps:
            raise RunnerError("租约缺少运行步骤")

        started = False
        for raw_step in steps:
            if not isinstance(raw_step, dict):
                raise RunnerError("运行步骤格式无效")
            step_id = _required_string(raw_step, "id")
            try:
                execution = self._validate_step(operation, raw_step)
            except RunnerError as exc:
                self._api.complete_step(
                    operation_id,
                    step_id,
                    lease_token,
                    EXIT_VALIDATION_FAILED,
                    "runtime_validation_failed",
                    str(exc),
                )
                return

            if not started:
                self._api.started_operation(operation_id, lease_token)
                started = True
            exit_code, error_code, error_message = self._execute_step(
                operation_id=operation_id,
                lease_token=lease_token,
                step=raw_step,
                **execution,
            )
            self._api.complete_step(
                operation_id,
                step_id,
                lease_token,
                exit_code,
                error_code,
                error_message,
            )
            if exit_code != 0:
                return

    def _validate_step(
        self,
        operation: dict[str, object],
        step: dict[str, object],
    ) -> dict[str, object]:
        workspace_root = Path(_required_string(operation, "workspace_host_root"))
        if not workspace_root.is_absolute():
            raise RunnerSecurityError("Workspace 根目录必须是绝对路径")
        resolved_workspace = workspace_root.resolve(strict=True)
        _require_within(resolved_workspace, self._allowed_workspace_root, "Workspace 越界")
        if not resolved_workspace.is_dir():
            raise RunnerSecurityError("Workspace 根目录不可用")

        snapshot_relative = _safe_relative(
            _required_string(step, "snapshot_relative_path"), "快照路径"
        )
        snapshot = self._runtime_root.joinpath(*snapshot_relative.parts)
        _reject_symlink_chain(snapshot, self._runtime_root)
        resolved_snapshot = snapshot.resolve(strict=True)
        _require_within(resolved_snapshot, self._runtime_root, "运行快照越界")
        if not resolved_snapshot.is_dir():
            raise RunnerSecurityError("运行快照不是目录")
        self._verify_manifest(resolved_snapshot, step)

        if step.get("entry_file") != ENTRY_FILE:
            raise RunnerSecurityError("运行入口必须是 deploy.sh")
        entry = resolved_snapshot / ENTRY_FILE
        if entry.is_symlink() or not entry.is_file() or not os.access(entry, os.X_OK):
            raise RunnerSecurityError("deploy.sh 必须是可执行普通文件")

        log_relative = _safe_relative(_required_string(step, "log_relative_path"), "日志路径")
        log_path = self._runtime_root.joinpath(*log_relative.parts)
        _require_within(log_path.resolve(strict=False), self._runtime_root, "日志路径越界")
        if log_path.is_symlink():
            raise RunnerSecurityError("日志文件不能是软链接")

        project_root: Path | None = None
        if step.get("owner_type") == "project":
            project_relative = _safe_relative(
                _required_string(step, "project_relative_path"), "项目路径"
            )
            project_root = resolved_workspace.joinpath(*project_relative.parts).resolve(strict=True)
            _require_within(project_root, resolved_workspace, "项目路径越出 Workspace")
            if not project_root.is_dir():
                raise RunnerSecurityError("项目目录不可用")

        timeout = operation.get("timeout_seconds")
        if not isinstance(timeout, int) or not 10 <= timeout <= 7200:
            raise RunnerSecurityError("运行超时范围无效")
        return {
            "workspace_root": resolved_workspace,
            "project_root": project_root,
            "snapshot_root": resolved_snapshot,
            "entry": entry,
            "log_path": log_path,
            "timeout_seconds": timeout,
        }

    def _verify_manifest(self, snapshot: Path, step: dict[str, object]) -> None:
        manifest_path = snapshot / MANIFEST_FILE
        if manifest_path.is_symlink() or not manifest_path.is_file():
            raise RunnerSecurityError("运行快照缺少 manifest")
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RunnerSecurityError("运行 manifest 无法读取") from exc
        if not isinstance(manifest, dict):
            raise RunnerSecurityError("运行 manifest 格式无效")
        expected_digest = manifest.pop("manifest_sha256", None)
        canonical = json.dumps(
            manifest,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        if not isinstance(expected_digest, str) or not _constant_digest(
            expected_digest, hashlib.sha256(canonical).hexdigest()
        ):
            raise RunnerSecurityError("运行 manifest 摘要不匹配")
        expected_identity = {
            "snapshot_id": _required_string(step, "snapshot_id"),
            "owner_type": _required_string(step, "owner_type"),
            "owner_id": _required_string(step, "owner_id"),
            "profile": _required_string(step, "mode"),
        }
        if any(manifest.get(key) != value for key, value in expected_identity.items()):
            raise RunnerSecurityError("运行 manifest 身份不匹配")
        files = manifest.get("files")
        if not isinstance(files, list) or manifest.get("file_count") != len(files):
            raise RunnerSecurityError("运行 manifest 文件数量无效")
        total_bytes = 0
        seen: set[str] = set()
        for item in files:
            if not isinstance(item, dict):
                raise RunnerSecurityError("运行 manifest 文件记录无效")
            relative = _safe_relative(_required_string(item, "relative_path"), "快照文件")
            normalized = relative.as_posix()
            if normalized in seen or normalized == MANIFEST_FILE:
                raise RunnerSecurityError("运行 manifest 包含重复或保留路径")
            seen.add(normalized)
            file_path = snapshot.joinpath(*relative.parts)
            _reject_symlink_chain(file_path, snapshot)
            if not file_path.is_file():
                raise RunnerSecurityError("运行快照文件缺失")
            content = file_path.read_bytes()
            size = len(content)
            total_bytes += size
            if item.get("size_bytes") != size or not _constant_digest(
                str(item.get("sha256", "")), hashlib.sha256(content).hexdigest()
            ):
                raise RunnerSecurityError("运行快照文件摘要不匹配")
        if manifest.get("total_bytes") != total_bytes:
            raise RunnerSecurityError("运行快照总大小不匹配")

    def _execute_step(
        self,
        *,
        operation_id: str,
        lease_token: str,
        step: dict[str, object],
        workspace_root: Path,
        project_root: Path | None,
        snapshot_root: Path,
        entry: Path,
        log_path: Path,
        timeout_seconds: int,
    ) -> tuple[int, str | None, str | None]:
        log_path.parent.mkdir(parents=True, exist_ok=True, mode=0o750)
        environment = _controlled_environment()
        environment.update(
            {
                "RUNTIME_OPERATION_ID": operation_id,
                "RUNTIME_STEP_ID": _required_string(step, "id"),
                "RUNTIME_DEPLOY_MODE": _required_string(step, "mode"),
                "RUNTIME_SNAPSHOT_DIR": str(snapshot_root),
                "WORKSPACE_ROOT": str(workspace_root),
                "WORKSPACE_HOST_ROOT": str(workspace_root),
            }
        )
        if project_root is not None:
            environment["PROJECT_ROOT"] = str(project_root)
            environment["PROJECT_HOST_ROOT"] = str(project_root)

        stop_heartbeat = threading.Event()
        heartbeat = threading.Thread(
            target=self._heartbeat_loop,
            args=(operation_id, lease_token, stop_heartbeat),
            daemon=True,
        )
        try:
            with log_path.open("wb") as log_stream:
                header = (
                    f"[runtime] operation={operation_id} "
                    f"step={_required_string(step, 'id')} "
                    f"owner={_required_string(step, 'owner_type')}:"
                    f"{_required_string(step, 'owner_id')} "
                    f"mode={_required_string(step, 'mode')}\n"
                )
                log_stream.write(header.encode())
                log_stream.flush()
                process = subprocess.Popen(
                    ["/bin/sh", str(entry)],
                    cwd=str(snapshot_root),
                    env=environment,
                    stdout=log_stream,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
                heartbeat.start()
                try:
                    exit_code = process.wait(timeout=timeout_seconds)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait()
                    return EXIT_TIMEOUT, "runtime_timeout", "运行步骤超过允许时间"
                if exit_code != 0:
                    return exit_code, "runtime_exit_nonzero", f"运行入口退出码为 {exit_code}"
                return 0, None, None
        except OSError as exc:
            return EXIT_VALIDATION_FAILED, "runtime_process_failed", str(exc)[:500]
        finally:
            stop_heartbeat.set()
            if heartbeat.is_alive():
                heartbeat.join(timeout=self._heartbeat_seconds + 1)

    def _heartbeat_loop(
        self,
        operation_id: str,
        lease_token: str,
        stopped: threading.Event,
    ) -> None:
        while not stopped.wait(self._heartbeat_seconds):
            try:
                self._api.heartbeat_operation(operation_id, lease_token)
            except RunnerError:
                pass


def run_forever(
    *,
    api: RunnerApiClient,
    runner: HostRuntimeRunner,
    runner_id: str,
    poll_seconds: float,
    once: bool,
) -> None:
    stopped = threading.Event()

    def stop_handler(_signum: int, _frame: object) -> None:
        stopped.set()

    signal.signal(signal.SIGTERM, stop_handler)
    signal.signal(signal.SIGINT, stop_handler)
    api.register(runner_id)
    print(f"[runner] registered id={runner_id}", flush=True)
    while not stopped.is_set():
        try:
            api.heartbeat_runner(runner_id)
            lease = api.lease(runner_id)
            if lease.get("operation") is not None:
                runner.execute_lease(lease)
                if once:
                    return
        except RunnerError as exc:
            print(f"[runner] {exc}", file=sys.stderr, flush=True)
        if once:
            return
        stopped.wait(poll_seconds)


def load_private_token(path: Path) -> str:
    try:
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise RunnerSecurityError("Runner token 必须是普通文件")
        if stat.S_IMODE(metadata.st_mode) & 0o077:
            raise RunnerSecurityError("Runner token 权限必须为 0600")
        value = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise RunnerSecurityError("Runner token 无法读取") from exc
    if len(value) < 32:
        raise RunnerSecurityError("Runner token 长度不足")
    return value


def _controlled_environment() -> dict[str, str]:
    allowed = {
        "PATH",
        "HOME",
        "USER",
        "LOGNAME",
        "SHELL",
        "TMPDIR",
        "LANG",
        "LC_ALL",
        "TERM",
        "SSH_AUTH_SOCK",
        "DOCKER_HOST",
    }
    return {key: value for key, value in os.environ.items() if key in allowed}


def _safe_relative(value: str, label: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if (
        not value
        or value.startswith("/")
        or "\\" in value
        or "\x00" in value
        or path.is_absolute()
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise RunnerSecurityError(f"{label}必须是安全相对路径")
    return path


def _reject_symlink_chain(path: Path, root: Path) -> None:
    relative = path.relative_to(root)
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise RunnerSecurityError("运行路径不能包含软链接")


def _require_within(path: Path, root: Path, message: str) -> None:
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise RunnerSecurityError(message) from exc


def _constant_digest(left: str, right: str) -> bool:
    if len(left) != len(right):
        return False
    return hmac.compare_digest(left, right)


def _required_dict(payload: dict[str, object], key: str) -> dict[str, object]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise RunnerError(f"缺少 {key}")
    return value


def _required_string(payload: dict[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise RunnerError(f"缺少 {key}")
    return value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Context Router Host Runtime Runner")
    parser.add_argument("--control-url", default="http://127.0.0.1:49173")
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--token-path", type=Path, required=True)
    parser.add_argument("--poll-seconds", type=float, default=2)
    parser.add_argument("--heartbeat-seconds", type=float, default=10)
    parser.add_argument("--runner-id")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--daemonize", action="store_true")
    parser.add_argument("--pid-path", type=Path)
    return parser.parse_args()


def daemonize(pid_path: Path) -> bool:
    first_pid = os.fork()
    if first_pid > 0:
        _, status_code = os.waitpid(first_pid, 0)
        if status_code != 0:
            raise RunnerError("Host Runner 后台进程初始化失败")
        return False
    try:
        os.setsid()
        second_pid = os.fork()
        if second_pid > 0:
            os._exit(0)
        os.chdir("/")
        os.umask(0o077)
        pid_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = pid_path.with_name(f".{pid_path.name}.{os.getpid()}.tmp")
        temporary.write_text(f"{os.getpid()}\n", encoding="utf-8")
        temporary.chmod(0o600)
        temporary.replace(pid_path)
        return True
    except BaseException:
        os._exit(1)


def main() -> int:
    args = parse_args()
    try:
        if args.daemonize:
            if args.pid_path is None:
                raise RunnerError("--daemonize 必须同时提供 --pid-path")
            if not daemonize(args.pid_path):
                return 0
        token = load_private_token(args.token_path)
        api = RunnerApiClient(args.control_url, token)
        runner = HostRuntimeRunner(
            api=api,
            allowed_workspace_root=args.workspace_root,
            runtime_root=args.runtime_root,
            heartbeat_seconds=args.heartbeat_seconds,
        )
        runner_id = args.runner_id or f"{socket.gethostname()}-{os.getpid()}"
        run_forever(
            api=api,
            runner=runner,
            runner_id=runner_id,
            poll_seconds=max(0.25, args.poll_seconds),
            once=args.once,
        )
    except RunnerError as exc:
        print(f"[runner] {exc}", file=sys.stderr)
        return 1
    finally:
        if args.daemonize and args.pid_path is not None and os.getpid() == _pid_file(args.pid_path):
            try:
                args.pid_path.unlink(missing_ok=True)
            except OSError:
                pass
    return 0


def _pid_file(path: Path) -> int | None:
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


if __name__ == "__main__":
    raise SystemExit(main())
