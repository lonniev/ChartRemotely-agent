"""Manage the chart's studies.

Not on the voice path - this is the one-time setup that puts a useful chart
on the wall. It drives thinkorswim's Edit Studies dialog, which behaves
differently from the chart itself in several ways worth knowing:

* the Studies toolbar control is a toggle that can be left "on" with no menu
  showing, so a blind press closes it instead of opening it
* its menu items answer to ``AXPick``
* the study list rows answer to NEITHER press nor keyboard - selecting one
  needs a real click, and "Add selected" stays greyed until something is
  genuinely selected
* button captions live in ``AXDescription``, not ``AXTitle``
* its combo boxes are not settable, but accept type-ahead once focused:
  send "d" and CHART becomes DAY
"""

from __future__ import annotations

import time

from . import ax, config, layout

DIALOG = "Edit Studies and Strategies"

# A chart for reading structure: where price traded, whether volatility is
# compressed, and the session's volume-weighted mean.
PRESET = (
    ("VolumeProfile", None),
    ("squeeze", "TTM_Squeeze"),
    ("vwap", "VWAP"),      # the period-resetting one, NOT AnchoredVWAP
)


class DialogError(RuntimeError):
    """The studies dialog could not be opened or driven."""


def _dialog(ax_app):
    for window in ax.attr(ax_app, "AXWindows") or []:
        if (ax.attr(window, "AXTitle") or "") == DIALOG:
            return window
    return None


def _labelled(element, caption: str) -> bool:
    return caption in (ax.attr(element, "AXTitle"), ax.attr(element, "AXDescription"))


def _button(root, caption: str):
    hits = ax.find(root, role="AXButton", predicate=lambda el: _labelled(el, caption))
    return hits[0] if hits else None


def open_dialog(app=None):
    """Studies toolbar -> "Edit studies...". Returns the dialog element."""
    app = app or ax.running_app()
    ax.activate(app)
    ax_app = ax.handle(app)
    if _dialog(ax_app) is not None:
        return _dialog(ax_app)

    prefix = config.load()["window_prefix"]
    spot = layout.find_in_panes(
        ax_app, prefix,
        lambda el: el is not None and ax.attr(el, "AXRole") == "AXCheckBox"
        and _labelled(el, "Studies"))
    if spot is None:
        raise DialogError("Studies control not found; is a chart visible?")

    toggle = ax.element_at(ax_app, *spot)
    # Cycle a stuck-open toggle: pressing it while already "on" would close
    # the menu, and the stale items left behind do not respond to AXPick.
    if ax.attr(toggle, "AXValue") in (0, "0", False, None):
        ax.perform(toggle, "AXPress")
        time.sleep(1.4)
    else:
        ax.perform(toggle, "AXPress")
        time.sleep(0.8)
        ax.perform(toggle, "AXPress")
        time.sleep(1.4)

    item = None
    for window in ax.attr(ax_app, "AXWindows") or []:
        for candidate in ax.find(window, role="AXMenuItem"):
            label = (ax.attr(candidate, "AXTitle") or ax.attr(candidate, "AXValue")
                     or ax.attr(candidate, "AXDescription") or "")
            if str(label).strip().lower().startswith("edit studies"):
                item = candidate
                break
        if item:
            break
    if item is None:
        raise DialogError("'Edit studies...' not found in the Studies menu")

    ax.perform(item, "AXPick")   # menu items take AXPick, not AXPress
    time.sleep(3.0)
    dialog = _dialog(ax_app)
    if dialog is None:
        raise DialogError("the studies dialog did not open")
    return dialog


def applied(ax_app=None) -> list[str]:
    """Studies currently on the chart."""
    dialog = _dialog(ax_app or ax.handle())
    if dialog is None:
        return []
    names = []
    for element in ax.find(dialog, role="AXStaticText"):
        value = ax.attr(element, "AXValue")
        if isinstance(value, str) and "(" in value and value.strip():
            names.append(value.strip()[:46])
    return list(dict.fromkeys(names))   # the dialog renders each row twice


def _row_label(row) -> str:
    found = []
    ax.walk(row, lambda el: found.append(
        ax.attr(el, "AXValue") or ax.attr(el, "AXTitle") or ax.attr(el, "AXDescription")))
    return next((str(v).strip() for v in found if isinstance(v, str) and v.strip()), "")


def add(search: str, exact: str | None = None, app=None) -> bool:
    """Filter the catalogue and add one study.

    ``exact`` matters: the list is alphabetical, so searching "vwap" offers
    AnchoredVWAP first and a naive "take the first row" picks the wrong one.
    """
    app = app or ax.running_app()
    pid = app.processIdentifier()
    ax_app = ax.handle(app)
    dialog = _dialog(ax_app)
    if dialog is None:
        raise DialogError("the studies dialog is not open")
    want = (exact or search).lower()

    # The filter field is the text field inside a combo box - the same
    # distinctive shape as the chart's symbol entry. Picking "the first wide
    # text field" grabs something else and the catalogue never filters,
    # leaving the category tree ("All Studies", "Alpha Studies") in view.
    def _is_filter(element):
        parent = ax.attr(element, "AXParent")
        return bool(parent is not None and ax.attr(parent, "AXRole") == "AXComboBox")

    fields = ax.find(dialog, role="AXTextField", predicate=_is_filter)
    if not fields:
        raise DialogError("the study filter field was not found")
    ax.set_attr(fields[0], "AXFocused", True)
    time.sleep(0.3)
    ax.key(ax.KEYCODE["a"], 1 << 20, pid)      # command-A
    time.sleep(0.1)
    ax.type_text(search, pid)
    time.sleep(1.2)

    rows = ax.find(dialog, role="AXRow",
                   predicate=lambda el: (ax.position(el) or type("", (), {"x": 9e9})).x < 900)
    target = next((r for r in rows if _row_label(r).lower() == want), None)
    if target is None:
        raise DialogError(f"no study named {want!r}; offered: "
                          f"{[_row_label(r) for r in rows][:5]}")
    button = _button(dialog, "Add selected")
    if button is None:
        raise DialogError("'Add selected' not found")

    # Rows answer to neither AXPress nor the keyboard: only a real click
    # selects one, and until one is selected the button stays greyed.
    spot, target_spot = ax.centre(button), ax.centre(target)
    blockers = ax.occluders_at(*target_spot, pid) + ax.occluders_at(*spot, pid)
    hidden = ax.hide_apps(list(dict.fromkeys(blockers)))
    try:
        ax.click(*target_spot, pid)
        time.sleep(0.6)
        ax.click(*spot, pid)
        time.sleep(1.4)
    finally:
        ax.unhide_apps(hidden)
    return True


def press(caption: str, app=None) -> bool:
    """Press a labelled button in the dialog."""
    app = app or ax.running_app()
    dialog = _dialog(ax.handle(app))
    button = _button(dialog, caption) if dialog else None
    if button is None:
        return False
    return ax.perform(button, "AXPress")


def setup(row_height: str | None = None, per: str = "CHART", app=None) -> list[str]:
    """Rebuild the study set from scratch. Idempotent.

    ``row_height`` should match the underlying's strike increment so profile
    buckets land on tradable strikes.
    """
    app = app or ax.running_app()
    cfg = config.load()
    height = row_height or cfg["row_height"]
    open_dialog(app)
    press("Remove all", app)
    time.sleep(0.8)
    for search, exact in PRESET:
        add(search, exact, app)
    configure_volume_profile(height, per, app)
    # Read the result BEFORE closing: applied() inspects the dialog, which
    # no longer exists once OK is pressed.
    result = applied()
    press("OK", app)
    time.sleep(2.5)
    config.update(row_height=height)
    return result


def configure_volume_profile(row_height: str = "1.0", per: str = "CHART", app=None) -> bool:
    """Set the profile's row height and period in its customiser."""
    app = app or ax.running_app()
    ax_app = ax.handle(app)
    dialog = _dialog(ax_app)
    if dialog is None:
        raise DialogError("the studies dialog is not open")

    rows = [el for el in ax.find(dialog, role="AXStaticText")
            if str(ax.attr(el, "AXValue") or "").startswith("VolumeProfile")]
    if not rows:
        raise DialogError("VolumeProfile is not in the applied list")
    # Find the row's settings control structurally: the buttons sharing its
    # vertical band, rightmost last. A fixed pixel offset from the label
    # would break the moment the dialog is resized or relaid out.
    row_spot = ax.centre(rows[0])

    def _same_band(element):
        p, s = ax.position(element), ax.size(element)
        return bool(p and s and p.y <= row_spot[1] <= p.y + s.height
                    and p.x > row_spot[0])

    controls = sorted(ax.find(dialog, role="AXButton", predicate=_same_band),
                      key=lambda el: ax.position(el).x)
    if not controls:
        raise DialogError("the VolumeProfile settings control was not found")
    gear = controls[-1]
    ax.perform(gear, "AXPress")
    time.sleep(2.5)

    sheet = next((w for w in ax.attr(ax_app, "AXWindows") or []
                  if (ax.attr(w, "AXTitle") or "").startswith("VolumeProfile")), None)
    if sheet is None:
        raise DialogError("the VolumeProfile customiser did not open")

    combos = sorted(ax.find(sheet, role="AXComboBox"),
                    key=lambda el: (ax.position(el).y, ax.position(el).x))
    if len(combos) < 3:
        raise DialogError("unexpected customiser layout")
    # Combos are not settable, but type-ahead works once focused.
    for combo, letter in ((combos[0], "c"), (combos[2], per[0].lower())):
        ax.set_attr(combo, "AXFocused", True)
        time.sleep(0.35)
        ax.key(ax.KEYCODE[letter], 0, app.processIdentifier())
        time.sleep(0.7)

    ok = _button(sheet, "OK")
    if ok is not None:
        ax.perform(ok, "AXPress")
        time.sleep(2.0)
    return True
