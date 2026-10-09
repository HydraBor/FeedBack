"""Background lifecycle must survive launchers and preserve other checkouts."""
import subprocess
import shutil
import socket
import signal
import os
import sys
import time
from contextlib import contextmanager
from pathlib import Path
import pytest

from scripts.service import is_service, start_project, status, stop_project


def write_app(root, delay=0):
    backend = root / "backend"
    backend.mkdir(parents=True)
    (backend / "__init__.py").write_text("")
    (backend / "app.py").write_text(f'''import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
@asynccontextmanager
async def lifespan(app):
    Path("started").touch()
    yield
    await asyncio.sleep({delay})
    Path("clean-shutdown").touch()
app = FastAPI(lifespan=lifespan)
@app.get("/api/health")
async def health():
    return {{"status": "ok"}}
''')


@contextmanager
def server(root, delay=0, port=0):
    write_app(root, delay)
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "backend.app:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=root, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 10
        while not (root / "started").exists():
            assert process.poll() is None, "isolated service did not start"
            assert time.monotonic() < deadline, "isolated service startup timed out"
            time.sleep(0.02)
        yield process
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def test_matches_only_actual_service_entrypoints():
    assert is_service(["python3", "-m", "uvicorn", "backend.app:app", "--port", "8766"])
    assert is_service(["/app/.venv/bin/python", "/app/.venv/bin/uvicorn", "backend.app:app"])
    assert is_service(["uvicorn", "backend.app:app"])
    assert not is_service(["python", "unrelated.py", "-m", "uvicorn", "backend.app:app"])
    assert not is_service(["python", "-m", "uvicorn", "other.app:app"])


def test_graceful_shutdown_is_scoped_to_checkout_and_repeatable(tmp_path):
    selected, other = tmp_path / "selected", tmp_path / "other"
    with server(selected) as selected_process, server(other) as other_process:
        assert stop_project(selected, timeout=10) == 0
        assert selected_process.wait(timeout=2) in (0, -signal.SIGTERM)
        assert (selected / "clean-shutdown").exists()
        assert other_process.poll() is None
        assert stop_project(selected, timeout=1) == 0
        assert stop_project(other, timeout=10) == 0


def test_timeout_does_not_force_terminate_pending_cleanup(tmp_path):
    root = tmp_path / "slow"
    with server(root, delay=0.6) as process:
        assert stop_project(root, timeout=0.1) == 1
        assert process.poll() is None
        assert process.wait(timeout=5) in (0, -signal.SIGTERM)
        assert (root / "clean-shutdown").exists()


def test_start_requires_explicit_transition_from_older_foreground_service(tmp_path):
    root = tmp_path / "foreground"
    with server(root) as process:
        with pytest.raises(RuntimeError, match="older foreground service"):
            start_project(root, port=free_port())
        assert process.poll() is None
        assert status(root)["managed"] is False


def free_port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def test_background_start_survives_launcher_exit_and_is_repeatable(tmp_path):
    root = tmp_path / "project with spaces"
    write_app(root)
    (root / "scripts").mkdir()
    shutil.copyfile(Path(__file__).resolve().parents[1] / "scripts/service.py", root / "scripts/service.py")
    try:
        result = subprocess.run(
            [sys.executable, "scripts/service.py", "start", "--port", str(free_port())],
            cwd=root, capture_output=True, text=True, timeout=15,
        )
        assert result.returncode == 0, result.stderr
        current = status(root)
        assert current["status"] == "running" and current["managed"]
        assert os.getsid(current["pid"]) == current["pid"]
        assert (Path("/proc") / str(current["pid"]) / "fd/0").readlink() == Path("/dev/null")
        assert (Path("/proc") / str(current["pid"]) / "fd/1").readlink() == root / ".run/service.log"
        assert start_project(root, port=current["port"]) is None
        assert status(root)["pid"] == current["pid"]
        assert stop_project(root, timeout=10) == 0
        assert (root / "clean-shutdown").exists()
        assert status(root)["status"] == "stopped"
        original_log = (root / ".run/service.log").read_bytes()
        restarted = start_project(root, port=current["port"])
        assert restarted is not None and restarted.pid != current["pid"]
        assert (root / ".run/service.previous.log").read_bytes() == original_log
        assert stop_project(root, timeout=10) == 0
        restarted.wait(timeout=2)
    finally:
        stop_project(root, timeout=10)


def test_busy_port_does_not_report_unrelated_healthy_service_as_started(tmp_path):
    other, selected = tmp_path / "other", tmp_path / "selected"
    port = free_port()
    write_app(selected)
    with server(other, port=port) as process:
        with pytest.raises(RuntimeError, match="Startup failed"):
            start_project(selected, port=port, timeout=10)
        assert process.poll() is None
        assert status(selected)["status"] == "stopped"
