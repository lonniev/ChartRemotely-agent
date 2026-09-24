"""Make the chart visible, and prove what it shows.

A voice command answered from across the room is only useful if the chart
is actually on screen, and only trustworthy if the caller can see that it
changed. Both matter more remotely than locally: at the desk you can see it
worked; from another building a silent failure is indistinguishable from
success.
"""

from __future__ import annotations

import subprocess
import tempfile
import time
from pathlib import Path

import Quartz
from AppKit import NSWorkspace

from . import ax, config, layout, snapshot, symbol


def _frame(pid: int) -> dict | None:
    """Bounds of the largest on-screen thinkorswim window."""
    best, best_area = None, -1
    for w in Quartz.CGWindowListCopyWindowInfo(
            Quartz.kCGWindowListOptionOnScreenOnly, Quartz.kCGNullWindowID):
        if w.get("kCGWindowOwnerPID") != pid:
            continue
        b = w.get("kCGWindowBounds") or {}
        area = b.get("Width", 0) * b.get("Height", 0)
        if area > best_area:
            best, best_area = w, area
    return best


def _overlaps(a: dict, b: dict) -> bool:
    return not (a.get("X", 0) + a.get("Width", 0) <= b.get("X", 0)
                or a.get("X", 0) >= b.get("X", 0) + b.get("Width", 0)
                or a.get("Y", 0) + a.get("Height", 0) <= b.get("Y", 0)
                or a.get("Y", 0) >= b.get("Y", 0) + b.get("Height", 0))


def clear(app=None) -> list[str]:
    """Hide every ordinary app overlapping the chart, then raise it.

    Only regular apps are touched - system overlays keep permanent
    full-screen windows and are neither hideable nor actually in the way.
    """
    app = app or ax.running_app()
    pid = app.processIdentifier()
    target = _frame(pid)
    if target is None:
        return []
    bounds = target["kCGWindowBounds"]

    regular = {a.processIdentifier(): a
               for a in NSWorkspace.sharedWorkspace().runningApplications()
               if a.activationPolicy() == 0 and a.processIdentifier() != pid}

    covering = {w["kCGWindowOwnerPID"]
                for w in Quartz.CGWindowListCopyWindowInfo(
                    Quartz.kCGWindowListOptionOnScreenOnly, Quartz.kCGNullWindowID)
                if w.get("kCGWindowOwnerPID") in regular
                and w.get("kCGWindowLayer", 0) >= 0
                and _overlaps(w.get("kCGWindowBounds") or {}, bounds)}

    hidden = []
    for p in covering:
        a = regular[p]
        if not a.isHidden():
            a.hide()
            hidden.append(a.localizedName() or str(p))
    if hidden:
        time.sleep(0.4)
    app.activateWithOptions_(2)
    return sorted(hidden)


def capture(app=None) -> bytes:
    """PNG of the chart's own pane, and nothing else in the window.

    Captured by window id rather than screen region, so it works even when
    something is floating on top - which is what makes it usable as proof
    that a remote command landed. Then cropped to the pane that holds the
    chart's symbol field; see :func:`snapshot.chart_crop` for why the rest of
    the window never leaves this machine.
    """
    app = app or ax.running_app()
    target = _frame(app.processIdentifier())
    if target is None:
        raise ax.NotRunning("no thinkorswim window on screen")
    b = target["kCGWindowBounds"]
    bounds = (int(b["X"]), int(b["Y"]), int(b["Width"]), int(b["Height"]))

    # Hit-testing answers from the menu bar unless the app is in front.
    ax.activate(app)
    ax_app = ax.handle(app)
    prefix = config.load()["window_prefix"]
    hit = symbol.discover(ax_app, prefix)
    if hit is None:
        raise snapshot.ChartNotIsolated("no chart is visible")
    panes = layout.panes(ax_app, prefix)

    with tempfile.TemporaryDirectory() as tmp:
        shot = Path(tmp) / "window.png"
        subprocess.run(["screencapture", "-x", "-o", "-l", str(target["kCGWindowNumber"]), str(shot)],
                       check=True, capture_output=True)
        crop = snapshot.chart_crop(hit, panes, bounds, _pixel_size(shot))
        chart = Path(tmp) / "chart.png"
        _crop(shot, chart, *crop)
        return chart.read_bytes()


def _image(path: Path):
    from CoreFoundation import CFURLCreateWithFileSystemPath, kCFURLPOSIXPathStyle

    url = CFURLCreateWithFileSystemPath(None, str(path), kCFURLPOSIXPathStyle, False)
    return Quartz.CGImageSourceCreateImageAtIndex(Quartz.CGImageSourceCreateWithURL(url, None), 0, None)


def _pixel_size(path: Path) -> tuple[int, int]:
    image = _image(path)
    return Quartz.CGImageGetWidth(image), Quartz.CGImageGetHeight(image)


def _crop(src: Path, dst: Path, x: int, y: int, w: int, h: int) -> None:
    from CoreFoundation import CFURLCreateWithFileSystemPath, kCFURLPOSIXPathStyle

    region = Quartz.CGImageCreateWithImageInRect(_image(src), Quartz.CGRectMake(x, y, w, h))
    out_url = CFURLCreateWithFileSystemPath(None, str(dst), kCFURLPOSIXPathStyle, False)
    dest = Quartz.CGImageDestinationCreateWithURL(out_url, "public.png", 1, None)
    Quartz.CGImageDestinationAddImage(dest, region, None)
    Quartz.CGImageDestinationFinalize(dest)
