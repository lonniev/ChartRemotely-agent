"""The listener as an ordinary patron: a voice command becomes a priced tool call.

The Mac plays by the operator's rules like any other MCP client. A chart
change heard by voice is a call to the operator's own ``chart_show_chart``
(and "read" to ``chart_read_chart``), made with the display owner's ``npub``
and the ``dpop_token`` they earned by answering a Nostr DM - the same
envelope every patron sends. The operator prices it, relays it to the named
display (blank "Where?": this Mac, by its agent_id), and that display's relay
changes the chart and takes its picture. Nothing here drives the chart.

Siri should not wait for the chart. The call starts in the background; a
refusal that comes back within :data:`HANDOFF_SECONDS` (sign-in expired, not
enough balance, no such display) is spoken, and otherwise the hand-off is
spoken at once - "Chart PLTR at half scale sent to Mac-mini. Good luck." -
while the call finishes on its own and its outcome is logged.

When the sign-in has expired the owner hears so, and one renewal runs in the
background: a fresh ``chart_request_npub_proof`` DM, then
``chart_receive_npub_proof`` on a bounded, slowing schedule until they answer,
and the new token goes back into the Keychain. The nsec is never asked for.

Stdlib only (the Keychain behind a lazy import), like the relay.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

from . import config, keystore, mcpclient, requestlog

ERR = "ERR "
#: How long a spoken reply waits for an early refusal before handing off.
HANDOFF_SECONDS = 3.0
#: "read" is answered with what the chart shows, so it may wait longer.
READ_SECONDS = 25.0
#: Bounds a cold operator plus the relay's own wait; the reply never waits on it.
CALL_TIMEOUT = 60.0
AS_IS = {"", "as is", "asis"}

#: What the SDK answers when a paid call's dpop_token is missing, unknown or expired.
PROOF_CODES = frozenset({"proof_missing", "proof_required", "proof_refresh_needed", "proof_invalid"})
EXPIRED = ERR + "Your ChartRemotely sign-in expired. Answer the DM on your phone to renew."
REASON = "Your Mac's ChartRemotely voice control needs you to sign in again."
#: Seconds between looks for the owner's reply: quick at first, then patient;
#: about half an hour in all, then the renewal gives up until the next command.
RENEW_DELAYS = (15.0,) * 4 + (30.0,) * 6 + (60.0,) * 25
#: The one receive answer that means "not yet" rather than "stop".
NOT_YET = "courier_not_found"


# -- what a spoken command asks of the operator ----------------------------------

def tool_for(command: str) -> tuple[str, dict] | str:
    """The priced tool and its arguments for one command, or an ERR sentence.

    ``set TICKER | scale`` -> chart_show_chart; ``read`` -> chart_read_chart;
    a bare name -> chart_show_chart with that name. ``snapshot`` has a
    priced tool, but a picture cannot be spoken: it is refused here.
    """
    verb, _, rest = command.partition(" ")
    verb = verb.lower()
    if verb == "set":
        ticker, _, scale = rest.partition("|")
        scale = scale.strip()
        return "chart_show_chart", {"security": ticker.strip(),
                                    "scale": "" if scale.lower() in AS_IS else scale}
    if verb == "read":
        return "chart_read_chart", {}
    if verb == "snapshot":
        return ERR + "A picture cannot be spoken. See your screens at chartremotely.tollbooth-dpyc.com."
    return "chart_show_chart", {"security": command, "scale": ""}


def handoff(args: dict, where: str) -> str:
    """What to say once a chart change is on its way: what, and where to."""
    at = f" at {args['scale']} scale" if args.get("scale") else ""
    return f"Chart {args['security']}{at} sent to {where or 'this Mac'}. Good luck."


def refusal(payload: dict) -> str | None:
    """The operator's reason for refusing, when it refused; else None."""
    if payload.get("success") is False or payload.get("ok") is False or payload.get("error"):
        return str(payload.get("error") or payload.get("result") or "the operator refused")
    return None


# -- the call -----------------------------------------------------------------------

def _call(base: str, tool: str, args: dict) -> dict:
    """One tool call. Never raises: an unreachable operator is an ``error`` payload."""
    try:
        return mcpclient.Client(base, timeout=CALL_TIMEOUT).call(tool, args)
    except mcpclient.McpError as exc:
        return {"success": False, "error": str(exc)}
    except Exception as exc:  # noqa: BLE001 - a background call must never kill the listener
        return {"success": False, "error": f"the call failed: {type(exc).__name__}"}


def send(command: str, where: str, cfg: dict | None = None) -> str:
    """Ask the operator's priced tool for one command, for the display named ``where``.

    Returns the sentence to speak. Never raises.
    """
    cfg = cfg or config.load()
    base = (cfg.get("operator_url") or "").rstrip("/")
    agent_id, npub = cfg.get("agent_id"), cfg.get("owner_npub")
    if not (base and agent_id):
        return ERR + "This Mac is not paired, so it cannot change a chart. Run chartremotely setup."
    if not npub:
        return ERR + "This Mac does not know whose display it is. Run chartremotely setup."
    # The Shortcut splices this Mac's own replies ("PLTR\n") into the command.
    wanted = " ".join((where or "").split())
    command = " ".join((command or "").split())
    mapped = tool_for(command)
    if isinstance(mapped, str):
        return mapped
    tool, args = mapped
    try:
        token = keystore.load_token(npub)
    except keystore.KeystoreError as exc:
        requestlog.outcome("serve", tool, wanted, str(exc))
        return ERR + "The Keychain would not give me your ChartRemotely sign-in."
    if not token:
        renew(base, npub)
        return EXPIRED

    envelope = {**args, "display": wanted or agent_id, "npub": npub, "dpop_token": token}
    box: dict = {}
    done = threading.Event()

    def work() -> None:
        payload = _call(base, tool, envelope)
        box["payload"] = payload
        settle(base, npub, tool, wanted, payload)
        done.set()

    threading.Thread(target=work, name=f"call-{tool}", daemon=True).start()
    if not done.wait(READ_SECONDS if tool == "chart_read_chart" else HANDOFF_SECONDS):
        return handoff(args, wanted) if tool == "chart_show_chart" else \
            f"Reading {wanted or 'this Mac'}; the answer is taking a while."
    payload = box["payload"]
    if payload.get("error_code") in PROOF_CODES:
        return EXPIRED
    if (why := refusal(payload)) is not None:
        return ERR + why.removeprefix(ERR)
    if tool == "chart_read_chart":
        return str(payload.get("result") or "")
    return handoff(args, wanted)


def settle(base: str, npub: str, tool: str, where: str, payload: dict) -> None:
    """Log how a call ended (no token, no arguments) and renew an expired sign-in."""
    if payload.get("error_code") in PROOF_CODES:
        renew(base, npub)
    requestlog.outcome("serve", tool, where, refusal(payload))


# -- renewing an expired sign-in ------------------------------------------------------

_renewing = threading.Lock()


def renew(base: str, npub: str, sleep: Callable[[float], None] = time.sleep) -> bool:
    """Start one background renewal; False when one is already under way."""
    if not _renewing.acquire(blocking=False):
        return False
    threading.Thread(target=_renew, args=(base, npub, sleep), name="renew-sign-in", daemon=True).start()
    return True


def _renew(base: str, npub: str, sleep: Callable[[float], None]) -> None:
    try:
        sent = _call(base, "chart_request_npub_proof", {"patron_npub": npub, "reason": REASON})
        phrase = sent.get("dpop_token")
        if not phrase:
            requestlog.outcome("serve", "renew", "", refusal(sent) or "no proof request was sent")
            return
        for delay in RENEW_DELAYS:
            sleep(delay)
            got = _call(base, "chart_receive_npub_proof", {"patron_npub": npub, "dpop_token": phrase})
            if got.get("success") is not False and not got.get("error"):
                keystore.save_token(npub, str(got.get("dpop_token") or phrase))
                requestlog.outcome("serve", "renew", "", None)
                return
            if got.get("error_code") not in (NOT_YET, None):
                requestlog.outcome("serve", "renew", "", refusal(got))
                return
        requestlog.outcome("serve", "renew", "", "the DM was not answered in time")
    except Exception as exc:  # noqa: BLE001 - renewal must never take the listener down
        requestlog.outcome("serve", "renew", "", f"renewal failed: {type(exc).__name__}")
    finally:
        _renewing.release()
