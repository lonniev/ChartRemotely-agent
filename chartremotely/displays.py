"""The owner's display names, so a sentence can say where: "... on mac mini".

:func:`understand.understand` splits "on <display>" off a sentence only when
it knows the names, and :mod:`hearing` primes Whisper with them. They come
from the operator's free ``chart_agent_status`` tool, asked as the owner
(their npub and voice sign-in), and are cached in
``~/.local/share/chartremotely/displays.json`` - labels only, never a token.

The list changes only when a display is paired or forgotten, so it is asked
for at most every :data:`MAX_AGE` seconds, after setup, and in the background:
a voice request never waits for it, and uses what is cached (this Mac's own
label at least) meanwhile.

Stdlib only.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable

from . import config, keystore, mcpclient, requestlog
from .config import DATA_DIR

PATH = DATA_DIR / "displays.json"
MAX_AGE = 4 * 3600
TOOL = "chart_agent_status"


def _read(path=None) -> dict:
    try:
        data = json.loads((path or PATH).read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def load(path=None) -> list[str]:
    """The cached display labels, this Mac's first; [] when none are cached."""
    data = _read(path)
    labels = data.get("labels")
    return [str(x) for x in labels if isinstance(x, str) and x.strip()] if isinstance(labels, list) else []


def stale(path=None, now: Callable[[], float] = time.time) -> bool:
    fetched = _read(path).get("fetched_at")
    return not isinstance(fetched, (int, float)) or now() - fetched > MAX_AGE


def labels_from(payload: dict, agent_id: str | None) -> list[str]:
    """Display labels from a ``chart_agent_status`` answer, this Mac's first."""
    rows = payload.get("displays") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return []
    mine, others = [], []
    for row in rows:
        if not isinstance(row, dict):
            continue
        label = " ".join(str(row.get("label") or "").split())[:64]
        if not label:
            continue
        (mine if agent_id and row.get("agent_id") == agent_id else others).append(label)
    out: list[str] = []
    for label in mine + others:
        if label not in out:
            out.append(label)
    return out


def refresh(cfg: dict | None = None, client_for=None, path=None) -> list[str] | None:
    """Ask the operator for the owner's displays and cache them.

    Returns the labels, or None when they could not be had (not paired, not
    signed in, operator unreachable) - the cache is then left as it was.
    Never raises.
    """
    cfg = cfg or config.load()
    base = (cfg.get("operator_url") or "").rstrip("/")
    npub = cfg.get("owner_npub")
    if not (base and npub and cfg.get("agent_id")):
        return None
    try:
        token = keystore.load_token(npub)
        if not token:
            return None
        payload = (client_for or mcpclient.Client)(base, timeout=30.0).call(TOOL, {"npub": npub, "dpop_token": token})
    except Exception as exc:  # noqa: BLE001 - a missing list must never cost a reply
        requestlog.outcome("serve", TOOL, "", f"display list failed: {type(exc).__name__}")
        return None
    if payload.get("error") or payload.get("success") is False:
        requestlog.outcome("serve", TOOL, "", str(payload.get("error") or "refused"))
        return None
    labels = labels_from(payload, cfg.get("agent_id"))
    target = path or PATH
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(".tmp")
        tmp.write_text(json.dumps({"fetched_at": time.time(), "labels": labels}))
        tmp.replace(target)
    except OSError:
        pass
    return labels


_refreshing = threading.Lock()


def refresh_in_background(**kwargs) -> bool:
    """Start one :func:`refresh`; False when one is already running."""
    if not _refreshing.acquire(blocking=False):
        return False

    def work() -> None:
        try:
            refresh(**kwargs)
        finally:
            _refreshing.release()

    threading.Thread(target=work, name="refresh-displays", daemon=True).start()
    return True


def current() -> list[str]:
    """The labels to use now; starts a background refresh when they are old."""
    if stale():
        refresh_in_background()
    return load()
