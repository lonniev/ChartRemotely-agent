"""Drive the chart's aggregation (time frame).

The presets live in a Java *lightweight* popup painted inside the window,
which is the most awkward control in the application:

* its rows are ``AXStaticText`` with no actions, so nothing can be pressed
* it ignores process-targeted mouse events entirely - no hover, no click
* arrow keys do not move its selection
* it dismisses when window activation changes

Only a real HID click works, which means the target must be uncovered
*before* the popup opens. Clearing occluders afterwards dismisses it.

Spoken mnemonics are chosen for phonetic distance rather than literal
accuracy. Digits are the worst thing to say to a recogniser - "fifteen" and
"fifty" collide - so the vocabulary avoids them.
"""

from __future__ import annotations

import re
import time

from . import ax, config
from .scales import AS_IS, MNEMONIC, canon, to_code

ITEM = re.compile(r"^\s*\d+\s*[DYW]\s*:\s*\S+", re.IGNORECASE)

class MenuError(RuntimeError):
    """The aggregation menu could not be opened or read."""


def discover(ax_app) -> tuple[int, int] | None:
    """Find the aggregation toggle by its neighbours.

    The control carries no label, but "Style", "Drawings", "Studies" and
    "Patterns" sit beside it and do. The toggle is the unlabelled check box
    immediately left of Style, so anchor on Style rather than on a fixed
    coordinate that a layout change would invalidate.
    """
    style = None
    for y in (120, 130, 140):
        for x in range(1400, 1920, 6):
            element = ax.element_at(ax_app, x, y)
            if element is None or ax.attr(element, "AXRole") != "AXCheckBox":
                continue
            label = ax.attr(element, "AXTitle") or ax.attr(element, "AXDescription")
            if label == "Style":
                style = ax.position(element)
                break
        if style:
            break
    if style is None:
        return None
    # Step left from Style until an unlabelled, pressable check box appears.
    for dx in range(10, 140, 4):
        x, y = int(style.x) - dx, int(style.y) + 12
        element = ax.element_at(ax_app, x, y)
        if element is None or ax.attr(element, "AXRole") != "AXCheckBox":
            continue
        label = ax.attr(element, "AXTitle") or ax.attr(element, "AXDescription")
        if not label and "AXPress" in ax.actions(element):
            return x, y
    return None


def learn(app=None) -> dict:
    app = app or ax.running_app()
    ax.activate(app)
    ax_app = ax.handle(app)
    cfg = config.load()
    found = discover(ax_app)
    if found is None:
        raise MenuError("aggregation control not found; is a chart visible?")
    win = ax.window(ax_app, cfg["window_prefix"])
    origin = ax.position(win)
    return config.update(aggregation_dx=int(found[0] - origin.x),
                         aggregation_dy=int(found[1] - origin.y))


def _control(ax_app, cfg):
    win = ax.window(ax_app, cfg["window_prefix"])
    if win is None:
        raise MenuError(f"no window titled {cfg['window_prefix']!r}")
    origin = ax.position(win)
    if cfg.get("aggregation_dx") is None:
        raise MenuError("aggregation control not learned; run doctor")
    x = int(origin.x) + cfg["aggregation_dx"]
    y = int(origin.y) + cfg["aggregation_dy"]
    return ax.element_at(ax_app, x, y), (x, y)


def _open(ax_app, cfg):
    """Open the popup if it is closed.

    The control is a TOGGLE. Pressing it while the menu is already showing
    closes it, so a blind press is a coin flip.
    """
    element, point = _control(ax_app, cfg)
    if element is None:
        raise MenuError(f"no aggregation control at {point}")
    if ax.attr(element, "AXValue") in (0, "0", False, None):
        ax.perform(element, "AXPress")
        time.sleep(0.9)
    return element


def _rows(ax_app) -> list[dict]:
    """Every preset the popup offers, with its centre and active flag.

    The list is the user's favourites, so never assume a fixed set or order.
    """
    found: list[dict] = []
    seen: set[str] = set()

    def visit(element):
        for name in ("AXValue", "AXTitle", "AXDescription"):
            value = ax.attr(element, name)
            if isinstance(value, str) and ITEM.match(value.strip()):
                label = value.strip()
                spot = ax.centre(element)
                if spot and label not in seen:
                    seen.add(label)
                    parent = ax.attr(element, "AXParent")
                    found.append({
                        "label": label, "x": spot[0], "y": spot[1],
                        "active": bool(parent is not None
                                       and ax.attr(parent, "AXSelected")),
                    })
                break

    for window in ax.attr(ax_app, "AXWindows") or []:
        ax.walk(window, visit)
    return found


def presets(app=None) -> list[str]:
    app = app or ax.running_app()
    ax.activate(app)
    ax_app = ax.handle(app)
    _open(ax_app, config.load())
    rows = _rows(ax_app)
    ax.escape(app.processIdentifier())
    return [r["label"] for r in rows]


def current(app=None) -> tuple[str, str]:
    """The active preset as (label, mnemonic), without changing anything."""
    app = app or ax.running_app()
    ax.activate(app)
    ax_app = ax.handle(app)
    _open(ax_app, config.load())
    rows = _rows(ax_app)
    ax.escape(app.processIdentifier())
    active = next((r for r in rows if r["active"]), None)
    if active is None:
        raise MenuError("could not read the current scale")
    label = active["label"]
    return label, MNEMONIC.get(canon(label), label)


def set_scale(phrase: str, app=None) -> tuple[str, str]:
    """Select a preset. Returns (label, mnemonic)."""
    if phrase.lower().strip() in AS_IS:
        return current(app)

    app = app or ax.running_app()
    pid = app.processIdentifier()
    ax.activate(app)
    ax_app = ax.handle(app)
    cfg = config.load()

    # Uncover the target BEFORE opening the popup: hiding an application
    # shuffles window activation, and a lightweight popup dismisses when
    # that happens.
    _, point = _control(ax_app, cfg)
    probes = [point] + [(point[0] - 120 + dx, point[1] + dy)
                        for dx in (0, 160, 320) for dy in (40, 200, 380)]
    blockers: list[int] = []
    for px, py in probes:
        blockers += ax.occluders_at(px, py, pid)
    hidden = ax.hide_apps(list(dict.fromkeys(blockers)))
    time.sleep(0.4)

    try:
        _open(ax_app, cfg)
        rows = _rows(ax_app)
        if not rows:
            raise MenuError("aggregation menu did not open")

        want = to_code(phrase)
        if not want:
            # canon() yields "" for an unparseable phrase, and every string
            # ends with "", so the loose match below would select whatever
            # happened to be first. Refuse instead.
            raise MenuError(f"could not parse timeframe {phrase!r}")
        match = next((r for r in rows if canon(r["label"]) == want), None)
        if match is None:
            match = next((r for r in rows if canon(r["label"]).endswith(want)), None)
        if match is None:
            offered = ", ".join(r["label"] for r in rows)
            raise MenuError(f"no preset matches {phrase!r}; this chart offers: {offered}")

        ax.click(match["x"], match["y"], pid)
        time.sleep(0.5)
        label = match["label"]
        return label, MNEMONIC.get(canon(label), label)
    except Exception:
        ax.escape(pid)
        raise
    finally:
        ax.unhide_apps(hidden)
