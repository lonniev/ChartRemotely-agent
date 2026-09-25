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

from . import ax, config, layout, screen, snapshot, symbol

#: NSApplicationActivateAllWindows | NSApplicationActivateIgnoringOtherApps:
#: bring every thinkorswim window forward, even when another app is in front.
ACTIVATE = 1 | 2
#: Longest wait for the chart window to reach the screen after being raised.
ON_SCREEN_WAIT = 2.0


class NotOnScreen(RuntimeError):
    """The chart window could not be brought on screen."""


def _on_screen() -> list[dict]:
    return list(Quartz.CGWindowListCopyWindowInfo(
        Quartz.kCGWindowListOptionOnScreenOnly, Quartz.kCGNullWindowID) or [])


def _frame(pid: int) -> dict | None:
    """The largest on-screen thinkorswim window."""
    return screen.largest(_on_screen(), pid)


def _ax_frame(win) -> screen.Frame | None:
    p, s = ax.position(win), ax.size(win)
    return (p.x, p.y, s.width, s.height) if p and s else None


def present(app=None) -> screen.Presented:
    """Put the chart window in front of the viewer, before anything drives it.

    Unhides thinkorswim, brings it forward, un-minimises and raises the chart
    window (the one titled ``window_prefix``, which every driver works in),
    waits until it is actually on screen - activation also switches to its
    Space when it is full screen elsewhere - then hides the ordinary apps
    overlapping it. Only regular apps are ever hidden: system overlays keep
    permanent full-screen windows and are neither hideable nor in the way.

    Run inside the chart lock, like every command that drives the chart.
    """
    app = app or ax.running_app()
    pid = app.processIdentifier()
    ax_app = ax.handle(app)
    # Read from the process itself: NSRunningApplication's isHidden/isActive
    # only refresh on a run loop, which the listener and relay never spin.
    unhid = bool(ax.attr(ax_app, "AXHidden"))
    raised = not ax.attr(ax_app, "AXFrontmost")
    if unhid:
        app.unhide()
    app.activateWithOptions_(ACTIVATE)

    prefix = config.load()["window_prefix"]
    win = screen.wait_for(lambda: ax.window(ax_app, prefix), timeout=ON_SCREEN_WAIT)
    if win is None:
        raise NotOnScreen(f"no thinkorswim window titled {prefix!r}")
    unminimized = bool(ax.attr(win, "AXMinimized"))
    if unminimized:
        ax.set_attr(win, "AXMinimized", False)
    ax.perform(win, "AXRaise")
    ax.set_attr(win, "AXMain", True)
    ax.set_attr(win, "AXFocused", True)

    def arrived():
        frame = _ax_frame(win)
        return frame and screen.showing(_on_screen(), pid, frame)

    target = screen.wait_for(arrived, timeout=ON_SCREEN_WAIT)
    if target is None:
        raise NotOnScreen("the chart window did not come on screen")

    hid = _uncover(pid, target["kCGWindowBounds"])
    app.activateWithOptions_(ACTIVATE)
    return screen.Presented(unhid=unhid, unminimized=unminimized,
                            raised=raised or unminimized, hid=hid)


def _uncover(pid: int, bounds: dict) -> tuple[str, ...]:
    """Hide every ordinary app with a window over ``bounds``; their names."""
    windows = _on_screen()
    apps = {p: ax.app_for(p) for p in {w.get("kCGWindowOwnerPID") for w in windows} if p}
    regular = {p: a for p, a in apps.items() if a is not None and a.activationPolicy() == 0}
    hidden = []
    # An app with a window on screen is not hidden, whatever a cached
    # isHidden says; see present().
    for p in screen.covering(windows, bounds, pid, regular):
        a = regular[p]
        a.hide()
        hidden.append(a.localizedName() or str(p))
    if hidden:
        time.sleep(0.4)
    return tuple(sorted(hidden))


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
