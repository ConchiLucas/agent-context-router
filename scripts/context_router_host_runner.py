#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import hmac
import http.client
import json
import os
import platform
import re
import signal
import socket
import stat
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path, PurePosixPath
from typing import Protocol

RUNNER_VERSION = "3"
MANIFEST_FILE = ".runtime-manifest.json"
ENTRY_FILE = "deploy.sh"
EXIT_VALIDATION_FAILED = 126
EXIT_TIMEOUT = 124
HOST_SCRIPT_ROOT = Path(
    "/Users/conchi/workforce/company_workforce/panzhihua_dev_workforce/deploy/host-runtime"
)
HOST_ACTIONS: dict[str, tuple[Path, str, int]] = {
    "pzh.start-and-check": (
        HOST_SCRIPT_ROOT / "start-and-check.sh",
        "start-and-check",
        3600,
    ),
    "pzh.ensure-host-runtime": (
        HOST_SCRIPT_ROOT / "ensure.sh",
        "ensure",
        600,
    ),
    "pzh.status-host-runtime": (
        HOST_SCRIPT_ROOT / "ensure.sh",
        "status",
        120,
    ),
}
SAFE_RESPONSE_HEADERS = {"content-type", "x-request-id", "trace-id", "x-trace-id"}
FORBIDDEN_REQUEST_HEADERS = {
    "connection",
    "content-length",
    "forwarded",
    "host",
    "proxy-authorization",
    "te",
    "transfer-encoding",
    "upgrade",
    "via",
    "x-forwarded-for",
    "x-forwarded-host",
    "x-forwarded-proto",
}
READINESS_PATTERN = re.compile(
    r"\[READINESS\]\s+"
    r"infrastructure=(pending|ready|failed)\s+"
    r"services=(pending|ready|failed)\s+"
    r"business=(pending|ready|failed)(?P<details>[^\r\n]*)"
)


class RunnerError(RuntimeError):
    pass


class RunnerSecurityError(RunnerError):
    pass


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


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
        readiness: dict[str, object] | None = None,
    ) -> None: ...

    def submit_host_action(
        self, workspace_id: str, action: str, environment: str
    ) -> dict[str, object]: ...
    def complete_forwarding_job(
        self,
        job_id: str,
        runner_id: str,
        lease_token: str,
        result: dict[str, object],
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
                "capabilities": ["docker", "posix-shell", "interface-forwarding"],
            },
        )

    def heartbeat_runner(self, runner_id: str) -> dict[str, object]:
        return self._post("/api/runtime-runner/heartbeat", {"runner_id": runner_id})

    def lease(self, runner_id: str) -> dict[str, object]:
        return self._post("/api/runtime-runner/lease", {"runner_id": runner_id})

    def lease_forwarding(self, runner_id: str) -> dict[str, object]:
        return self._post(
            "/api/runtime-runner/forwarding/lease", {"runner_id": runner_id}
        )

    def complete_forwarding_job(
        self,
        job_id: str,
        runner_id: str,
        lease_token: str,
        result: dict[str, object],
    ) -> None:
        self._post(
            f"/api/runtime-runner/forwarding/jobs/{job_id}/complete",
            {"runner_id": runner_id, "lease_token": lease_token, **result},
        )

    def submit_host_action(
        self, workspace_id: str, action: str, environment: str
    ) -> dict[str, object]:
        return self._post(
            f"/api/workspaces/{workspace_id}/host-runtime/actions",
            {"action": action, "environment": environment},
        )

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
        readiness: dict[str, object] | None = None,
    ) -> None:
        self._post(
            f"/api/runtime-runner/operations/{operation_id}/steps/{step_id}/complete",
            {
                "lease_token": lease_token,
                "exit_code": exit_code,
                "error_code": error_code,
                "error_message": error_message,
                "readiness": readiness,
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
        except (
            urllib.error.URLError,
            http.client.HTTPException,
            TimeoutError,
            OSError,
        ) as exc:
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
        workspace_id = _required_string(operation, "workspace_id")
        project_ids_by_relative_path = _required_string_map(lease, "project_ids_by_relative_path")
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
                environment_name = _operation_environment(operation)
                if operation.get("kind") == "host_action":
                    execution = self._validate_host_action(operation, raw_step)
                else:
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
            if operation.get("kind") == "host_action":
                exit_code, error_code, error_message = self._execute_host_action(
                    operation_id=operation_id,
                    workspace_id=workspace_id,
                    lease_token=lease_token,
                    step=raw_step,
                    **execution,
                )
                readiness = _read_readiness_result(execution["log_path"])
            else:
                exit_code, error_code, error_message = self._execute_step(
                    operation_id=operation_id,
                    workspace_id=workspace_id,
                    project_ids_by_relative_path=project_ids_by_relative_path,
                    lease_token=lease_token,
                    step=raw_step,
                    environment_name=environment_name,
                    **execution,
                )
                readiness = None
            self._api.complete_step(
                operation_id,
                step_id,
                lease_token,
                exit_code,
                error_code,
                error_message,
                readiness,
            )
            if exit_code != 0:
                return

    def execute_forwarding_job(
        self, payload: dict[str, object], *, runner_id: str
    ) -> None:
        job_id = _required_string(payload, "job_id")
        lease_token = _required_string(payload, "lease_token")
        request_payload = _required_dict(payload, "request")
        started = time.perf_counter()
        status_code: int | None = None
        response_body = ""
        response_headers: dict[str, str] = {}
        response_bytes = 0
        response_truncated = False
        error_type: str | None = None
        try:
            request, timeout_seconds, max_response_bytes = self._forwarding_request(
                request_payload
            )
            opener = urllib.request.build_opener(_NoRedirectHandler())
            try:
                response = opener.open(request, timeout=timeout_seconds)
            except urllib.error.HTTPError as exc:
                response = exc
            with response:
                status_code = int(response.status)
                response_headers = {
                    key.lower(): value
                    for key, value in response.headers.items()
                    if key.lower() in SAFE_RESPONSE_HEADERS
                }
                chunks: list[bytes] = []
                retained = 0
                while True:
                    chunk = response.read(65_536)
                    if not chunk:
                        break
                    response_bytes += len(chunk)
                    if retained < max_response_bytes:
                        piece = chunk[: max_response_bytes - retained]
                        chunks.append(piece)
                        retained += len(piece)
                    if response_bytes > max_response_bytes:
                        response_truncated = True
                        break
                response_body = b"".join(chunks).decode("utf-8", errors="replace")
        except (
            RunnerError,
            urllib.error.URLError,
            http.client.HTTPException,
            TimeoutError,
            OSError,
        ) as exc:
            error_type = exc.__class__.__name__
            response_body = f"请求失败：{error_type}"
        duration_ms = max(0, round((time.perf_counter() - started) * 1000))
        self._api.complete_forwarding_job(
            job_id,
            runner_id,
            lease_token,
            {
                "status_code": status_code,
                "response_body": response_body,
                "response_headers": response_headers,
                "response_bytes": response_bytes,
                "response_truncated": response_truncated,
                "error_type": error_type,
                "duration_ms": duration_ms,
            },
        )

    @staticmethod
    def _forwarding_request(
        payload: dict[str, object],
    ) -> tuple[urllib.request.Request, int, int]:
        method = _required_string(payload, "method").upper()
        if method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
            raise RunnerSecurityError("宿主机接口转发方法不受支持")
        url = _required_string(payload, "url")
        parsed = urllib.parse.urlsplit(url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
        ):
            raise RunnerSecurityError("宿主机接口转发地址无效")
        query = payload.get("query") or {}
        body = payload.get("body") or {}
        headers = payload.get("headers") or {}
        if (
            not isinstance(query, dict)
            or not isinstance(body, dict)
            or not isinstance(headers, dict)
        ):
            raise RunnerSecurityError("宿主机接口转发参数格式无效")
        encoded_query = urllib.parse.urlencode(query, doseq=True)
        if encoded_query:
            url += ("&" if parsed.query else "?") + encoded_query
        request_headers: dict[str, str] = {}
        for raw_name, raw_value in headers.items():
            if not isinstance(raw_name, str) or not isinstance(raw_value, str):
                raise RunnerSecurityError("宿主机接口转发请求头格式无效")
            name = raw_name.strip()
            if (
                not name
                or name.lower() in FORBIDDEN_REQUEST_HEADERS
                or any(character in name or character in raw_value for character in ("\r", "\n"))
            ):
                raise RunnerSecurityError("宿主机接口转发请求头不安全")
            request_headers[name] = raw_value
        data: bytes | None = None
        if method in {"POST", "PUT", "PATCH", "DELETE"}:
            data = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()
            if len(data) > 262_144:
                raise RunnerSecurityError("宿主机接口转发请求体超过限制")
            request_headers.setdefault("Content-Type", "application/json")
        timeout_seconds = payload.get("timeout_seconds")
        max_response_bytes = payload.get("max_response_bytes")
        if not isinstance(timeout_seconds, int) or not 1 <= timeout_seconds <= 30:
            raise RunnerSecurityError("宿主机接口转发超时范围无效")
        if (
            not isinstance(max_response_bytes, int)
            or not 1 <= max_response_bytes <= 1_048_576
        ):
            raise RunnerSecurityError("宿主机接口转发响应上限无效")
        return (
            urllib.request.Request(
                url, data=data, headers=request_headers, method=method
            ),
            timeout_seconds,
            max_response_bytes,
        )

    def _validate_step(
        self,
        operation: dict[str, object],
        step: dict[str, object],
    ) -> dict[str, object]:
        resolved_workspace = self._resolved_workspace(operation)

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

    def _validate_host_action(
        self,
        operation: dict[str, object],
        step: dict[str, object],
    ) -> dict[str, object]:
        workspace_root = self._resolved_workspace(operation)
        action = _required_string(operation, "action")
        definition = HOST_ACTIONS.get(action)
        if definition is None:
            raise RunnerSecurityError("宿主机动作不在白名单中")
        if step.get("owner_type") != "workspace" or step.get("mode") != "host":
            raise RunnerSecurityError("宿主机动作步骤身份无效")
        if step.get("owner_id") != operation.get("workspace_id"):
            raise RunnerSecurityError("宿主机动作 Workspace 身份不匹配")

        log_relative = _safe_relative(_required_string(step, "log_relative_path"), "日志路径")
        log_path = self._runtime_root.joinpath(*log_relative.parts)
        _require_within(log_path.resolve(strict=False), self._runtime_root, "日志路径越界")
        if log_path.is_symlink():
            raise RunnerSecurityError("日志文件不能是软链接")

        script, command, action_timeout = definition
        self._validate_host_script(script)
        timeout = operation.get("timeout_seconds")
        if not isinstance(timeout, int) or not 10 <= timeout <= 7200:
            raise RunnerSecurityError("运行超时范围无效")
        return {
            "workspace_root": workspace_root,
            "script": script,
            "command": command,
            "action": action,
            "environment_name": _operation_environment(operation),
            "log_path": log_path,
            "timeout_seconds": min(timeout, action_timeout),
        }

    def _resolved_workspace(self, operation: dict[str, object]) -> Path:
        workspace_root = Path(_required_string(operation, "workspace_host_root"))
        if not workspace_root.is_absolute():
            raise RunnerSecurityError("Workspace 根目录必须是绝对路径")
        resolved_workspace = workspace_root.resolve(strict=True)
        _require_within(resolved_workspace, self._allowed_workspace_root, "Workspace 越界")
        if not resolved_workspace.is_dir():
            raise RunnerSecurityError("Workspace 根目录不可用")
        return resolved_workspace

    @staticmethod
    def _validate_host_script(script: Path) -> None:
        root = HOST_SCRIPT_ROOT.resolve(strict=True)
        try:
            metadata = script.lstat()
            resolved = script.resolve(strict=True)
        except OSError as exc:
            raise RunnerSecurityError("白名单宿主机脚本不存在") from exc
        if resolved.parent != root or resolved != script:
            raise RunnerSecurityError("白名单宿主机脚本路径无效")
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise RunnerSecurityError("白名单宿主机脚本必须是普通文件")
        if metadata.st_uid != os.getuid():
            raise RunnerSecurityError("白名单宿主机脚本所有者无效")
        if stat.S_IMODE(metadata.st_mode) & 0o022:
            raise RunnerSecurityError("白名单宿主机脚本不能允许组或其他用户写入")
        if not os.access(script, os.X_OK):
            raise RunnerSecurityError("白名单宿主机脚本不可执行")
        state_path = root.parent / "runtime/context-router-shared-files.json"
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
            revision = int(state["revision"])
            digest = str(state["digest"])
            expected_sha256 = str(state["files"][f"deploy/host-runtime/{script.name}"])
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise RunnerSecurityError("宿主机脚本缺少有效的数据库同步状态") from exc
        if revision < 1 or len(digest) != 64 or len(expected_sha256) != 64:
            raise RunnerSecurityError("宿主机脚本数据库同步状态无效")
        actual_sha256 = hashlib.sha256(script.read_bytes()).hexdigest()
        if not hmac.compare_digest(actual_sha256, expected_sha256):
            raise RunnerSecurityError("宿主机脚本与数据库同步摘要不一致")

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
        workspace_id: str,
        project_ids_by_relative_path: dict[str, str],
        lease_token: str,
        step: dict[str, object],
        workspace_root: Path,
        project_root: Path | None,
        snapshot_root: Path,
        entry: Path,
        log_path: Path,
        timeout_seconds: int,
        environment_name: str,
    ) -> tuple[int, str | None, str | None]:
        log_path.parent.mkdir(parents=True, exist_ok=True, mode=0o750)
        environment = _controlled_environment()
        environment.update(
            {
                "RUNTIME_OPERATION_ID": operation_id,
                "RUNTIME_STEP_ID": _required_string(step, "id"),
                "RUNTIME_DEPLOY_MODE": _required_string(step, "mode"),
                "RUNTIME_WORKSPACE_ID": workspace_id,
                "RUNTIME_PROJECT_IDS": "\n".join(
                    f"{relative_path}\t{project_id}"
                    for relative_path, project_id in sorted(project_ids_by_relative_path.items())
                ),
                "RUNTIME_SNAPSHOT_DIR": str(snapshot_root),
                "WORKSPACE_ROOT": str(workspace_root),
                "WORKSPACE_HOST_ROOT": str(workspace_root),
                "C12_ENVIRONMENT": environment_name,
            }
        )
        if project_root is not None:
            environment["PROJECT_ROOT"] = str(project_root)
            environment["PROJECT_HOST_ROOT"] = str(project_root)
            environment["RUNTIME_PROJECT_ID"] = _required_string(step, "owner_id")

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
                    f"mode={_required_string(step, 'mode')} "
                    f"environment={environment_name}\n"
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

    def _execute_host_action(
        self,
        *,
        operation_id: str,
        workspace_id: str,
        lease_token: str,
        step: dict[str, object],
        workspace_root: Path,
        script: Path,
        command: str,
        action: str,
        environment_name: str,
        log_path: Path,
        timeout_seconds: int,
    ) -> tuple[int, str | None, str | None]:
        log_path.parent.mkdir(parents=True, exist_ok=True, mode=0o750)
        environment = _controlled_environment()
        environment.update(
            {
                "C12_ENVIRONMENT": environment_name,
                "RUNTIME_ACTION": action,
                "RUNTIME_OPERATION_ID": operation_id,
                "RUNTIME_STEP_ID": _required_string(step, "id"),
                "RUNTIME_WORKSPACE_ID": workspace_id,
                "WORKSPACE_ROOT": str(workspace_root),
                "WORKSPACE_HOST_ROOT": str(workspace_root),
            }
        )
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
                    f"owner=workspace:{workspace_id} mode=host "
                    f"action={action} environment={environment_name}\n"
                )
                log_stream.write(header.encode())
                log_stream.flush()
                process = subprocess.Popen(
                    [str(script), command, "--environment", environment_name],
                    cwd=str(HOST_SCRIPT_ROOT),
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
                    return EXIT_TIMEOUT, "runtime_timeout", "宿主机动作超过允许时间"
                if exit_code != 0:
                    return exit_code, "runtime_exit_nonzero", f"宿主机动作退出码为 {exit_code}"
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
    startup_workspace_id: str | None = None,
    startup_action: str | None = None,
    startup_environment: str = "local",
) -> None:
    stopped = threading.Event()

    def stop_handler(_signum: int, _frame: object) -> None:
        stopped.set()

    signal.signal(signal.SIGTERM, stop_handler)
    signal.signal(signal.SIGINT, stop_handler)
    api.register(runner_id)
    print(f"[runner] registered id={runner_id}", flush=True)
    startup_pending = startup_workspace_id is not None and startup_action is not None
    next_startup_attempt = 0.0

    def poll_forwarding() -> bool:
        forwarding_lease = api.lease_forwarding(runner_id)
        forwarding_job = forwarding_lease.get("job")
        if forwarding_job is None:
            return False
        if not isinstance(forwarding_job, dict):
            raise RunnerError("宿主机接口转发租约格式无效")
        runner.execute_forwarding_job(forwarding_job, runner_id=runner_id)
        return True

    def forwarding_loop() -> None:
        while not stopped.is_set():
            try:
                # 部署步骤可能持续数分钟；独立心跳和租约线程保证接口转发不会被阻塞。
                api.heartbeat_runner(runner_id)
                poll_forwarding()
            except RunnerError as exc:
                print(f"[runner] {exc}", file=sys.stderr, flush=True)
            stopped.wait(poll_seconds)

    forwarding_thread: threading.Thread | None = None
    if not once:
        forwarding_thread = threading.Thread(
            target=forwarding_loop,
            name="context-router-forwarding",
            daemon=True,
        )
        forwarding_thread.start()
    try:
        while not stopped.is_set():
            try:
                api.heartbeat_runner(runner_id)
                if startup_pending and time.monotonic() >= next_startup_attempt:
                    try:
                        result = api.submit_host_action(
                            startup_workspace_id,
                            startup_action,
                            startup_environment,
                        )
                        print(
                            "[runner] startup host action queued "
                            f"action={startup_action} environment={startup_environment} "
                            f"operation={result.get('id', 'unknown')}",
                            flush=True,
                        )
                        startup_pending = False
                    except RunnerError as exc:
                        print(
                            f"[runner] 启动保障任务提交失败：{exc}",
                            file=sys.stderr,
                            flush=True,
                        )
                        next_startup_attempt = time.monotonic() + 15
                if once and poll_forwarding():
                    return
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
    finally:
        stopped.set()
        if forwarding_thread is not None and forwarding_thread.is_alive():
            forwarding_thread.join(timeout=poll_seconds + 1)


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
    environment = {key: value for key, value in os.environ.items() if key in allowed}
    inherited_path = environment.get("PATH", "")
    configured_path = os.environ.get("CONTEXT_ROUTER_HOST_TOOL_PATHS", "")
    path_entries = [
        entry
        for value in (inherited_path, configured_path)
        for entry in value.split(os.pathsep)
        if entry
    ]
    # launchd jobs commonly receive only /usr/bin:/bin:/usr/sbin:/sbin. Keep the
    # host-runner useful for workspace scripts that call Docker Desktop or
    # Homebrew-installed tools without requiring every workspace to repair PATH.
    for entry in (
        "/usr/local/bin",
        "/opt/homebrew/bin",
        "/usr/bin",
        "/bin",
        "/usr/sbin",
        "/sbin",
    ):
        if entry not in path_entries:
            path_entries.append(entry)
    environment["PATH"] = os.pathsep.join(path_entries)
    return environment


def _read_readiness_result(log_path: object) -> dict[str, object] | None:
    if not isinstance(log_path, Path):
        return None
    try:
        content = log_path.read_text(encoding="utf-8", errors="replace")[-131_072:]
    except OSError:
        return None
    matches = list(READINESS_PATTERN.finditer(content))
    if not matches:
        return None
    latest = matches[-1]
    details = latest.group("details")

    def detail_number(key: str) -> int | None:
        match = re.search(rf"(?:^|\s){re.escape(key)}=(\d+)(?:\s|$)", details)
        return int(match.group(1)) if match else None

    labels = {
        "infrastructure": "基础设施",
        "services": "项目服务",
        "business": "业务入口",
    }
    result: dict[str, object] = {}
    for index, key in enumerate(labels, start=1):
        status = latest.group(index)
        result[key] = {
            "status": status,
            "duration_ms": detail_number(f"{key}_ms"),
            "error_message": (
                f"{labels[key]}阶段失败，详见运行日志" if status == "failed" else None
            ),
        }
    revision = detail_number("revision")
    result["revision"] = revision if revision and revision >= 1 else None
    return result


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


def _required_string_map(payload: dict[str, object], key: str) -> dict[str, str]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise RunnerError(f"缺少 {key}")
    result: dict[str, str] = {}
    for raw_path, raw_id in value.items():
        if not isinstance(raw_path, str) or not isinstance(raw_id, str) or not raw_id:
            raise RunnerError(f"{key} 格式无效")
        if any(character in raw_path or character in raw_id for character in ("\t", "\n", "\r")):
            raise RunnerError(f"{key} 包含非法字符")
        result[_safe_relative(raw_path, "项目路径").as_posix()] = raw_id
    return result


def _operation_environment(operation: dict[str, object]) -> str:
    value = operation.get("environment") or "local"
    if not isinstance(value, str) or value not in {"local", "test", "uat"}:
        raise RunnerSecurityError("environment 仅支持 local、test 或 uat")
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
    parser.add_argument("--startup-workspace-id")
    parser.add_argument("--startup-action", choices=tuple(HOST_ACTIONS))
    parser.add_argument(
        "--startup-environment",
        choices=("local", "test", "uat"),
        default="local",
    )
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


def write_pid_file(pid_path: Path) -> None:
    pid_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = pid_path.with_name(f".{pid_path.name}.{os.getpid()}.tmp")
    temporary.write_text(f"{os.getpid()}\n", encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(pid_path)


def main() -> int:
    args = parse_args()
    try:
        if args.daemonize:
            if args.pid_path is None:
                raise RunnerError("--daemonize 必须同时提供 --pid-path")
            if not daemonize(args.pid_path):
                return 0
        elif args.pid_path is not None:
            write_pid_file(args.pid_path)
        if (args.startup_workspace_id is None) != (args.startup_action is None):
            raise RunnerError(
                "--startup-workspace-id 与 --startup-action 必须同时提供"
            )
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
            startup_workspace_id=args.startup_workspace_id,
            startup_action=args.startup_action,
            startup_environment=args.startup_environment,
        )
    except RunnerError as exc:
        print(f"[runner] {exc}", file=sys.stderr)
        return 1
    finally:
        if args.pid_path is not None and os.getpid() == _pid_file(args.pid_path):
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
