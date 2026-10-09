"""Start, inspect and gracefully stop this checkout's detached feedback service."""
import argparse
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import select
import signal
import subprocess
import sys
import time
from urllib.request import build_opener, ProxyHandler

ROOT = Path(__file__).resolve().parents[1]


def is_service(argv):
    return (
        len(argv) >= 4 and Path(argv[0]).name.startswith("python")
        and argv[1:4] == ["-m", "uvicorn", "backend.app:app"]
    ) or (
        len(argv) >= 2 and Path(argv[0]).name == "uvicorn" and argv[1] == "backend.app:app"
    ) or (
        len(argv) >= 3 and Path(argv[0]).name.startswith("python")
        and Path(argv[1]).name == "uvicorn" and argv[2] == "backend.app:app"
    )


def identity(pid, root):
    try:
        proc = Path("/proc") / str(pid)
        if (proc / "cwd").resolve(strict=True) != Path(root).resolve():
            return None
        argv = (proc / "cmdline").read_bytes().decode(errors="replace").rstrip("\0").split("\0")
        if not is_service(argv):
            return None
        start = (proc / "stat").read_text().rsplit(") ", 1)[1].split()[19]
        port = 8000
        for i, arg in enumerate(argv):
            if arg == "--port" and i + 1 < len(argv):
                port = int(argv[i + 1])
            elif arg.startswith("--port="):
                port = int(arg.split("=", 1)[1])
        return {"pid": pid, "start": start, "port": port}
    except (OSError, IndexError, ValueError):
        return None


def servers(root):
    return [value for proc in Path("/proc").iterdir() if proc.name.isdigit()
            for value in [identity(int(proc.name), root)] if value]


def state_dir(root):
    directory = Path(root) / ".run"
    directory.mkdir(mode=0o700, exist_ok=True)
    return directory


@contextmanager
def lifecycle_lock(root):
    with (state_dir(root) / "service.lock").open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def healthy(port):
    try:
        opener = build_opener(ProxyHandler({}))
        with opener.open(f"http://127.0.0.1:{port}/api/health", timeout=0.5) as response:
            return response.status == 200 and json.loads(response.read(4096)).get("status") == "ok"
    except (OSError, ValueError):
        return False


def owns_port(pid, port):
    """Do not mistake an unrelated service on the requested port for our startup."""
    try:
        proc = Path("/proc") / str(pid)
        sockets = set()
        for fd in (proc / "fd").iterdir():
            try:
                target = str(fd.readlink())
            except FileNotFoundError:
                continue
            if target.startswith("socket:["):
                sockets.add(target.removeprefix("socket:[").removesuffix("]"))
        for line in (proc / "net/tcp").read_text().splitlines()[1:]:
            columns = line.split()
            if columns[3] == "0A" and int(columns[1].split(":")[1], 16) == port and columns[9] in sockets:
                return True
    except (OSError, IndexError, ValueError):
        pass
    return False


def status(root=ROOT):
    entries = servers(root)
    if not entries:
        return {"status": "stopped", "managed": False}
    try:
        saved = json.loads((Path(root) / ".run/state.json").read_text())
    except (OSError, ValueError):
        saved = {}
    selected = next((entry for entry in entries if entry == saved), entries[0])
    ready = owns_port(selected["pid"], selected["port"]) and healthy(selected["port"])
    return {**selected, "status": "running" if ready else "starting",
            "managed": selected == saved, "log": str(Path(root) / ".run/service.log") if selected == saved else None}


def start_project(root=ROOT, port=8765, timeout=20):
    root = Path(root).resolve()
    with lifecycle_lock(root):
        existing = status(root)
        if existing["status"] != "stopped":
            if not existing["managed"]:
                raise RuntimeError("An older foreground service is running. Stop it first, then start in background mode.")
            return None
        directory = state_dir(root)
        log = directory / "service.log"
        if log.exists():
            log.replace(directory / "service.previous.log")
        environment = os.environ.copy()
        environment["PATH"] = str(root / ".tools/node/bin") + os.pathsep + environment.get("PATH", "")
        environment["PYTHONUNBUFFERED"] = "1"
        with log.open("ab") as output:
            log.chmod(0o600)
            process = subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "backend.app:app", "--host", "127.0.0.1", "--port", str(port)],
                cwd=root, env=environment, stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        deadline = time.monotonic() + timeout
        current = identity(process.pid, root)
        # Popen may return just before the child executes the service command.
        while current is None and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.02)
            current = identity(process.pid, root)
        if current is None:
            if process.poll() is None:
                process.terminate()
            process.wait(timeout=5)
            raise RuntimeError("Could not identify the new service. Check .run/service.log.")
        metadata = directory / "state.json"
        metadata.write_text(json.dumps(current))
        metadata.chmod(0o600)
        while time.monotonic() < deadline:
            if process.poll() is not None:
                metadata.unlink(missing_ok=True)
                raise RuntimeError("Startup failed. Check .run/service.log (for example, the port may be occupied).")
            if owns_port(process.pid, port) and healthy(port):
                return process
            time.sleep(0.1)
        # A failed readiness check does not leave an unreported background server.
        try:
            handle = os.pidfd_open(process.pid)
            try:
                signal.pidfd_send_signal(handle, signal.SIGTERM)
            finally:
                os.close(handle)
        except ProcessLookupError:
            pass
        raise RuntimeError("Startup timed out. The service was asked to stop; check .run/service.log.")


def stop_project(root=ROOT, timeout=30):
    root = Path(root).resolve()
    handles = []
    with lifecycle_lock(root):
        try:
            for entry in servers(root):
                try:
                    handle = os.pidfd_open(entry["pid"])
                except ProcessLookupError:
                    continue
                if identity(entry["pid"], root) != entry:
                    os.close(handle)
                    continue
                handles.append(handle)
                try:
                    signal.pidfd_send_signal(handle, signal.SIGTERM)
                except ProcessLookupError:
                    pass
            if not handles:
                (state_dir(root) / "state.json").unlink(missing_ok=True)
                print("Project service is already stopped.")
                return 0
            print("Stopping project service; waiting for ongoing work to finish cleanup...", flush=True)
            pending = handles.copy()
            deadline = time.monotonic() + timeout
            while pending:
                exited, _, _ = select.select(pending, [], [], max(0, deadline - time.monotonic()))
                pending = [handle for handle in pending if handle not in exited]
                if pending and time.monotonic() >= deadline:
                    print("Graceful shutdown is still in progress. Wait and run the stop command again.")
                    return 1
            (state_dir(root) / "state.json").unlink(missing_ok=True)
            print("Project service stopped.")
            return 0
        finally:
            for handle in handles:
                os.close(handle)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("start", "stop", "status"))
    parser.add_argument("--port", type=int, default=int(os.getenv("FEEDBACK_PORT", "8765")))
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument("--json", action="store_true", help="Machine-readable status")
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535 or not 0 < args.timeout <= 300:
        parser.error("port must be 1024-65535; timeout must be greater than 0 and at most 300 seconds")
    try:
        if args.action == "stop":
            return stop_project(timeout=args.timeout)
        if args.action == "start":
            start_project(port=args.port, timeout=args.timeout)
        current = status()
        if args.json:
            print(json.dumps(current))
        elif current["status"] == "stopped":
            print("Project service is stopped.")
        else:
            print(f"Service {current['status']}: http://localhost:{current['port']}/ (PID {current['pid']})")
            if current["log"]:
                print("Log: " + current["log"])
            else:
                print("Older foreground service; use stop then start to switch to background mode.")
        return 1 if current["status"] == "stopped" else 0
    except (OSError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
