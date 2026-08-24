from __future__ import annotations

import codecs
import http.client
import json
import re
import socket
import threading
from collections.abc import Callable, Iterator, Mapping
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from queue import Empty, Full, Queue
from urllib.parse import quote, urlencode

from context_router.schemas.workspaces import WorkspaceContainerSummary

MAX_DOCKER_RESPONSE_BYTES = 2_000_000
MAX_LOG_SNAPSHOT_BYTES = 512_000
MAX_LOG_LINE_CHARS = 65_536
LOG_HEARTBEAT_SECONDS = 15
MAX_CONTAINER_ACTION_WORKERS = 6
CONTAINER_ID_PATTERN = re.compile(r"^[a-f0-9]{12,64}$")
ANSI_ESCAPE_PATTERN = re.compile(r"\x1b(?:[@-_][0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))")
TIMESTAMP_PATTERN = re.compile(r"^(?P<timestamp>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z)\s?")


class WorkspaceContainerError(RuntimeError):
    pass


@dataclass(frozen=True)
class _LogRecord:
    stream: str
    content: str
    timestamp: str | None


@dataclass(frozen=True)
class ContainerLogRecord:
    stream: str
    content: str
    timestamp: str | None


@dataclass(frozen=True)
class ContainerLogSnapshot:
    records: list[ContainerLogRecord]
    truncated: bool


class _UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self, socket_path: Path, *, timeout: float | None = 5) -> None:
        super().__init__("localhost", timeout=timeout)
        self._socket_path = socket_path

    def connect(self) -> None:
        connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        connection.settimeout(self.timeout)
        connection.connect(str(self._socket_path))
        self.sock = connection


class _DockerLogParser:
    def __init__(self, *, tty: bool) -> None:
        self._tty = tty
        self._frame_buffer = bytearray()
        self._text_buffers = {"stdout": "", "stderr": ""}
        self._decoders = {
            "stdout": codecs.getincrementaldecoder("utf-8")("replace"),
            "stderr": codecs.getincrementaldecoder("utf-8")("replace"),
        }

    def feed(self, chunk: bytes) -> list[_LogRecord]:
        if not chunk:
            return []
        if self._tty:
            return self._feed_text("stdout", chunk)

        self._frame_buffer.extend(chunk)
        records: list[_LogRecord] = []
        while len(self._frame_buffer) >= 8:
            payload_size = int.from_bytes(self._frame_buffer[4:8], "big")
            if len(self._frame_buffer) < 8 + payload_size:
                break
            stream = "stderr" if self._frame_buffer[0] == 2 else "stdout"
            payload = bytes(self._frame_buffer[8 : 8 + payload_size])
            del self._frame_buffer[: 8 + payload_size]
            records.extend(self._feed_text(stream, payload))
        return records

    def flush(self) -> list[_LogRecord]:
        records: list[_LogRecord] = []
        for stream in ("stdout", "stderr"):
            decoded = self._decoders[stream].decode(b"", final=True)
            if decoded:
                self._text_buffers[stream] += decoded
            if self._text_buffers[stream]:
                records.append(_parse_log_record(stream, self._text_buffers[stream]))
                self._text_buffers[stream] = ""
        return records

    def _feed_text(self, stream: str, payload: bytes) -> list[_LogRecord]:
        self._text_buffers[stream] += self._decoders[stream].decode(payload)
        records: list[_LogRecord] = []
        while "\n" in self._text_buffers[stream]:
            line, self._text_buffers[stream] = self._text_buffers[stream].split("\n", 1)
            records.append(_parse_log_record(stream, line.rstrip("\r")))
        while len(self._text_buffers[stream]) > MAX_LOG_LINE_CHARS:
            line = self._text_buffers[stream][:MAX_LOG_LINE_CHARS]
            self._text_buffers[stream] = self._text_buffers[stream][MAX_LOG_LINE_CHARS:]
            records.append(_parse_log_record(stream, line))
        return records


class WorkspaceContainerService:
    def __init__(
        self,
        docker_socket: Path,
        *,
        connection_factory: Callable[[], http.client.HTTPConnection] | None = None,
    ) -> None:
        self._docker_socket = docker_socket
        self._uses_docker_socket = connection_factory is None
        self._connection_factory = connection_factory

    def list_containers(
        self,
        workspace_id: str,
        *,
        project_names: Mapping[str, str] | None = None,
        project_kinds: Mapping[str, str] | None = None,
    ) -> list[WorkspaceContainerSummary]:
        self._ensure_socket()
        filters = json.dumps(
            {"label": [f"runtime-runner.workspace-id={workspace_id}"]},
            separators=(",", ":"),
        )
        path = f"/containers/json?{urlencode({'all': '1', 'filters': filters})}"
        document = self._read_json(path, "Docker 容器列表读取失败")
        if not isinstance(document, list):
            raise WorkspaceContainerError("Docker 返回了无效的容器列表")
        names = project_names or {}
        kinds = project_kinds or {}
        containers = [
            _container_summary(item, names, kinds) for item in document if isinstance(item, dict)
        ]
        return sorted(
            containers,
            key=lambda item: (item.state != "running", item.name.casefold()),
        )

    def stream_logs(
        self,
        workspace_id: str,
        container_id: str,
        *,
        tail: int = 200,
        since: str | None = None,
    ) -> Iterator[str]:
        config = self._validated_container_config(workspace_id, container_id)
        encoded_id = quote(container_id, safe="")

        query: dict[str, str] = {
            "follow": "1",
            "stdout": "1",
            "stderr": "1",
            "timestamps": "1",
            "tail": str(max(1, min(tail, 1000))),
        }
        if since and TIMESTAMP_PATTERN.match(since):
            query["since"] = since
        connection = self._connection(streaming=True)
        try:
            connection.request(
                "GET",
                f"/containers/{encoded_id}/logs?{urlencode(query)}",
                headers={"Accept": "application/octet-stream"},
            )
            response = connection.getresponse()
        except (OSError, http.client.HTTPException, TimeoutError) as exc:
            connection.close()
            raise WorkspaceContainerError("Docker 实时日志连接失败") from exc
        if response.status == 404:
            connection.close()
            raise WorkspaceContainerError("容器不存在")
        if response.status != 200:
            connection.close()
            raise WorkspaceContainerError("Docker 实时日志连接失败")

        return self._log_event_stream(
            connection,
            response,
            tty=bool(config.get("Tty")),
        )

    def read_log_snapshot(
        self,
        workspace_id: str,
        container_id: str,
        *,
        tail: int = 500,
        since: str | None = None,
    ) -> ContainerLogSnapshot:
        """Read one bounded, non-following log snapshot from a registered container."""
        config = self._validated_container_config(workspace_id, container_id)
        encoded_id = quote(container_id, safe="")
        query: dict[str, str] = {
            "follow": "0",
            "stdout": "1",
            "stderr": "1",
            "timestamps": "1",
            "tail": str(max(1, min(tail, 1000))),
        }
        if since and TIMESTAMP_PATTERN.match(since):
            query["since"] = since

        connection = self._connection(timeout=10)
        try:
            connection.request(
                "GET",
                f"/containers/{encoded_id}/logs?{urlencode(query)}",
                headers={"Accept": "application/octet-stream"},
            )
            response = connection.getresponse()
            if response.status == 404:
                raise WorkspaceContainerError("容器不存在")
            if response.status != 200:
                raise WorkspaceContainerError("Docker 日志快照读取失败")

            parser = _DockerLogParser(tty=bool(config.get("Tty")))
            parsed: list[_LogRecord] = []
            total_bytes = 0
            truncated = False
            while True:
                chunk = response.read(16_384)
                if not chunk:
                    break
                total_bytes += len(chunk)
                if total_bytes > MAX_LOG_SNAPSHOT_BYTES:
                    allowed = len(chunk) - (total_bytes - MAX_LOG_SNAPSHOT_BYTES)
                    if allowed > 0:
                        parsed.extend(parser.feed(chunk[:allowed]))
                    truncated = True
                    break
                parsed.extend(parser.feed(chunk))
            if not truncated:
                parsed.extend(parser.flush())
        except WorkspaceContainerError:
            raise
        except (OSError, http.client.HTTPException, TimeoutError) as exc:
            raise WorkspaceContainerError("Docker 日志快照读取失败") from exc
        finally:
            connection.close()

        return ContainerLogSnapshot(
            records=[
                ContainerLogRecord(
                    stream=record.stream,
                    content=record.content,
                    timestamp=record.timestamp,
                )
                for record in parsed
            ],
            truncated=truncated,
        )

    def bulk_action(
        self,
        workspace_id: str,
        project_ids: set[str],
        *,
        action: str,
    ) -> tuple[int, list[str]]:
        if action not in {"restart", "stop"}:
            raise WorkspaceContainerError("不支持的容器批量操作")
        containers = [
            container
            for container in self.list_containers(workspace_id)
            if container.project_id in project_ids
        ]
        if not containers:
            return 0, []

        failures: list[str] = []
        worker_count = min(MAX_CONTAINER_ACTION_WORKERS, len(containers))
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = {
                executor.submit(self._control_container, container.id, action): container.name
                for container in containers
            }
            for future in as_completed(futures):
                container_name = futures[future]
                try:
                    error = future.result()
                except Exception:
                    error = "Docker 请求失败"
                if error:
                    failures.append(f"{container_name}：{error}")
        return len(containers), sorted(failures, key=str.casefold)

    def _control_container(self, container_id: str, action: str) -> str | None:
        if not CONTAINER_ID_PATTERN.fullmatch(container_id):
            return "容器 ID 不正确"
        endpoint = "restart" if action == "restart" else "stop"
        connection = self._connection(timeout=20)
        try:
            connection.request(
                "POST",
                f"/containers/{quote(container_id, safe='')}/{endpoint}?t=10",
                headers={"Accept": "application/json"},
            )
            response = connection.getresponse()
            response.read(MAX_DOCKER_RESPONSE_BYTES + 1)
        except (OSError, http.client.HTTPException, TimeoutError):
            return "Docker 请求失败"
        finally:
            connection.close()
        if response.status in {204, 304}:
            return None
        if response.status == 404:
            return "容器不存在"
        return f"Docker 返回状态 {response.status}"

    def _log_event_stream(
        self,
        connection: http.client.HTTPConnection,
        response: http.client.HTTPResponse,
        *,
        tty: bool,
    ) -> Iterator[str]:
        queue: Queue[_LogRecord | Exception | None] = Queue(maxsize=512)
        stopped = threading.Event()

        def enqueue(item: _LogRecord | Exception | None) -> bool:
            while not stopped.is_set():
                try:
                    queue.put(item, timeout=0.5)
                    return True
                except Full:
                    continue
            return False

        def read_logs() -> None:
            parser = _DockerLogParser(tty=tty)
            read_chunk = response.read1 if hasattr(response, "read1") else response.read
            try:
                while not stopped.is_set():
                    chunk = read_chunk(16_384)
                    if not chunk:
                        break
                    for record in parser.feed(chunk):
                        if not enqueue(record):
                            return
                for record in parser.flush():
                    if not enqueue(record):
                        return
                enqueue(None)
            except Exception as exc:  # The generator reports Docker disconnects to SSE.
                enqueue(exc)

        reader = threading.Thread(target=read_logs, name="docker-log-stream", daemon=True)
        reader.start()
        try:
            yield _sse_event("ready", {"connected": True})
            while True:
                try:
                    item = queue.get(timeout=LOG_HEARTBEAT_SECONDS)
                except Empty:
                    yield ": heartbeat\n\n"
                    continue
                if item is None:
                    yield _sse_event("end", {"reason": "container-log-stream-ended"})
                    return
                if isinstance(item, Exception):
                    yield _sse_event("stream-error", {"message": "Docker 日志流已中断"})
                    return
                payload = {
                    "stream": item.stream,
                    "content": item.content,
                    "timestamp": item.timestamp,
                }
                yield _sse_event("log", payload, event_id=item.timestamp)
        finally:
            stopped.set()
            active_socket = getattr(connection, "sock", None)
            if active_socket is not None:
                try:
                    active_socket.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
            reader.join(timeout=1)
            connection.close()

    def _ensure_socket(self) -> None:
        if self._uses_docker_socket and not self._docker_socket.exists():
            raise WorkspaceContainerError("Docker Socket 当前不可用")

    def _validated_container_config(
        self,
        workspace_id: str,
        container_id: str,
    ) -> dict[str, object]:
        self._ensure_socket()
        if not CONTAINER_ID_PATTERN.fullmatch(container_id):
            raise WorkspaceContainerError("容器不存在")
        document = self._read_json(
            f"/containers/{quote(container_id, safe='')}/json",
            "Docker 容器信息读取失败",
            missing_message="容器不存在",
        )
        if not isinstance(document, dict):
            raise WorkspaceContainerError("Docker 返回了无效的容器信息")
        config = document.get("Config")
        config = config if isinstance(config, dict) else {}
        labels = config.get("Labels")
        labels = labels if isinstance(labels, dict) else {}
        if labels.get("runtime-runner.workspace-id") != workspace_id:
            raise WorkspaceContainerError("容器不属于当前工作空间")
        return config

    def _connection(
        self,
        *,
        streaming: bool = False,
        timeout: float | None = None,
    ) -> http.client.HTTPConnection:
        if self._connection_factory is not None:
            return self._connection_factory()
        return _UnixHTTPConnection(
            self._docker_socket,
            timeout=None if streaming else (timeout if timeout is not None else 5),
        )

    def _read_json(
        self,
        path: str,
        error_message: str,
        *,
        missing_message: str | None = None,
    ) -> object:
        connection = self._connection()
        try:
            connection.request("GET", path, headers={"Accept": "application/json"})
            response = connection.getresponse()
            payload = response.read(MAX_DOCKER_RESPONSE_BYTES + 1)
        except (OSError, http.client.HTTPException, TimeoutError) as exc:
            raise WorkspaceContainerError(error_message) from exc
        finally:
            connection.close()
        if response.status == 404 and missing_message:
            raise WorkspaceContainerError(missing_message)
        if response.status != 200:
            raise WorkspaceContainerError(error_message)
        if len(payload) > MAX_DOCKER_RESPONSE_BYTES:
            raise WorkspaceContainerError("Docker 响应过大")
        try:
            return json.loads(payload)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise WorkspaceContainerError("Docker 返回了无效的 JSON") from exc


def _parse_log_record(stream: str, line: str) -> _LogRecord:
    cleaned = ANSI_ESCAPE_PATTERN.sub("", line)
    match = TIMESTAMP_PATTERN.match(cleaned)
    timestamp = match.group("timestamp") if match else None
    content = cleaned[match.end() :] if match else cleaned
    return _LogRecord(stream=stream, content=content, timestamp=timestamp)


def _sse_event(event: str, data: object, *, event_id: str | None = None) -> str:
    fields = []
    if event_id:
        fields.append(f"id: {event_id}")
    fields.append(f"event: {event}")
    encoded = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    fields.extend(f"data: {line}" for line in encoded.splitlines() or [""])
    return "\n".join(fields) + "\n\n"


def _container_summary(
    item: dict[str, object],
    project_names: Mapping[str, str],
    project_kinds: Mapping[str, str],
) -> WorkspaceContainerSummary:
    labels = item.get("Labels") if isinstance(item.get("Labels"), dict) else {}
    project_id = _optional_string(labels.get("runtime-runner.project-id"))
    status = _optional_string(item.get("Status")) or "未知状态"
    names = item.get("Names") if isinstance(item.get("Names"), list) else []
    name = next(
        (value.removeprefix("/") for value in names if isinstance(value, str) and value),
        _optional_string(item.get("Id")) or "unknown",
    )
    return WorkspaceContainerSummary(
        id=_optional_string(item.get("Id")) or name,
        name=name,
        image=_optional_string(item.get("Image")) or "未知镜像",
        state=_optional_string(item.get("State")) or "unknown",
        status=status,
        health=_health_from_status(status),
        project_id=project_id,
        project_name=project_names.get(project_id) if project_id else None,
        project_kind=project_kinds.get(project_id) if project_id else None,
        mode=_optional_string(labels.get("runtime-runner.mode")),
        operation_id=_optional_string(labels.get("runtime-runner.operation-id")),
        ports=_ports(item.get("Ports")),
    )


def _ports(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    ports: list[str] = []
    for item in value:
        if not isinstance(item, dict) or not isinstance(item.get("PrivatePort"), int):
            continue
        protocol = _optional_string(item.get("Type")) or "tcp"
        private = f"{item['PrivatePort']}/{protocol}"
        public = item.get("PublicPort")
        ip_address = _optional_string(item.get("IP"))
        ports.append(
            f"{ip_address or '0.0.0.0'}:{public} -> {private}"
            if isinstance(public, int)
            else private
        )
    return ports


def _health_from_status(status: str) -> str | None:
    lowered = status.casefold()
    for value in ("healthy", "unhealthy", "starting"):
        if f"({value})" in lowered:
            return value
    return None


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None
