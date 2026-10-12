import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import process_control as pc


class _FakeProcess:
    def __init__(self, cmdline, running=True, vanish_on_cmdline=False):
        self._cmdline = cmdline
        self._running = running
        self._vanish_on_cmdline = vanish_on_cmdline

    def is_running(self):
        return self._running

    def cmdline(self):
        if self._vanish_on_cmdline:
            raise _FakePsutil.NoSuchProcess("gone")
        return self._cmdline


class _FakePsutil:
    """Minimal stand-in for the psutil module so tests never depend on real OS processes."""

    class NoSuchProcess(Exception):
        pass

    class AccessDenied(Exception):
        pass

    class ZombieProcess(Exception):
        pass

    def __init__(self, processes: dict):
        self._processes = processes  # pid -> _FakeProcess

    def Process(self, pid):
        if pid not in self._processes:
            raise self.NoSuchProcess(pid)
        return self._processes[pid]


class StalePidLockTests(unittest.TestCase):
    def test_stale_lock_from_a_crashed_process_is_cleaned_up(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock_path = Path(tmp) / "phonewatcher.lock"
            lock_path.write_text("4321", encoding="utf-8")
            fake_psutil = _FakePsutil(processes={})  # PID 4321 is gone

            pid = pc.get_running_pid(lock_path, psutil_module=fake_psutil)

            self.assertIsNone(pid)
            self.assertFalse(lock_path.exists())

    def test_lock_pointing_at_an_unrelated_reused_pid_is_treated_as_stale(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock_path = Path(tmp) / "phonewatcher.lock"
            lock_path.write_text("4321", encoding="utf-8")
            fake_psutil = _FakePsutil(processes={4321: _FakeProcess(cmdline=["C:\\Windows\\explorer.exe"])})

            pid = pc.get_running_pid(lock_path, psutil_module=fake_psutil)

            self.assertIsNone(pid)
            self.assertFalse(lock_path.exists())

    def test_lock_pointing_at_a_dead_process_object_is_treated_as_stale(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock_path = Path(tmp) / "phonewatcher.lock"
            lock_path.write_text("4321", encoding="utf-8")
            fake_psutil = _FakePsutil(
                processes={4321: _FakeProcess(cmdline=["pythonw.exe", "main.py"], running=False)}
            )

            pid = pc.get_running_pid(lock_path, psutil_module=fake_psutil)

            self.assertIsNone(pid)
            self.assertFalse(lock_path.exists())

    def test_lock_pointing_at_a_live_matching_process_is_kept(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock_path = Path(tmp) / "phonewatcher.lock"
            lock_path.write_text("4321", encoding="utf-8")
            fake_psutil = _FakePsutil(
                processes={4321: _FakeProcess(cmdline=["pythonw.exe", "D:\\phoneWatcher\\main.py"])}
            )

            pid = pc.get_running_pid(lock_path, psutil_module=fake_psutil)

            self.assertEqual(pid, 4321)
            self.assertTrue(lock_path.exists())

    def test_missing_lock_file_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock_path = Path(tmp) / "phonewatcher.lock"
            fake_psutil = _FakePsutil(processes={})
            self.assertIsNone(pc.get_running_pid(lock_path, psutil_module=fake_psutil))

    def test_process_vanishing_between_is_running_and_cmdline_is_treated_as_stopped(self):
        # Regression test: a fast, clean process exit can race this check (is_running()
        # says yes, then cmdline() finds it already gone) -- that must not raise or be
        # mistaken for "still our process running".
        with tempfile.TemporaryDirectory() as tmp:
            lock_path = Path(tmp) / "phonewatcher.lock"
            lock_path.write_text("4321", encoding="utf-8")
            fake_psutil = _FakePsutil(
                processes={4321: _FakeProcess(cmdline=[], running=True, vanish_on_cmdline=True)}
            )

            pid = pc.get_running_pid(lock_path, psutil_module=fake_psutil)

            self.assertIsNone(pid)
            self.assertFalse(lock_path.exists())

    def test_corrupt_lock_file_contents_is_treated_as_no_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock_path = Path(tmp) / "phonewatcher.lock"
            lock_path.write_text("not-a-pid", encoding="utf-8")
            fake_psutil = _FakePsutil(processes={})
            self.assertIsNone(pc.get_running_pid(lock_path, psutil_module=fake_psutil))


if __name__ == "__main__":
    unittest.main()
