"""Hand a spoken chart change to the operator, which charges for it and relays it.

Every chart change heard by voice goes to the operator's ``/agent/forward``,
even one for this Mac: blank "Where?" names this Mac by its own agent_id. The
operator is the one place names are matched (loosely - "mini mac" finds
"Mac mini") and the one place a change is priced, however it arrives. It
answers as soon as the change is paid for; the chart then changes by itself,
through this Mac's (or the target's) relay. So the words spoken back are the
hand-off, never the chart's own reply.

Stdlib only, like the relay, so it imports where the macOS drivers do not.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from . import config

ERR = "ERR "
#: The operator answers once the change is paid for, not once it is shown;
#: this only bounds a cold operator.
TIMEOUT = 35.0
AS_IS = {"", "as is", "asis"}


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


def sent(command: str, where: str, accepted: dict) -> str:
    """What to say once the operator has accepted a change: what, and where to."""
    verb, _, rest = command.partition(" ")
    ticker, _, scale = rest.partition("|")
    if verb.lower() == "set":
        what = str(accepted.get("symbol") or ticker.strip())
        scale = str(accepted.get("scale") or scale.strip())
    else:
        what, scale = command, ""
    at = "" if scale.lower() in AS_IS else f" at {scale} scale"
    return f"Chart {what}{at} sent to {where or 'this Mac'}. Good luck."


def send(command: str, where: str, cfg: dict | None = None) -> str:
    """Send one chart change to the display named ``where`` (blank: this Mac).

    Returns the sentence to speak. Never raises: every failure is a short
    ``ERR`` sentence, the operator's own refusal when it gave one.
    """
    cfg = cfg or config.load()
    base = (cfg.get("operator_url") or "").rstrip("/")
    agent_id, secret = cfg.get("agent_id"), cfg.get("agent_secret")
    if not (base and agent_id and secret):
        return ERR + "This Mac is not paired, so it cannot change a chart. Run chartremotely setup."
    # The Shortcut builds the command from this Mac's own replies, and every
    # reply ends in a newline ("PLTR\n"), so the command arrives as
    # "set PLTR\n | half\n"; the operator rightly refuses anything
    # unprintable. Collapse the whitespace before it leaves.
    wanted = " ".join((where or "").split())
    command = " ".join(command.split())
    try:
        status, body = _post(f"{base}/agent/forward",
                             {"agent_id": agent_id, "secret": secret,
                              "display": wanted or agent_id, "cmd": command})
    except (urllib.error.URLError, TimeoutError, OSError):
        return ERR + "I could not reach the operator."
    if status == 202:
        return sent(command, wanted, body)
    if status == 404:
        names = [str(n) for n in body.get("displays") or []]
        yours = f" Yours: {', '.join(names)}." if names else ""
        return ERR + f'No display named "{wanted or "this Mac"}".{yours}'
    return ERR + str(body.get("error") or f"the operator answered {status}")
