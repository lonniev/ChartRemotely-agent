"""Close thinkorswim's popups before anyone looks at the chart.

Two popups get left open over the chart, and a picture taken then shows them:

* the symbol field's autocomplete list (PLTR:XTSE, PLTRX, ...), which hangs
  under the field after a symbol is typed and often outlives the Return that
  committed it;
* the aggregation (time frame) menu, which stays open after a preset is
  picked or the current one is read.

Neither answers the obvious remedies. An Escape posted to thinkorswim lands on
whatever holds keyboard focus, which after a commit is nothing at all - so it
is silently dropped. What works, measured on thinkorswim build 1993:

* the aggregation menu closes when its toggle is pressed again (``AXPress``);
  the toggle's ``AXValue`` is 1 while the menu shows;
* the autocomplete list closes on Escape once the symbol field has focus.
  Escape only hides the list: text typed but not yet committed stays in the
  field, so it never cancels an entry;
* focus leaves the field when the chart's own title strip (the line under
  the field reading "PLTR 10 D 30m") is focused. Setting the field's
  ``AXFocused`` to false is accepted and ignored.

A Swing field commits its text when it loses focus, so focus is moved off the
field only when that text is what the chart already shows. Otherwise the field
keeps focus and its pending text, and nothing changes.

The decisions are pure and live at module scope, over a :class:`Seen`
snapshot, so they are tested where PyObjC is absent. :func:`dismiss` gathers
the snapshots and acts; its macOS imports are deferred.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass

Rect = tuple[float, float, float, float]

#: Longest dismiss() spends closing popups.
TIMEOUT = 1.5
#: How often dismiss() looks again after acting.
POLL = 0.1
#: Longest dismiss() waits for one action to show before trying it again.
ACT_WAIT = 0.5
#: Points of slack when deciding a list hangs from the symbol field.
SLACK = 8
#: How far under the field's bottom edge to hit-test for a list or the title.
PROBE_DY, PROBE_DX = 8, 8

#: The first word of the chart's title strip: the symbol it is drawn for.
CHART_SYMBOL = re.compile(r"^[./$^]?[A-Z0-9]{1,12}([/.][A-Z0-9]{1,3})?(:[A-Z]+)?$")

CLOSE_SCALE, CLOSE_LIST, LEAVE_FIELD = "close scale menu", "close symbol list", "leave field"


@dataclass(frozen=True)
class Seen:
    """What the chart's popups and symbol field looked like at one moment."""

    scale_open: bool = False
    list_open: bool = False
    field_focused: bool = False
    field_value: str | None = None
    #: The chart's title strip, e.g. "PLTR 10 D 30m"; None while a list covers it.
    title: str | None = None

    @property
    def clean(self) -> bool:
        """Nothing is drawn over the chart."""
        return not (self.scale_open or self.list_open)


def hangs_under(field: Rect, table: Rect | None) -> bool:
    """Whether ``table`` is the autocomplete list dropped from the symbol field.

    thinkorswim paints that list inside the window, so the window server never
    sees it; the accessibility tree reports it as a table whose top-left corner
    sits on the field's bottom-left corner. ``field`` is the field's combo box.
    """
    if table is None:
        return False
    fx, fy, _, fh = field
    tx, ty, tw, th = table
    return (tw > 0 and th > 0 and abs(tx - fx) <= SLACK
            and abs(ty - (fy + fh)) <= SLACK)


def chart_symbol(title: str | None) -> str | None:
    """The symbol a chart title strip names ("PLTR 10 D 30m" -> "PLTR"), or None."""
    if not isinstance(title, str) or not title.strip():
        return None
    word = title.split()[0]
    return word if CHART_SYMBOL.match(word) else None


def shows(title: str | None, entry: str | None) -> bool:
    """Whether the chart already shows what ``entry`` names.

    A futures root typed as "/ES" is drawn as its front contract ("/ESZ26"),
    so a root counts as shown by any of its contracts.
    """
    drawn = chart_symbol(title)
    want = (entry or "").strip().upper()
    if not drawn or not want:
        return False
    return drawn == want or (want.startswith("/") and drawn.startswith(want))


def next_step(seen: Seen) -> str | None:
    """The one thing to do next, or None when there is nothing safe left to do.

    The menu is closed before the list: its toggle is pressed through the
    tree, which needs no focus, whereas closing the list moves focus into the
    field. Focus leaves the field only when the chart already shows its text,
    because losing focus commits whatever the field holds.
    """
    if seen.scale_open:
        return CLOSE_SCALE
    if seen.list_open:
        return CLOSE_LIST
    if seen.field_focused and shows(seen.title, seen.field_value):
        return LEAVE_FIELD
    return None


@dataclass(frozen=True)
class Dismissed:
    """What dismiss() did, and whether the chart was left uncovered."""

    did: tuple[str, ...] = ()
    clean: bool = True

    def __bool__(self) -> bool:
        return bool(self.did)

    def __str__(self) -> str:
        done = "; ".join(self.did) or "nothing open"
        return done if self.clean else done + "; a popup is still open"


def run(look: Callable[[], Seen], act: Callable[[str], None], *,
        until: Callable[[Seen], bool] | None = None, timeout: float = TIMEOUT,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep) -> Dismissed:
    """Look, act on the next step, and look again until nothing is left.

    ``until``, when given, must also hold before it stops early: a symbol just
    committed is waited for until the chart's title names it, so focus can
    leave the field once it is safe to. One action is retried only after it
    has had ACT_WAIT to show, so a slow repaint is not answered with a second
    press of a toggle.
    """
    deadline = clock() + timeout
    did: list[str] = []
    last: tuple[str | None, float] = (None, -ACT_WAIT)
    while True:
        seen = look()
        step = next_step(seen)
        now = clock()
        if step is None and (until is None or until(seen)) or now >= deadline:
            return Dismissed(tuple(did), seen.clean)
        if step is not None and (step != last[0] or now - last[1] >= ACT_WAIT):
            act(step)
            if step not in did:
                did.append(step)
            last = (step, now)
        sleep(POLL)


# --------------------------------------------------------------------------
# macOS. Imported lazily so the decisions above stay importable anywhere.


def _frame(ax, element) -> Rect | None:
    p, s = ax.position(element), ax.size(element)
    return (p.x, p.y, s.width, s.height) if p and s else None


def _under_field(ax, ax_app, field):
    """The combo's frame, the element just under it, and the list that is, if any."""
    combo = ax.attr(field, "AXParent")
    frame = _frame(ax, combo) if combo is not None else None
    if frame is None:
        return None, None, None
    x, y, _, h = frame
    hit = ax.element_at(ax_app, x + PROBE_DX, y + h + PROBE_DY)
    table = None
    for element in (hit, ax.attr(hit, "AXParent") if hit is not None else None):
        if element is not None and ax.attr(element, "AXRole") == "AXTable":
            table = element
            break
    return frame, hit, table


def dismiss(app=None, expect: str | None = None, timeout: float = TIMEOUT) -> Dismissed:
    """Close the symbol list and the scale menu, and take focus off the field.

    ``expect`` is a symbol just committed: dismiss() then also waits, within
    ``timeout``, for the chart's title to name it before it lets focus go.

    Idempotent, and cheap when nothing is open: a few accessibility reads.
    Call it with thinkorswim in front (hit-testing answers from the menu bar
    otherwise), inside the chart lock, after the change it tidies up after.
    A field or toggle that cannot be found is left alone rather than raised
    about: tidying up must never turn a change that landed into an error.
    """
    from . import ax, config, symbol, timeframe

    app = app or ax.running_app()
    pid = app.processIdentifier()
    ax_app = ax.handle(app)
    cfg = config.load()
    try:
        field, _ = symbol.locate(ax_app, cfg)
    except symbol.NotFound:
        field = None
    try:
        toggle, _ = timeframe._control(ax_app, cfg)
    except timeframe.MenuError:
        toggle = None
    title = [None]

    def look() -> Seen:
        scale_open = toggle is not None and ax.attr(toggle, "AXValue") not in (0, "0", False, None)
        if field is None:
            return Seen(scale_open=scale_open)
        frame, hit, table = _under_field(ax, ax_app, field)
        list_open = frame is not None and hangs_under(
            frame, _frame(ax, table) if table is not None else None)
        title[0] = None if list_open else hit
        return Seen(
            scale_open=scale_open,
            list_open=list_open,
            field_focused=bool(ax.attr(field, "AXFocused")),
            field_value=ax.attr(field, "AXValue"),
            title=ax.attr(title[0], "AXValue") if title[0] is not None else None,
        )

    def act(step: str) -> None:
        if step == CLOSE_SCALE:
            ax.perform(toggle, "AXPress")
        elif step == CLOSE_LIST:
            # Escape reaches only the focused component; after a commit that
            # is nothing, so the field is focused first.
            if not ax.attr(field, "AXFocused"):
                ax.set_attr(field, "AXFocused", True)
                time.sleep(0.1)
            ax.escape(pid)
        elif step == LEAVE_FIELD:
            # LEAVE_FIELD is only chosen when the element under the field
            # read as the chart's title, so title[0] is that strip.
            ax.set_attr(title[0], "AXFocused", True)

    until = (lambda seen: shows(seen.title, expect)) if expect else None
    return run(look, act, until=until, timeout=timeout)
