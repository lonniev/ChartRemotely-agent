"""Decisions about what is on screen, made from a snapshot of the window list.

Getting the chart in front of someone takes macOS calls - unhide, activate,
un-minimise, raise, hide what covers it - but deciding WHICH window is the
chart, WHETHER it is on screen yet and WHAT covers it needs none of them. That
half lives here, over plain dicts shaped like Quartz's window list, so it runs
(and is tested) where PyObjC is absent. :mod:`window` feeds it.

A window is a dict with ``kCGWindowOwnerPID``, ``kCGWindowLayer`` and
``kCGWindowBounds`` (``X``, ``Y``, ``Width``, ``Height``), as
``CGWindowListCopyWindowInfo`` reports it: front to back, on-screen only.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass

Frame = tuple[float, float, float, float]

#: Points of slack when matching the accessibility frame to the window list.
TOLERANCE = 2.0


def overlaps(a: dict, b: dict) -> bool:
    """Whether two bounds dicts share any area."""
    return not (a.get("X", 0) + a.get("Width", 0) <= b.get("X", 0)
                or a.get("X", 0) >= b.get("X", 0) + b.get("Width", 0)
                or a.get("Y", 0) + a.get("Height", 0) <= b.get("Y", 0)
                or a.get("Y", 0) >= b.get("Y", 0) + b.get("Height", 0))


def largest(windows: Iterable[dict], pid: int) -> dict | None:
    """The largest window ``pid`` has on screen."""
    best, best_area = None, -1.0
    for w in windows:
        if w.get("kCGWindowOwnerPID") != pid:
            continue
        b = w.get("kCGWindowBounds") or {}
        area = b.get("Width", 0) * b.get("Height", 0)
        if area > best_area:
            best, best_area = w, area
    return best


def showing(windows: Iterable[dict], pid: int, frame: Frame) -> dict | None:
    """The on-screen window of ``pid`` whose bounds are ``frame``, or None.

    ``frame`` is the chart window's (x, y, w, h) as the accessibility tree
    reports it. Matching on it, rather than taking the app's largest window,
    means a detached thinkorswim window left on screen does not count as the
    chart being back.
    """
    for w in windows:
        if w.get("kCGWindowOwnerPID") != pid:
            continue
        b = w.get("kCGWindowBounds") or {}
        got = (b.get("X", 0), b.get("Y", 0), b.get("Width", 0), b.get("Height", 0))
        if all(abs(g - f) <= TOLERANCE for g, f in zip(got, frame, strict=True)):
            return w
    return None


def covering(windows: Iterable[dict], bounds: dict, pid: int,
             regular: Iterable[int]) -> list[int]:
    """Pids of ordinary apps with a window overlapping ``bounds``.

    Only ``regular`` apps count: system overlays keep permanent full-screen
    windows that are neither hideable nor actually in the way. Negative
    layers are desktop furniture, never in front of the chart.
    """
    allowed = set(regular) - {pid}
    found = [w["kCGWindowOwnerPID"] for w in windows
             if w.get("kCGWindowOwnerPID") in allowed
             and w.get("kCGWindowLayer", 0) >= 0
             and overlaps(w.get("kCGWindowBounds") or {}, bounds)]
    return list(dict.fromkeys(found))


def wait_for(probe: Callable[[], object], timeout: float = 2.0, interval: float = 0.1,
             clock: Callable[[], float] = time.monotonic,
             sleep: Callable[[float], None] = time.sleep):
    """Poll ``probe`` until it returns something truthy, for at most ``timeout`` seconds.

    Returns that value, or None when time ran out. Always probes at least once.
    """
    deadline = clock() + timeout
    while True:
        found = probe()
        if found:
            return found
        if clock() >= deadline:
            return None
        sleep(interval)


@dataclass(frozen=True)
class Presented:
    """What it took to get the chart in front of the viewer."""

    unhid: bool = False
    unminimized: bool = False
    raised: bool = False
    hid: tuple[str, ...] = ()

    def __bool__(self) -> bool:
        return self.unhid or self.unminimized or self.raised or bool(self.hid)

    def __str__(self) -> str:
        done = [word for word, did in (("unhid", self.unhid),
                                       ("unminimized", self.unminimized),
                                       ("raised", self.raised)) if did]
        if self.hid:
            done.append("hid " + ", ".join(self.hid))
        return "; ".join(done) or "already in front"
