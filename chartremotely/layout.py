"""Find controls without assuming where on screen anything lives.

thinkorswim layouts differ per user, and one user's layout differs through
the day - charts get rearranged, panes resized, grids switched. Anything
that sweeps a fixed screen region works on the machine it was written on
and nowhere else.

The accessibility tree is no help on its own: the chart's controls are not
reachable through ``AXChildren``. The combo box holding the symbol reports
the window as its parent, yet the window does not list it as a child. The
link exists upward but not downward, so hit-testing is the only way in.

What the tree *does* expose reliably is the container layout - the split
groups and tab groups that tile the window. So: ask the tree where the
panes are, then hit-test relative to each pane's own bounds. Move the chart
anywhere and the search follows it.
"""

from __future__ import annotations

from . import ax

# Panes smaller than this cannot be a chart.
MIN_PANE_W, MIN_PANE_H = 400, 300

# Charting apps put the symbol entry and the toolbar in a band at the top of
# the pane. Searching that band first is an optimisation, not an assumption:
# discovery falls back to the whole pane.
BAND_HEIGHT = 140
STEP_X, STEP_Y = 12, 6

CONTAINER_ROLES = ("AXTabGroup", "AXSplitGroup", "AXScrollArea", "AXGroup")


def panes(ax_app, window_prefix: str) -> list[tuple[int, int, int, int]]:
    """Candidate chart panes as (x, y, w, h), largest first.

    Derived entirely from what the tree reports, so it holds wherever the
    user has dragged things.
    """
    window = ax.window(ax_app, window_prefix)
    if window is None:
        return []
    found: set[tuple[int, int, int, int]] = set()

    def visit(element):
        if ax.attr(element, "AXRole") not in CONTAINER_ROLES:
            return
        p, s = ax.position(element), ax.size(element)
        if p and s and s.width >= MIN_PANE_W and s.height >= MIN_PANE_H:
            found.add((int(p.x), int(p.y), int(s.width), int(s.height)))

    ax.walk(window, visit, budget=[400000])
    # Whole-window fallback: a layout may expose no qualifying container.
    p, s = ax.position(window), ax.size(window)
    if p and s:
        found.add((int(p.x), int(p.y), int(s.width), int(s.height)))
    return sorted(found, key=lambda r: -(r[2] * r[3]))


def scan(ax_app, rect, matches, *, band: int | None = BAND_HEIGHT,
         step_x: int = STEP_X, step_y: int = STEP_Y) -> tuple[int, int] | None:
    """Hit-test inside a rect until ``matches(element)`` is true.

    Coordinates are derived from the rect, never hardcoded. ``band`` limits
    the search to the top of the pane; pass None to sweep all of it.
    """
    x0, y0, w, h = rect
    height = min(band, h) if band else h
    for y in range(y0 + 2, y0 + height, step_y):
        for x in range(x0 + 2, x0 + w, step_x):
            if matches(ax.element_at(ax_app, x, y)):
                return x, y
    return None


def scan_all(ax_app, rect, matches, *, band: int | None = BAND_HEIGHT,
             step_x: int = STEP_X, step_y: int = STEP_Y) -> list[tuple[int, int]]:
    """Every distinct match in a rect, de-duplicated by element bounds.

    Used where a window may hold several charts: each gets its own hit.
    """
    x0, y0, w, h = rect
    height = min(band, h) if band else h
    hits: list[tuple[int, int]] = []
    seen: set[tuple[int, int]] = set()
    for y in range(y0 + 2, y0 + height, step_y):
        for x in range(x0 + 2, x0 + w, step_x):
            element = ax.element_at(ax_app, x, y)
            if not matches(element):
                continue
            p = ax.position(element)
            key = (int(p.x), int(p.y)) if p else (x, y)
            if key not in seen:
                seen.add(key)
                hits.append((x, y))
    return hits


def find_in_panes(ax_app, window_prefix: str, matches, *, band: int | None = BAND_HEIGHT):
    """Search each pane in turn, largest first. Returns (x, y) or None."""
    for rect in panes(ax_app, window_prefix):
        hit = scan(ax_app, rect, matches, band=band)
        if hit:
            return hit
    return None
