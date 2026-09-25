"""Tell the operator what the chart looks like after it changes.

A chart changed by voice goes straight to this machine over the tailnet, so
the operator never hears of it. Once a change is answered — after the reply
("… Good luck.") has been sent — one picture of the chart pane is pushed up so
the patron's browser can offer it, labelled with the symbol and scale the
last command of the burst put on the chart (the symbol field is read only as
a fallback: it can be stale; the scale is never read back). The operator keeps the newest picture per symbol,
encrypted, for an hour each.

Three rules keep it out of the way:

* **After the reply.** The listener and the relay schedule the picture only
  once their reply has gone out, so it never delays or races the answer.
* **Coalesced.** Changes in quick succession produce one picture, taken when
  the chart has been quiet for QUIET_SECONDS — never a trail of in-between
  captures.
* **Serialised.** The capture holds the same cross-process lock as every
  command that drives the chart (guilock), so it never overlaps one.

Any failure is swallowed: the chart already changed, and a missing picture
must never become a spoken error. Stdlib only at module scope, like the relay;
the capture is imported lazily.
"""

from __future__ import annotations

import re
import threading
import time

from . import config, guilock, relay

#: How long the chart must go unchanged before its picture is taken.
QUIET_SECONDS = 1.5

#: Verbs that read or picture the chart, or only resolve words: they change
#: nothing, so no picture follows them. Every other request — `set`, or a bare
#: company name — changes the chart (see vocab.dispatch).
_NOT_A_CHANGE = frozenset({"resolve", "scale", "read", "snapshot"})

#: What a symbol label may look like on the wire: tickers, futures (/ES),
#: indices (.SPX, $SPX.X, ^VIX) and share classes (BRK/B). The operator checks
#: the same shape; anything else is left off rather than sent.
SYMBOL = re.compile(r"^[A-Z0-9./^$-]{1,15}$")

#: What a scale label may look like on the wire: the words a reply states
#: ("half", "30 minutes", "1 day"). The operator checks the same shape.
SCALE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 .:/-]{0,23}$")

_state = threading.Condition()
#: The symbol the last successful chart-changing command put on the chart.
#: A burst's picture carries the LAST one; a change that names none keeps it.
_named: str | None = None
#: The scale the last chart-changing command stated; kept the same way.
_scaled: str | None = None
_due: float | None = None
_worker: threading.Thread | None = None


def changes_chart(request: str, reply: str) -> bool:
    """Whether this answered request changed what the chart shows."""
    verb = (request or "").strip().partition(" ")[0].lower()
    return bool(verb) and verb not in _NOT_A_CHANGE and not reply.startswith("ERR")


def symbol_label(raw: object) -> str | None:
    """The chart's symbol as sent to the operator, or None when it is not symbol-shaped."""
    if not isinstance(raw, str):
        return None
    label = raw.strip().upper()
    return label if SYMBOL.match(label) else None


def scale_label(raw: object) -> str | None:
    """The chart's scale as sent to the operator, or None when it is not scale-shaped."""
    if not isinstance(raw, str):
        return None
    label = " ".join(raw.split())
    return label if SCALE.match(label) else None


def payload(cfg: dict, image: str, symbol: str | None = None,
            scale: str | None = None) -> tuple[str, dict] | None:
    """Where to send a picture and what to send, or None when not paired.

    ``symbol`` is what the chart showed when the picture was taken; it is left
    out when unknown or not symbol-shaped, and the operator files the picture
    under a plain "Chart". ``scale`` is the time frame the last change stated;
    it is left out the same way.
    """
    base = (cfg.get("operator_url") or "").rstrip("/")
    agent_id, secret = cfg.get("agent_id"), cfg.get("agent_secret")
    if not (base and agent_id and secret):
        return None
    body = {"agent_id": agent_id, "secret": secret, "image": image}
    label = symbol_label(symbol)
    if label:
        body["symbol"] = label
    scaled = scale_label(scale)
    if scaled:
        body["scale"] = scaled
    return f"{base}/agent/snapshot", body


def _showing() -> str | None:
    """The symbol field's value, or None. Never raises.

    Only a fallback: thinkorswim does not push accessibility updates, so right
    after a change this can still name the previous symbol. The symbol a
    command named is preferred whenever one is known.
    """
    try:
        from . import symbol
        return symbol_label(symbol.current())
    except Exception:  # noqa: BLE001 - a label is optional; the picture is not
        return None


def after_reply(request: str, reply: str, symbol: str | None = None,
                scale: str | None = None) -> None:
    """Call once a reply has been sent. Schedules a picture if the chart changed.

    ``symbol`` and ``scale`` are what the command put on the chart
    (vocab.Answer), when it named them; a change that names neither keeps the
    previous command's.
    """
    global _named, _scaled
    if changes_chart(request, reply):
        with _state:
            _named = symbol_label(symbol) or _named
            _scaled = scale_label(scale) or _scaled
        schedule()


def schedule() -> None:
    """Ask for one picture once the chart has been quiet; later asks push it back."""
    global _due, _worker
    with _state:
        _due = time.monotonic() + QUIET_SECONDS
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_wait_then_push, name="push-latest", daemon=True)
            _worker.start()
        _state.notify_all()


def _wait_then_push() -> None:
    global _due
    with _state:
        while True:
            remaining = (_due or 0) - time.monotonic()
            if remaining <= 0:
                _due = None
                break
            _state.wait(remaining)
    push_now()


def push_now() -> None:
    """Take the chart's picture and send it. Never raises."""
    try:
        cfg = config.load()
        if payload(cfg, "") is None:
            return
        from . import snapshot, window
        with guilock.driving():
            image = snapshot.as_reply(snapshot.shrink(window.capture()))
            with _state:
                label, scaled = _named, _scaled
            label = label or _showing()
        url, body = payload(cfg, image, label, scaled)
        relay._post(url, body, timeout=30)
    except Exception:  # noqa: BLE001, S110 - deliberate: see the module docstring
        pass
