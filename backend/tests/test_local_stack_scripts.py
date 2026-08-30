from pathlib import Path


def test_manual_stack_scripts_have_safe_lifecycle_contract() -> None:
    root = Path(__file__).parents[2]
    start = (root / "scripts/start-local-stack.sh").read_text()
    stop = (root / "scripts/stop-local-stack.sh").read_text()
    status = (root / "scripts/status-local-stack.sh").read_text()

    assert "docker compose up -d" in start
    assert "runner.token" in start and "chmod 600" in start
    assert "context_router_host_runner.py" in start
    assert "kill -TERM" in stop and "runner.pid" in stop
    assert "docker compose ps" in status and "runner.pid" in status
    assert "launchctl" not in start + stop + status


def test_native_stack_scripts_keep_workspace_docker_separate() -> None:
    root = Path(__file__).parents[2]
    start = (root / "scripts/start-native-stack.sh").read_text()
    stop = (root / "scripts/stop-native-stack.sh").read_text()
    status = (root / "scripts/status-native-stack.sh").read_text()
    common = (root / "scripts/native-common.sh").read_text()
    service = (root / "scripts/run-native-service.sh").read_text()

    assert "uvicorn context_router.main:create_app" in service
    assert "npm run build:native" in start
    assert "npm run build:native" in start
    assert "launchctl submit" in start
    assert "node_modules/next/dist/bin/next start" in service
    assert "context_router_host_runner.py" in start
    assert "docker compose up" not in start
    assert "docker compose down" not in stop
    assert "Docker Engine" in status
    assert "CONTEXT_ROUTER_RUNTIME_MODE=native" in common
    assert "native_require_node22" in common
    assert "NO_PROXY" in common and "127.0.0.1" in common
    assert "launchctl remove" in common
