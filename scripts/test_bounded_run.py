"""Isolated stdlib tests; launchd test installs only a temporary, unique agent."""

import importlib.util
import os
from pathlib import Path
import plistlib
import subprocess
import sys
import tempfile
import time
import unittest
import uuid

SCRIPT = Path(__file__).with_name("bounded_run.py")
spec = importlib.util.spec_from_file_location("bounded_run", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class BoundedRunTests(unittest.TestCase):
    def test_login_plists_have_no_restart_triggers(self):
        for name in ("login", "vpn-relay"):
            config = plistlib.loads(
                SCRIPT.parent.parent.joinpath(
                    f"launchd/com.conchi.agent-context-router.{name}.plist"
                ).read_bytes()
            )
            self.assertIs(config["RunAtLoad"], True)
            self.assertIs(config["KeepAlive"], False)
            for key in (
                "StartInterval",
                "StartCalendarInterval",
                "WatchPaths",
                "QueueDirectories",
            ):
                self.assertNotIn(key, config)
            self.assertEqual(config["StandardOutPath"], "/dev/null")
            self.assertEqual(config["StandardErrorPath"], "/dev/null")
            self.assertTrue(Path(config["ProgramArguments"][0]).is_absolute())
            self.assertIn("/opt/homebrew/bin", config["EnvironmentVariables"]["PATH"])

    def test_existing_oversized_log_is_bounded(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "start.error.log"
            with path.open("wb") as stream:
                stream.truncate(2 * module.MAX_BYTES)
            log = module.BoundedLog(path)
            log.write(b"new")
            log.close()
            self.assertLessEqual(path.stat().st_size, module.MAX_BYTES)
            self.assertEqual(Path(str(path) + ".1").stat().st_size, module.MAX_BYTES)

    def test_rotation_and_large_newline_free_stream(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "start.error.log"
            log = module.BoundedLog(path)
            block = b"x" * 65536
            for _ in range(6 * 160):  # 60 MiB, including several old-log deletions
                log.write(block)
            log.write(b"latest")
            log.close()
            files = list(Path(directory).glob("*.log*"))
            self.assertEqual(len(files), 4)
            self.assertTrue(
                all(item.stat().st_size <= module.MAX_BYTES for item in files)
            )
            self.assertLessEqual(
                sum(item.stat().st_size for item in files), 4 * module.MAX_BYTES
            )
            self.assertEqual(path.read_bytes(), b"latest")

    def test_success_and_failure_exit_codes(self):
        with tempfile.TemporaryDirectory() as directory:
            prefix = Path(directory) / "start"
            for status in (0, 23):
                result = subprocess.run(
                    [
                        sys.executable,
                        str(SCRIPT),
                        "--log-prefix",
                        str(prefix),
                        "--",
                        "/bin/sh",
                        "-c",
                        f"echo output; echo error >&2; exit {status}",
                    ]
                )
                self.assertEqual(result.returncode, status)
            self.assertIn(b"error", prefix.with_suffix(".error.log").read_bytes())
            self.assertIn(b"output", prefix.with_suffix(".out.log").read_bytes())

    def test_both_streams_are_bounded_in_real_process(self):
        with tempfile.TemporaryDirectory() as directory:
            prefix = Path(directory) / "start"
            code = "import os; [(os.write(1,b'a'*65536),os.write(2,b'b'*65536)) for _ in range(850)]"
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--log-prefix",
                    str(prefix),
                    "--",
                    sys.executable,
                    "-c",
                    code,
                ],
                timeout=30,
            )
            self.assertEqual(result.returncode, 0)
            for stream in ("out", "error"):
                files = list(Path(directory).glob(f"start.{stream}.log*"))
                self.assertEqual(len(files), 4)
                self.assertTrue(
                    all(p.stat().st_size <= module.MAX_BYTES for p in files)
                )

    def test_signal_stops_child(self):
        with tempfile.TemporaryDirectory() as directory:
            prefix = Path(directory) / "start"
            process = subprocess.Popen(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--log-prefix",
                    str(prefix),
                    "--",
                    sys.executable,
                    "-u",
                    "-c",
                    "import os,time; print(os.getpid()); time.sleep(90)",
                ]
            )
            try:
                output = prefix.with_suffix(".out.log")
                for _ in range(100):
                    if output.exists() and output.stat().st_size:
                        break
                    time.sleep(0.05)
                child_pid = int(output.read_text())
                process.terminate()
                process.wait(timeout=8)
                with self.assertRaises(ProcessLookupError):
                    os.kill(child_pid, 0)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()

    @unittest.skipUnless(sys.platform == "darwin", "requires a macOS login session")
    def test_launchagent_failure_runs_only_once(self):
        label = "com.conchi.agent-context-router.test-" + uuid.uuid4().hex
        target = f"gui/{os.getuid()}/{label}"
        plist_path = Path.home() / "Library/LaunchAgents" / (label + ".plist")
        with tempfile.TemporaryDirectory() as directory:
            # Runtime fixture, isolated from production scripts and services.
            failing = Path(directory) / "start.sh"
            failing.write_text("#!/bin/sh\necho intentional-failure >&2\nexit 23\n")
            prefix = failing.with_suffix("")
            config = plistlib.loads(
                SCRIPT.parent.parent.joinpath(
                    "launchd/com.conchi.agent-context-router.login.plist"
                ).read_bytes()
            )
            config["Label"] = label
            config["ProgramArguments"] = [
                "/usr/bin/python3",
                str(SCRIPT),
                "--log-prefix",
                str(prefix),
                "--",
                "/bin/sh",
                str(failing),
            ]
            plist_path.write_bytes(plistlib.dumps(config))
            try:
                subprocess.run(
                    ["launchctl", "bootstrap", f"gui/{os.getuid()}", str(plist_path)],
                    check=True,
                )
                for _ in range(50):
                    result = subprocess.check_output(
                        ["launchctl", "print", target], text=True
                    )
                    if "last exit code = 23" in result:
                        break
                    time.sleep(0.2)
                self.assertIn("last exit code = 23", result)
                error = prefix.with_suffix(".error.log")
                size = error.stat().st_size
                # Longer than launchd's usual 10-second throttle interval.
                time.sleep(25)
                result = subprocess.check_output(
                    ["launchctl", "print", target], text=True
                )
                self.assertIn("runs = 1", result)
                self.assertIn("last exit code = 23", result)
                self.assertEqual(error.stat().st_size, size)
                self.assertEqual(error.parent, failing.parent)
                self.assertEqual(error.read_text().count("intentional-failure"), 1)
                print(
                    "LaunchAgent failure: runs=1, exit=23, log unchanged after 25s",
                    flush=True,
                )
            finally:
                subprocess.run(["launchctl", "bootout", target], capture_output=True)
                plist_path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
