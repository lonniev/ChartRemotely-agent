"""Talk to the operator, so a display can be driven from anywhere.

The agent dials OUT and holds a poll open. Nothing here ever listens on a
public port and the operator never connects to this machine: no Funnel, no
port forwarding, no firewall rules, and nothing on the patron's network
becomes reachable. That single choice is why pairing is safe to offer to
someone who is not a network engineer.

Stdlib only, on purpose. This runs on a machine whose owner granted
Accessibility permission to software that types into a trading
application - the dependency list is part of what they are auditing.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

from . import config, requestlog
from .answer import Answer

#: Poll window. The operator holds a request open for slightly less than
#: this, so a timeout here means the network dropped it, not that the
#: operator is idle.
POLL_TIMEOUT = 35.0
CLAIM_INTERVAL = 3.0
BACKOFF_MAX = 60.0


class PairingError(RuntimeError):
    """Pairing could not be completed."""


def execute(command: str) -> Answer:
    """Hand a relayed command to the agent's own vocabulary.

    Imported lazily and wrapped here for one reason: the wire logic in this
    module is pure, and importing vocab at module scope would drag the macOS
    drivers in with it - making the whole file unimportable anywhere the
    drivers are not installed, CI included.
    """
    from .vocab import answer
    return answer(command)


def _post(url: str, payload: dict, timeout: float) -> dict:
    body = json.dumps(payload).encode()
    request = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read().decode("utf-8", "replace")
    return json.loads(raw) if raw.strip() else {}


def open_code(base: str) -> tuple[str, float]:
    """Ask the operator for a pairing code. Returns the code and its lifetime in seconds."""
    opened = _post(f"{base}/agent/open", {}, timeout=20)
    code = opened.get("code")
    if not code:
        raise PairingError("the operator did not issue a pairing code")
    return code, float(opened.get("expires_in") or 900)


def collect(base: str, code: str, expires_in: float) -> dict:
    """Wait until someone adopts the code, then keep the identity it earns."""
    deadline = time.time() + expires_in
    while time.time() < deadline:
        time.sleep(CLAIM_INTERVAL)
        try:
            claimed = _post(f"{base}/agent/collect", {"code": code}, timeout=45)
        except (urllib.error.URLError, TimeoutError, OSError):
            # A read timeout is TimeoutError, not URLError - catching only
            # the latter turned a slow first response into a hard failure.
            # The code stays valid, and collect is idempotent, so retrying
            # is always safe.
            continue
        if claimed.get("paired"):
            return config.update(operator_url=base,
                                 agent_id=claimed["agent_id"],
                                 agent_secret=claimed["secret"])
    raise PairingError("the pairing code expired before anyone claimed it")


def operator_base(operator_url: str | None) -> str:
    base = (operator_url or config.load().get("operator_url") or "").rstrip("/")
    if not base:
        raise PairingError("no operator URL; pass one or set operator_url in config")
    return base


def pair(operator_url: str | None = None, on_code=print) -> dict:
    """Ask the operator for a code, show it, and wait to be adopted.

    The patron reads the code to their MCP client, which calls
    ``pair_agent``. ``setup`` takes the same path and adopts the code itself.
    This machine hands out nothing: it proves it is theirs and receives an
    identity in return.
    """
    base = operator_base(operator_url)
    code, expires_in = open_code(base)
    on_code(code)
    return collect(base, code, expires_in)


def run(operator_url: str | None = None, once: bool = False) -> None:
    """Hold a poll open, execute what arrives, report the result.

    Commands are handed straight to the agent's own vocabulary. The
    operator relays; this machine decides what is permitted, which is what
    keeps a compromised operator from widening the surface.
    """
    cfg = config.load()
    base = (operator_url or cfg.get("operator_url") or "").rstrip("/")
    agent_id, secret = cfg.get("agent_id"), cfg.get("agent_secret")
    if not (base and agent_id and secret):
        raise PairingError("this agent is not paired; run: chartremotely pair")

    credentials = {"agent_id": agent_id, "secret": secret}
    backoff = 1.0
    while True:
        try:
            envelope = _post(f"{base}/agent/poll", credentials, timeout=POLL_TIMEOUT)
            backoff = 1.0
        except (urllib.error.URLError, TimeoutError, OSError):
            # The operator being unreachable is not fatal: this machine
            # still works locally, and the display should reconnect by
            # itself when the operator returns.
            time.sleep(backoff)
            backoff = min(backoff * 2, BACKOFF_MAX)
            if once:
                return
            continue

        if envelope.get("command"):
            command = str(envelope["command"])
            result = execute(command)
            reply = result.reply
            try:
                _post(f"{base}/agent/result",
                      {**credentials, "id": envelope.get("id"), "reply": reply},
                      timeout=20)
            except (urllib.error.URLError, TimeoutError, OSError):
                pass          # the caller has already timed out and refunded
            requestlog.request("relay", command, "", reply)
            # After the reply, never before: the picture of a changed chart.
            from . import push
            push.after_reply(command, reply, result.symbol)
        if once:
            return
