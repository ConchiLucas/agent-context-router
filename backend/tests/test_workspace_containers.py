import json
import threading
from pathlib import Path
from queue import Queue
from urllib.parse import parse_qs, urlparse

import pytest

from context_router.services.workspace_containers import (
    WorkspaceContainerError,
    WorkspaceContainerService,
    _DockerLogParser,
)


class _Response:
    status = 200

    def __init__(self, document: object) -> None:
        self._payload = json.dumps(document).encode()

    def read(self, _: int) -> bytes:
        return self._payload


class _Connection:
    def __init__(self, document: object) -> None:
        self._document = document
        self.path = ""
        self.closed = False

    def request(self, method: str, path: str, *, headers: dict[str, str]) -> None:
        assert method == "GET"
        assert headers == {"Accept": "application/json"}
        self.path = path

    def getresponse(self) -> _Response:
        return _Response(self._document)

    def close(self) -> None:
        self.closed = True


class _StreamingResponse:
    status = 200

    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = iter(chunks)

    def read(self, _: int) -> bytes:
        return next(self._chunks, b"")


class _StreamingConnection:
    def __init__(self, chunks: list[bytes]) -> None:
        self.response = _StreamingResponse(chunks)
        self.path = ""
        self.headers: dict[str, str] = {}
        self.closed = False

    def request(self, method: str, path: str, *, headers: dict[str, str]) -> None:
        assert method == "GET"
        self.path = path
        self.headers = headers

    def getresponse(self) -> _StreamingResponse:
        return self.response

    def close(self) -> None:
        self.closed = True


class _ActionResponse:
    def __init__(self, status: int) -> None:
        self.status = status

    def read(self, _: int) -> bytes:
        return b""


class _ActionConnection:
    def __init__(self, status: int = 204) -> None:
        self.response = _ActionResponse(status)
        self.path = ""
        self.closed = False

    def request(self, method: str, path: str, *, headers: dict[str, str]) -> None:
        assert method == "POST"
        assert headers == {"Accept": "application/json"}
        self.path = path

    def getresponse(self) -> _ActionResponse:
        return self.response

    def close(self) -> None:
        self.closed = True


class _BlockingResponse:
    def __init__(self, released: threading.Event) -> None:
        self._released = released

    def read1(self, _: int) -> bytes:
        self._released.wait(timeout=2)
        return b""


class _ShutdownSocket:
    def __init__(self, released: threading.Event) -> None:
        self._released = released
        self.shutdown_called = False

    def shutdown(self, _: int) -> None:
        self.shutdown_called = True
        self._released.set()


class _BlockingConnection:
    def __init__(self, released: threading.Event) -> None:
        self.sock = _ShutdownSocket(released)
        self.closed = False

    def close(self) -> None:
        self.closed = True


def test_list_containers_filters_workspace_and_formats_results(tmp_path: Path) -> None:
    connection = _Connection(
        [
            {
                "Id": "stopped-id",
                "Names": ["/stopped-api"],
                "Image": "api:old",
                "State": "exited",
                "Status": "Exited (0) 2 hours ago",
                "Labels": {
                    "runtime-runner.project-id": "project-api",
                    "runtime-runner.mode": "full",
                },
                "Ports": [],
            },
            {
                "Id": "running-id",
                "Names": ["/running-web"],
                "Image": "web:latest",
                "State": "running",
                "Status": "Up 5 minutes (healthy)",
                "Labels": {
                    "runtime-runner.project-id": "project-web",
                    "runtime-runner.operation-id": "operation-1",
                },
                "Ports": [
                    {
                        "IP": "127.0.0.1",
                        "PrivatePort": 3000,
                        "PublicPort": 49175,
                        "Type": "tcp",
                    }
                ],
            },
        ]
    )
    service = WorkspaceContainerService(
        tmp_path / "unused.sock",
        connection_factory=lambda: connection,  # type: ignore[arg-type]
    )

    result = service.list_containers(
        "workspace-1",
        project_names={"project-web": "Web 项目"},
        project_kinds={"project-web": "frontend", "project-api": "backend"},
    )

    query = parse_qs(urlparse(connection.path).query)
    assert query["all"] == ["1"]
    assert json.loads(query["filters"][0]) == {"label": ["runtime-runner.workspace-id=workspace-1"]}
    assert connection.closed is True
    assert [container.id for container in result] == ["running-id", "stopped-id"]
    assert result[0].name == "running-web"
    assert result[0].project_name == "Web 项目"
    assert result[0].project_kind == "frontend"
    assert result[0].health == "healthy"
    assert result[0].ports == ["127.0.0.1:49175 -> 3000/tcp"]
    assert result[1].project_name is None
    assert result[1].project_kind == "backend"


def test_list_containers_reports_missing_docker_socket(tmp_path: Path) -> None:
    service = WorkspaceContainerService(tmp_path / "missing.sock")

    with pytest.raises(WorkspaceContainerError, match="Docker Socket 当前不可用"):
        service.list_containers("workspace-1")


def test_docker_log_parser_decodes_fragmented_multiplexed_frames() -> None:
    payload = "2026-08-09T10:20:30.123456789Z \x1b[31m服务启动\x1b[0m\n".encode()
    frame = bytes([2, 0, 0, 0]) + len(payload).to_bytes(4, "big") + payload
    parser = _DockerLogParser(tty=False)

    assert parser.feed(frame[:11]) == []
    records = parser.feed(frame[11:])

    assert len(records) == 1
    assert records[0].stream == "stderr"
    assert records[0].timestamp == "2026-08-09T10:20:30.123456789Z"
    assert records[0].content == "服务启动"


def test_stream_logs_validates_workspace_and_emits_sse(tmp_path: Path) -> None:
    container_id = "a" * 64
    inspect_connection = _Connection(
        {
            "Config": {
                "Tty": False,
                "Labels": {"runtime-runner.workspace-id": "workspace-1"},
            }
        }
    )
    payload = b"2026-08-09T10:20:30.123456789Z ready\n"
    frame = bytes([1, 0, 0, 0]) + len(payload).to_bytes(4, "big") + payload
    log_connection = _StreamingConnection([frame])
    connections = iter([inspect_connection, log_connection])
    service = WorkspaceContainerService(
        tmp_path / "unused.sock",
        connection_factory=lambda: next(connections),  # type: ignore[arg-type]
    )

    events = list(
        service.stream_logs(
            "workspace-1",
            container_id,
            tail=20,
            since="2026-08-09T10:00:00Z",
        )
    )

    assert inspect_connection.path == f"/containers/{container_id}/json"
    query = parse_qs(urlparse(log_connection.path).query)
    assert query["follow"] == ["1"]
    assert query["tail"] == ["20"]
    assert query["since"] == ["2026-08-09T10:00:00Z"]
    assert log_connection.headers == {"Accept": "application/octet-stream"}
    assert log_connection.closed is True
    assert "event: ready" in events[0]
    assert "event: log" in events[1]
    assert '"stream":"stdout"' in events[1]
    assert '"content":"ready"' in events[1]
    assert "event: end" in events[2]


def test_stream_logs_rejects_container_from_another_workspace(tmp_path: Path) -> None:
    inspect_connection = _Connection(
        {
            "Config": {
                "Tty": False,
                "Labels": {"runtime-runner.workspace-id": "workspace-2"},
            }
        }
    )
    service = WorkspaceContainerService(
        tmp_path / "unused.sock",
        connection_factory=lambda: inspect_connection,  # type: ignore[arg-type]
    )

    with pytest.raises(WorkspaceContainerError, match="容器不属于当前工作空间"):
        service.stream_logs("workspace-1", "b" * 64)


def test_closing_log_stream_interrupts_blocked_docker_read(tmp_path: Path) -> None:
    released = threading.Event()
    connection = _BlockingConnection(released)
    service = WorkspaceContainerService(tmp_path / "unused.sock", connection_factory=lambda: None)  # type: ignore[arg-type,return-value]
    events = service._log_event_stream(  # noqa: SLF001
        connection,  # type: ignore[arg-type]
        _BlockingResponse(released),  # type: ignore[arg-type]
        tty=True,
    )

    assert "event: ready" in next(events)
    events.close()

    assert connection.sock.shutdown_called is True
    assert connection.closed is True
    assert released.is_set()


def test_bulk_action_controls_only_selected_project_containers(tmp_path: Path) -> None:
    list_connection = _Connection(
        [
            {
                "Id": "a" * 64,
                "Names": ["/backend-api"],
                "Image": "api:latest",
                "State": "running",
                "Status": "Up 1 hour",
                "Labels": {"runtime-runner.project-id": "backend-project"},
                "Ports": [],
            },
            {
                "Id": "b" * 64,
                "Names": ["/frontend-ui"],
                "Image": "ui:latest",
                "State": "running",
                "Status": "Up 1 hour",
                "Labels": {"runtime-runner.project-id": "frontend-project"},
                "Ports": [],
            },
        ]
    )
    action_connection = _ActionConnection()
    connections: Queue[object] = Queue()
    connections.put(list_connection)
    connections.put(action_connection)
    service = WorkspaceContainerService(
        tmp_path / "unused.sock",
        connection_factory=connections.get,  # type: ignore[arg-type]
    )

    target_count, failures = service.bulk_action(
        "workspace-1",
        {"backend-project"},
        action="restart",
    )

    assert target_count == 1
    assert failures == []
    assert action_connection.path == f"/containers/{'a' * 64}/restart?t=10"
    assert action_connection.closed is True


def test_container_action_reports_docker_failure(tmp_path: Path) -> None:
    connection = _ActionConnection(status=500)
    service = WorkspaceContainerService(
        tmp_path / "unused.sock",
        connection_factory=lambda: connection,  # type: ignore[arg-type]
    )

    error = service._control_container("c" * 64, "stop")  # noqa: SLF001

    assert error == "Docker 返回状态 500"
    assert connection.path == f"/containers/{'c' * 64}/stop?t=10"
    assert connection.closed is True
