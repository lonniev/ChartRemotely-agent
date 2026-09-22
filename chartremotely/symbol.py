"""Drive the chart's symbol field.

``AXValue`` on that field is read-only, so the symbol cannot be written
directly. ``AXFocused`` *is* settable, so the field is focused and typed
into - which is also why the vocabulary can be kept narrow: this module can
only ever put text in one box.
"""

from __future__ import annotations

import re
import time

import Quartz

from . import ax, config

# Accepts tickers, futures (/ES), indices (.SPX) and share classes (BRK/B).
TICKER = re.compile(r"^[./$]?[A-Z]{1,6}([/.][A-Z]{1,2})?(:[A-Z]+)?$")

# Where to look when discovering the field: the chart toolbar band.
SEARCH_X = range(380, 760, 8)
SEARCH_Y = range(95, 210, 5)


class NotFound(RuntimeError):
    """The symbol field could not be located or did not validate."""


def to_ticker(text: str) -> str:
    """Normalise a ticker. Name resolution happens in :mod:`resolve`."""
    t = re.sub(r"[^A-Z0-9./$-]", "", text.strip().upper())
    # The SEC writes share classes as BRK-B; thinkorswim wants BRK/B.
    return re.sub(r"-([A-Z]{1,2})$", r"/\1", t)


def validate(element) -> tuple[bool, str]:
    """True only for something that really is a symbol entry field.

    This is the guard that keeps a stale offset from typing a ticker into
    whatever else happens to be at those coordinates.
    """
    if element is None or ax.attr(element, "AXRole") != "AXTextField":
        return False, "not a text field"
    parent = ax.attr(element, "AXParent")
    if parent is None or ax.attr(parent, "AXRole") != "AXComboBox":
        return False, "parent is not a combo box"
    if not ax.settable(element, "AXFocused"):
        return False, "field does not accept focus"
    value = ax.attr(element, "AXValue")
    if not isinstance(value, str) or not TICKER.match(value.strip()):
        return False, f"current value {value!r} is not ticker-shaped"
    return True, value.strip()


def discover(ax_app) -> tuple[int, int] | None:
    """Find the symbol field by sweeping the toolbar band.

    The chart's accessibility children are populated lazily, so a tree walk
    never reaches this field; hit-testing does. Being able to find it
    automatically is what removes the manual teach step.
    """
    for y in SEARCH_Y:
        for x in SEARCH_X:
            ok, _ = validate(ax.element_at(ax_app, x, y))
            if ok:
                return x, y
    return None


def learn(app=None) -> dict:
    """Locate the field and record its window-relative offset."""
    app = app or ax.running_app()
    ax.activate(app)
    ax_app = ax.handle(app)
    cfg = config.load()
    found = discover(ax_app)
    if found is None:
        raise NotFound("no symbol field found; is a chart visible?")
    win = ax.window(ax_app, cfg["window_prefix"])
    if win is None:
        raise NotFound(f"no window titled {cfg['window_prefix']!r}")
    origin = ax.position(win)
    return config.update(symbol_dx=int(found[0] - origin.x),
                         symbol_dy=int(found[1] - origin.y))


def locate(ax_app, cfg: dict):
    """Resolve the field through the window's CURRENT position.

    The stored offset only proposes where to look; validation decides
    whether to act. A small ring absorbs minor layout drift, and a full
    rediscovery handles the rest.
    """
    win = ax.window(ax_app, cfg["window_prefix"])
    if win is None:
        raise NotFound(f"no window titled {cfg['window_prefix']!r}")
    origin = ax.position(win)

    if cfg.get("symbol_dx") is not None:
        x, y = int(origin.x) + cfg["symbol_dx"], int(origin.y) + cfg["symbol_dy"]
        ok, info = validate(ax.element_at(ax_app, x, y))
        if ok:
            return ax.element_at(ax_app, x, y), info
        for r in (4, 8, 12):
            for dx, dy in ((r, 0), (-r, 0), (0, r), (0, -r), (r, r), (-r, -r)):
                ok, info = validate(ax.element_at(ax_app, x + dx, y + dy))
                if ok:
                    return ax.element_at(ax_app, x + dx, y + dy), info

    found = discover(ax_app)
    if found is None:
        raise NotFound("symbol field did not validate and could not be rediscovered")
    config.update(symbol_dx=int(found[0] - origin.x),
                  symbol_dy=int(found[1] - origin.y))
    element = ax.element_at(ax_app, *found)
    return element, validate(element)[1]


def current(app=None) -> str:
    """What the field reports.

    Note this can be STALE: thinkorswim does not push accessibility updates,
    so after a change it may still report the previous symbol. Use it to
    confirm the field is reachable, never to confirm a change took.
    """
    app = app or ax.running_app()
    ax.activate(app)
    _, value = locate(ax.handle(app), config.load())
    return value


def show(ticker: str, app=None) -> str:
    """Put a ticker in the chart. Returns the symbol that was displaced."""
    ticker = to_ticker(ticker)
    if not ticker or not TICKER.match(ticker):
        raise ValueError(f"not a valid ticker: {ticker!r}")

    app = app or ax.running_app()
    pid = app.processIdentifier()
    ax.activate(app)
    field, previous = locate(ax.handle(app), config.load())

    if not ax.set_attr(field, "AXFocused", True):
        raise NotFound("could not focus the symbol field")
    time.sleep(0.15)

    ax.key(ax.KEYCODE["a"], Quartz.kCGEventFlagMaskCommand, pid)
    time.sleep(0.10)
    ax.type_text(ticker, pid)

    # thinkorswim pops an autocomplete list as you type. A Return arriving
    # before it renders is swallowed and the list stays open over the chart.
    # Let it settle, accept it, then commit - the second Return is a no-op
    # on an already-committed field.
    time.sleep(0.35)
    ax.key(ax.KEY_RETURN, 0, pid)
    time.sleep(0.25)
    ax.key(ax.KEY_RETURN, 0, pid)
    return previous
