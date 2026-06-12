"""Self-terminate when a watched parent process disappears.

The desktop app starts agentd detached (nohup), so a crashed or
force-killed app would leave an orphan daemon. macOS has no PDEATHSIG;
instead the app passes its pid and the daemon polls it, exiting
gracefully once the pid is gone. CLI-started daemons never set the
flag and are unaffected.
"""

from __future__ import annotations

import os
import signal
import threading
import time
from collections.abc import Callable


def parent_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Process exists but belongs to another user.
        return True
    return True


def _default_exit() -> None:
    # SIGTERM to ourselves lets uvicorn run its graceful shutdown.
    os.kill(os.getpid(), signal.SIGTERM)


def start_parent_watch(
    pid: int,
    *,
    interval_seconds: float = 2.0,
    on_exit: Callable[[], None] | None = None,
) -> threading.Thread:
    """Watch pid in a daemon thread; trigger on_exit when it disappears."""
    trigger = on_exit or _default_exit

    def _loop() -> None:
        while parent_alive(pid):
            time.sleep(interval_seconds)
        trigger()

    thread = threading.Thread(target=_loop, name="parent-watch", daemon=True)
    thread.start()
    return thread
