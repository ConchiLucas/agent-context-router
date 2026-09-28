#!/usr/bin/env python3
"""Run a command once, draining stdout/stderr into strictly bounded local logs."""

import argparse
import fcntl
import os
from pathlib import Path
import selectors
import signal
import subprocess
import time

MAX_BYTES = 10 * 1024 * 1024
BACKUPS = 3


class BoundedLog:
    def __init__(self, path):
        self.path = Path(path)
        # Normalize existing oversized logs without reading them into memory.
        for item in [self.path] + [Path(str(self.path) + f".{n}") for n in range(1, 4)]:
            if item.exists() and item.stat().st_size > MAX_BYTES:
                with item.open("r+b") as stream:
                    stream.truncate(MAX_BYTES)
        self.stream = self.path.open("ab", buffering=0)
        os.chmod(self.path, 0o600)
        self.size = self.path.stat().st_size

    def rotate(self):
        self.stream.close()
        oldest = Path(str(self.path) + f".{BACKUPS}")
        if oldest.exists():
            oldest.unlink()
        for n in range(BACKUPS - 1, 0, -1):
            source = Path(str(self.path) + f".{n}")
            if source.exists():
                source.replace(str(self.path) + f".{n + 1}")
        self.path.replace(str(self.path) + ".1")
        self.stream = self.path.open("ab", buffering=0)
        os.chmod(self.path, 0o600)
        self.size = 0

    def write(self, data):
        while data:
            if self.size == MAX_BYTES:
                self.rotate()
            count = min(len(data), MAX_BYTES - self.size)
            written = self.stream.write(data[:count])
            self.size += written
            data = data[written:]

    def close(self):
        self.stream.close()


def run(prefix, command):
    os.umask(0o077)
    # A duplicate manual/bootstrap invocation must not start a second process or
    # race rotation. The stable lock file intentionally survives process exit.
    with open(str(prefix) + ".log.lock", "a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 0
        logs = [
            BoundedLog(str(prefix) + suffix) for suffix in (".out.log", ".error.log")
        ]
        child = None
        deadline = None

        def stop(signum, _frame):
            nonlocal deadline
            deadline = time.monotonic() + 3
            if child is not None:
                try:
                    os.killpg(child.pid, signum)
                except ProcessLookupError:
                    pass

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        try:
            child = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
            )
            with selectors.DefaultSelector() as selector:
                for pipe, log in zip((child.stdout, child.stderr), logs):
                    selector.register(pipe, selectors.EVENT_READ, log)
                while selector.get_map() or child.poll() is None:
                    if deadline is not None and time.monotonic() >= deadline:
                        try:
                            os.killpg(child.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                        break
                    for key, _ in selector.select(timeout=0.2):
                        data = os.read(key.fileobj.fileno(), 65536)
                        if data:
                            key.data.write(data)
                        else:
                            selector.unregister(key.fileobj)
                            key.fileobj.close()
            result = child.wait()
            if result:
                logs[1].write(
                    f"\nCommand exited with status {result}; no automatic retry.\n".encode()
                )
            return result if result >= 0 else 128 - result
        except OSError:
            # Disk/logging failure is fail-closed: never fall back to unlimited
            # launchd stderr output or repeatedly attempt a failing write.
            if child is not None:
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                child.wait()
            try:
                logs[1].write(b"Command or log I/O failed; no automatic retry.\n")
            except OSError:
                pass
            return 74
        finally:
            for log in logs:
                log.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log-prefix", type=Path, required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if (
        not args.log_prefix.is_absolute()
        or not command
        or not Path(command[0]).is_absolute()
    ):
        parser.error("log prefix and executable must be absolute paths")
    raise SystemExit(run(args.log_prefix, command))
