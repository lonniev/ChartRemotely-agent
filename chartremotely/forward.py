"""Send a spoken command on to another of the owner's displays.

The Shortcut asks "Where?" and passes the dictated answer through verbatim.
Empty, or this Mac's exact agent_id, means this Mac. Any other name goes to
the operator's ``/agent/forward``, which is the one place names are matched:
it finds the display among the SAME owner's displays (loosely - "mini mac"
finds "Mac mini") and relays the command there, or answers that the name is
this Mac's own. The target's reply is what gets spoken.

Stdlib only, like the relay, so it imports where the macOS drivers do not.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from . import config

ERR = "ERR "
#: Longer than the operator's own wait on the target, so its 504 arrives first.
TIMEOUT = 35.0

def is_here(where: str, cfg: dict) -> bool:
    """Whether ``where`` means this Mac without asking: empty, or exactly its agent_id."""
    wanted = (where or "").strip()
    return not wanted or wanted == cfg.get("agent_id")


def _post(url: str, payload: dict) -> tuple[int, dict]:
    """POST JSON; the status and the JSON body, for error statuses too."""
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode(), method="POST",
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            status, raw = response.status, response.read()
    except urllib.error.HTTPError as exc:
        status, raw = exc.code, exc.read()
    try:
        body = json.loads(raw.decode("utf-8", "replace") or "{}")
    except ValueError:
        body = {}
    return status, body if isinstance(body, dict) else {}


def route(command: str, where: str, cfg: dict | None = None) -> str | None:
    """The reply of the display named ``where``, or None when that display is this Mac.

    Never raises: every failure is a short ``ERR`` sentence to be spoken.
    """
    cfg = cfg or config.load()
    if is_here(where, cfg):
        return None
    base = (cfg.get("operator_url") or "").rstrip("/")
    agent_id, secret = cfg.get("agent_id"), cfg.get("agent_secret")
    if not (base and agent_id and secret):
        return ERR + "This Mac is not paired, so it can only drive its own chart."
    # The Shortcut builds the command from this Mac's own replies, and every
    # reply ends in a newline ("PLTR\n"), so a forwarded command arrives as
    # "set PLTR\n | half\n". Run here, vocab strips that; the operator rightly
    # refuses anything unprintable. Collapse the whitespace before it leaves.
    wanted = " ".join(where.split())
    try:
        status, body = _post(f"{base}/agent/forward",
                             {"agent_id": agent_id, "secret": secret,
                              "display": wanted, "cmd": " ".join(command.split())})
    except (urllib.error.URLError, TimeoutError, OSError):
        return ERR + "I could not reach the operator."
    if status == 200 and body.get("self"):
        return None
    if status == 200:
        return str(body.get("reply") or "")
    if status == 404:
        names = [str(n) for n in body.get("displays") or []]
        yours = f" Yours: {', '.join(names)}." if names else ""
        return ERR + f'No display named "{wanted}".{yours}'
    return ERR + str(body.get("error") or f"the operator answered {status}")
