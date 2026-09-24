"""Tell the operator what the chart looks like after it changes.

A chart changed by voice goes straight to this machine over the tailnet, so
the operator never hears of it. Right after a change succeeds, one picture of
the chart pane is pushed up so the patron's browser can offer it. The operator
keeps only the newest, encrypted, for an hour.

Off the voice path on purpose: the push runs in the background after the
answer is already on its way, and any failure is swallowed. The chart has
already changed; a missing picture must never turn into a spoken error.

Stdlib only at module scope, like the relay: the capture is imported lazily.
"""

from __future__ import annotations

import threading
import time

from . import config, relay

#: Time for the chart to redraw before its picture is taken.
SETTLE_SECONDS = 1.0

_lock = threading.Lock()


def payload(cfg: dict, image: str) -> tuple[str, dict] | None:
    """Where to send a picture and what to send, or None when not paired."""
    base = (cfg.get("operator_url") or "").rstrip("/")
    agent_id, secret = cfg.get("agent_id"), cfg.get("agent_secret")
    if not (base and agent_id and secret):
        return None
    return f"{base}/agent/snapshot", {"agent_id": agent_id, "secret": secret, "image": image}


def after_change(reply: str) -> str:
    """Start a picture push if the change worked. Returns the reply unchanged."""
    if not reply.startswith("ERR"):
        threading.Thread(target=push_now, name="push-latest", daemon=True).start()
    return reply


def push_now() -> None:
    """Take the chart's picture and send it. Never raises."""
    try:
        cfg = config.load()
        if payload(cfg, "") is None:
            return
        # One at a time: two quick changes should not capture over each other.
        with _lock:
            time.sleep(SETTLE_SECONDS)
            from . import snapshot, window
            image = snapshot.as_reply(snapshot.shrink(window.capture()))
            url, body = payload(cfg, image)
            relay._post(url, body, timeout=30)
    except Exception:  # noqa: BLE001, S110 - deliberate: see the module docstring
        pass
