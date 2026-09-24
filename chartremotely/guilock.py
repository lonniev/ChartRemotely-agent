"""One driver of thinkorswim at a time, across every process on this Mac.

The Siri listener (`serve`) and the website's relay (`relay`) are separate
processes, and each can drive the chart; so can the background picture taken
after a change. Two of them hit-testing and typing into the same symbol field
at once is how a good request comes back as an error. A file lock is the one
primitive both processes and their threads share.

Stdlib only, so the wire logic that imports it stays importable on Linux.
"""

from __future__ import annotations

import fcntl
import time
from collections.abc import Iterator
from contextlib import contextmanager

from . import config

LOCK_NAME = "gui.lock"
#: Longest a request waits for another to finish driving the chart.
WAIT_SECONDS = 30.0
_POLL_SECONDS = 0.1


class Busy(TimeoutError):
    """Another request held the chart for longer than WAIT_SECONDS."""


@contextmanager
def driving(wait: float = WAIT_SECONDS) -> Iterator[None]:
    """Hold the chart for the duration of the block."""
    config.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(config.CONFIG_DIR / LOCK_NAME, "a") as handle:
        deadline = time.monotonic() + wait
        while True:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise Busy("the chart is busy with another request") from None
                time.sleep(_POLL_SECONDS)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)
