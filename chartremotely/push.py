"""Tell the operator what the chart looks like after it changes.

A chart changed by voice goes straight to this machine over the tailnet, so
the operator never hears of it. Once a change is answered — after the reply
("… Good luck.") has been sent — one picture of the chart pane is pushed up so
the patron's browser can offer it. The operator keeps only the newest,
encrypted, for an hour.

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

import threading
import time

from . import config, guilock, relay

#: How long the chart must go unchanged before its picture is taken.
QUIET_SECONDS = 1.5

#: Verbs that read or picture the chart, or only resolve words: they change
#: nothing, so no picture follows them. Every other request — `set`, or a bare
#: company name — changes the chart (see vocab.dispatch).
_NOT_A_CHANGE = frozenset({"resolve", "scale", "read", "snapshot"})

_state = threading.Condition()
_due: float | None = None
_worker: threading.Thread | None = None


def changes_chart(request: str, reply: str) -> bool:
    """Whether this answered request changed what the chart shows."""
    verb = (request or "").strip().partition(" ")[0].lower()
    return bool(verb) and verb not in _NOT_A_CHANGE and not reply.startswith("ERR")


def payload(cfg: dict, image: str) -> tuple[str, dict] | None:
    """Where to send a picture and what to send, or None when not paired."""
    base = (cfg.get("operator_url") or "").rstrip("/")
    agent_id, secret = cfg.get("agent_id"), cfg.get("agent_secret")
    if not (base and agent_id and secret):
        return None
    return f"{base}/agent/snapshot", {"agent_id": agent_id, "secret": secret, "image": image}


def after_reply(request: str, reply: str) -> None:
    """Call once a reply has been sent. Schedules a picture if the chart changed."""
    if changes_chart(request, reply):
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
        url, body = payload(cfg, image)
        relay._post(url, body, timeout=30)
    except Exception:  # noqa: BLE001, S110 - deliberate: see the module docstring
        pass
