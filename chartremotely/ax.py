"""macOS Accessibility and input primitives.

Everything awkward about driving thinkorswim lives here so the drivers above
stay readable. thinkorswim is a Java/Swing application, which breaks several
reasonable assumptions:

* Its accessibility tree is real, but chart children are populated lazily -
  walking ``AXChildren`` misses the symbol field entirely. Hit-testing finds
  it. See :func:`element_at`.
* ``AXValue`` is read-only on its text fields, while ``AXFocused`` is
  settable. You focus a field and type into it; you cannot write it.
* Its menu items answer to ``AXPick``, not ``AXPress``.
* Its aggregation list is a *lightweight* popup painted inside the window.
  It ignores process-targeted mouse events completely, so it needs a real
  HID click - which in turn needs the target to be unobstructed.
* AWT ignores ``CGEventKeyboardSetUnicodeString``; only real virtual
  keycodes register.
"""

from __future__ import annotations

import time

import Quartz
from AppKit import NSWorkspace
from ApplicationServices import (
    AXUIElementCopyActionNames,
    AXUIElementCopyAttributeValue,
    AXUIElementCopyElementAtPosition,
    AXUIElementCreateApplication,
    AXUIElementIsAttributeSettable,
    AXUIElementPerformAction,
    AXUIElementSetAttributeValue,
    AXValueGetValue,
    kAXErrorSuccess,
    kAXValueCGPointType,
    kAXValueCGSizeType,
)

APP_NAME = "thinkorswim"

# Virtual keycodes. AWT ignores unicode-string events, so every character
# must be sent as the key a human would press.
KEYCODE = {
    "a": 0, "b": 11, "c": 8, "d": 2, "e": 14, "f": 3, "g": 5, "h": 4,
    "i": 34, "j": 38, "k": 40, "l": 37, "m": 46, "n": 45, "o": 31, "p": 35,
    "q": 12, "r": 15, "s": 1, "t": 17, "u": 32, "v": 9, "w": 13, "x": 7,
    "y": 16, "z": 6,
    "0": 29, "1": 18, "2": 19, "3": 20, "4": 21,
    "5": 23, "6": 22, "7": 26, "8": 28, "9": 25,
    ".": 47, "/": 44, "-": 27, ":": 41, "$": 21,
}
KEY_RETURN, KEY_ESCAPE, KEY_DOWN = 36, 53, 125


class NotRunning(RuntimeError):
    """thinkorswim is not running."""


def running_app():
    for a in NSWorkspace.sharedWorkspace().runningApplications():
        if APP_NAME.lower() in (a.localizedName() or "").lower():
            return a
    raise NotRunning(f"{APP_NAME} is not running")


def handle(app=None):
    return AXUIElementCreateApplication((app or running_app()).processIdentifier())


def activate(app=None) -> None:
    """Bring thinkorswim forward, and wait for it to actually be forward.

    This must happen BEFORE any hit-testing.
    ``AXUIElementCopyElementAtPosition`` resolves against the application's
    menu bar - not the window under the point - when the app is not
    frontmost, so every lookup silently returns ``AXMenuBar``.
    """
    (app or running_app()).activateWithOptions_(2)
    time.sleep(0.6)


def attr(element, name):
    err, value = AXUIElementCopyAttributeValue(element, name, None)
    return value if err == kAXErrorSuccess else None


def settable(element, name) -> bool:
    err, is_settable = AXUIElementIsAttributeSettable(element, name, None)
    return bool(is_settable) if err == kAXErrorSuccess else False


def set_attr(element, name, value) -> bool:
    return AXUIElementSetAttributeValue(element, name, value) == kAXErrorSuccess


def actions(element) -> list[str]:
    err, names = AXUIElementCopyActionNames(element, None)
    return list(names) if err == kAXErrorSuccess else []


def perform(element, action) -> bool:
    """Run an action. Menu items want ``AXPick``; buttons want ``AXPress``."""
    return AXUIElementPerformAction(element, action) == kAXErrorSuccess


def _geo(element, name, kind):
    value = attr(element, name)
    if value is None:
        return None
    ok, out = AXValueGetValue(value, kind, None)
    return out if ok else None


def position(element):
    return _geo(element, "AXPosition", kAXValueCGPointType)


def size(element):
    return _geo(element, "AXSize", kAXValueCGSizeType)


def centre(element) -> tuple[int, int] | None:
    p, s = position(element), size(element)
    return (int(p.x + s.width / 2), int(p.y + s.height / 2)) if p and s else None


def element_at(ax_app, x: float, y: float):
    """Hit-test a screen point. Requires the app to be frontmost."""
    err, element = AXUIElementCopyElementAtPosition(ax_app, float(x), float(y), None)
    return element if err == kAXErrorSuccess else None


def window(ax_app, title_prefix: str):
    for w in attr(ax_app, "AXWindows") or []:
        if (attr(w, "AXTitle") or "").startswith(title_prefix):
            return w
    return None


def walk(element, visit, depth: int = 0, budget: list[int] | None = None) -> None:
    """Depth-first walk. Chart subtrees are lazy, so this cannot find
    everything - use it for dialogs, and hit-testing for charts."""
    budget = budget if budget is not None else [80000]
    budget[0] -= 1
    if budget[0] <= 0 or depth > 45:
        return
    visit(element)
    for child in attr(element, "AXChildren") or []:
        walk(child, visit, depth + 1, budget)


def find(root, *, role=None, label=None, predicate=None) -> list:
    """Collect matching descendants. ``label`` checks title, value and
    description - thinkorswim scatters captions across all three."""
    hits = []

    def visit(element):
        if role and attr(element, "AXRole") != role:
            return
        if label is not None and label not in (
            attr(element, "AXTitle"), attr(element, "AXValue"),
            attr(element, "AXDescription"),
        ):
            return
        if predicate and not predicate(element):
            return
        hits.append(element)

    walk(root, visit)
    return hits


# --------------------------------------------------------------------------
# Input


def key(code: int, flags: int = 0, pid: int | None = None) -> None:
    """Send a keystroke, to a process when given a pid.

    ``CGEventPost(kCGHIDEventTap)`` delivers to whatever holds keyboard
    focus, which is not reliably thinkorswim when another window floats
    always-on-top - the keystrokes land in that window instead.
    ``CGEventPostToPid`` removes the race.
    """
    for down in (True, False):
        event = Quartz.CGEventCreateKeyboardEvent(None, code, down)
        Quartz.CGEventSetFlags(event, flags)
        if pid is None:
            Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)
        else:
            Quartz.CGEventPostToPid(pid, event)
        time.sleep(0.012)


def type_text(text: str, pid: int | None = None) -> None:
    for ch in text.lower():
        code = KEYCODE.get(ch)
        if code is None:
            continue
        key(code, Quartz.kCGEventFlagMaskShift if ch in "$:" else 0, pid)
        time.sleep(0.02)


def escape(pid: int) -> None:
    key(KEY_ESCAPE, 0, pid)


# --------------------------------------------------------------------------
# Occlusion. A real HID click goes to whatever is visually on top, so
# clicking blind can land in another application entirely.


def _regular_pids() -> set[int]:
    """Ordinary windowed apps.

    System overlays - Notification Center above all - keep permanent
    full-screen windows at high layers with alpha 1.0 that are visually
    empty. Counting those as obstructions blocks every click forever.
    """
    return {a.processIdentifier()
            for a in NSWorkspace.sharedWorkspace().runningApplications()
            if a.activationPolicy() == 0}


def occluders_at(x: float, y: float, tos_pid: int) -> list[int]:
    """Pids of regular apps whose windows sit above thinkorswim at a point."""
    regular = _regular_pids()
    found, seen_target = [], False
    for w in Quartz.CGWindowListCopyWindowInfo(
            Quartz.kCGWindowListOptionOnScreenOnly, Quartz.kCGNullWindowID):
        pid = w.get("kCGWindowOwnerPID")
        b = w.get("kCGWindowBounds") or {}
        covers = (b.get("X", 0) <= x <= b.get("X", 0) + b.get("Width", 0)
                  and b.get("Y", 0) <= y <= b.get("Y", 0) + b.get("Height", 0))
        if pid == tos_pid and covers:
            seen_target = True
        elif (covers and not seen_target and pid in regular
              and w.get("kCGWindowLayer", 0) >= 0 and w.get("kCGWindowAlpha", 1)):
            found.append(pid)
    return list(dict.fromkeys(found))


def hide_apps(pids) -> list:
    apps = [a for a in NSWorkspace.sharedWorkspace().runningApplications()
            if a.processIdentifier() in pids and not a.isHidden()]
    for a in apps:
        a.hide()
    if apps:
        time.sleep(0.6)
    return apps


def unhide_apps(apps) -> None:
    for a in apps:
        a.unhide()


class Obstructed(RuntimeError):
    """The click target is covered and the click was refused."""


def click(x: int, y: int, tos_pid: int) -> None:
    """Real HID click, refused unless the target is provably unobstructed."""
    blockers = occluders_at(x, y, tos_pid)
    if blockers:
        names = sorted({(a.localizedName() or "?")
                        for a in NSWorkspace.sharedWorkspace().runningApplications()
                        if a.processIdentifier() in blockers})
        raise Obstructed(f"target at ({x},{y}) is covered by {', '.join(names)}")
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, Quartz.CGEventCreateMouseEvent(
        None, Quartz.kCGEventMouseMoved, Quartz.CGPointMake(x, y),
        Quartz.kCGMouseButtonLeft))
    time.sleep(0.25)
    for kind in (Quartz.kCGEventLeftMouseDown, Quartz.kCGEventLeftMouseUp):
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, Quartz.CGEventCreateMouseEvent(
            None, kind, Quartz.CGPointMake(x, y), Quartz.kCGMouseButtonLeft))
        time.sleep(0.12)
