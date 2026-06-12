"""Tests for the parent-process watchdog (desktop crash-orphan guard)."""

from __future__ import annotations

import os
import subprocess
import threading

from agentic_os.parent_watch import parent_alive, start_parent_watch


def test_parent_alive_for_current_process() -> None:
    assert parent_alive(os.getpid()) is True


def test_parent_alive_false_for_reaped_child() -> None:
    child = subprocess.Popen(["/usr/bin/true"])
    child.wait()
    assert parent_alive(child.pid) is False


def test_watch_triggers_on_exit_when_parent_dies() -> None:
    child = subprocess.Popen(["/bin/sleep", "30"])
    fired = threading.Event()
    start_parent_watch(child.pid, interval_seconds=0.05, on_exit=fired.set)
    child.kill()
    child.wait()
    assert fired.wait(timeout=3.0), "watchdog did not fire after parent death"


def test_watch_stays_quiet_while_parent_alive() -> None:
    fired = threading.Event()
    start_parent_watch(os.getpid(), interval_seconds=0.05, on_exit=fired.set)
    assert not fired.wait(timeout=0.3), "watchdog fired while parent still alive"
