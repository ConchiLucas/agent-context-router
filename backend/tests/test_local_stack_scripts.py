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
