"""One spoken sentence, from recording to reply.

The "ChartRemotely" Shortcut records a sentence and posts it here. This
module hears it (:mod:`hearing`), understands it (:mod:`understand`) and
either asks for what is missing or makes the same priced call a typed
request makes (:func:`patron.send`, ``chart_show_chart``) - so voice costs
exactly what it cost before, and the reply is the same hand-off: "Chart
PLTR at half scale sent to mac mini. Good luck."

A follow-up question ends with :data:`LISTENING`. The Shortcut records again
when it hears that word, and what was understood the first time is held for
:data:`FOLLOW_UP_SECONDS`: "Palantir" then "half" is one request, as is
"Palantir half" then "PLTR" after "Did you mean PLTR or PLTX?".

Never raises: every path returns a sentence to speak.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import replace

from . import displays, hearing, patron, recent, registry, requestlog, resolve
from .understand import Understanding, understand

ERR = "ERR "
#: The word every follow-up question ends with; the Shortcut listens again on it.
LISTENING = "I'm listening."
FOLLOW_UP_SECONDS = 45.0

_pending: dict = {}
_pending_lock = threading.Lock()


def _held(now: float) -> Understanding | None:
    with _pending_lock:
        got = _pending.get("u")
        if got and now - _pending.get("at", 0.0) <= FOLLOW_UP_SECONDS:
            return got
        _pending.clear()
        return None


def _hold(u: Understanding | None, now: float) -> None:
    with _pending_lock:
        _pending.clear()
        if u is not None:
            _pending.update(u=u, at=now)


def merge(new: Understanding, old: Understanding | None) -> Understanding:
    """The new sentence, with what it left out taken from the one before."""
    if old is None:
        return new
    got = new
    if "company" in new.missing and not new.ambiguous and (old.ticker or old.ambiguous):
        got = replace(got, ticker=old.ticker, company=old.company, ambiguous=list(old.ambiguous))
    if new.scale is None and old.scale is not None:
        got = replace(got, scale=old.scale)
    if not new.where and old.where:
        got = replace(got, where=old.where)
    missing = []
    if not got.ticker and not got.ambiguous:
        missing.append("company")
    if got.scale is None:
        missing.append("scale")
    return replace(got, missing=missing, heard=new.heard)


def question(u: Understanding, names: dict[str, str]) -> str | None:
    """What to ask for, or None when the request is complete."""
    if u.ambiguous:
        options = [f"{t} ({names[t]})" if t in names else t for t in u.ambiguous[:3]]
        said = " or ".join([", ".join(options[:-1]), options[-1]]) if len(options) > 1 else options[0]
        return f"Did you mean {said}? Say the one you meant. {LISTENING}"
    if "company" in u.missing and "scale" in u.missing:
        return f"I didn't catch a company or a scale. Say both, like Palantir half. {LISTENING}"
    if "company" in u.missing:
        return f"Which company{' at ' + u.scale if u.scale and u.scale != 'as is' else ''}? {LISTENING}"
    if "scale" in u.missing:
        return f"I heard {u.company or u.ticker} but no scale. Say the scale, like half or daily. {LISTENING}"
    return None


def command(u: Understanding) -> str:
    """The vocabulary's command for a complete request (see :func:`patron.tool_for`)."""
    return f"set {u.ticker} | {'' if u.scale == 'as is' else u.scale}"


def respond(audio: bytes, content_type: str | None = None, *,
            decode: Callable[..., bytes] = hearing.decode,
            transcribe: Callable[[bytes, str | None], str] = hearing.transcribe,
            send: Callable[[str, str], str] = patron.send,
            rows: list[dict] | None = None,
            known: list[str] | None = None,
            now: Callable[[], float] = time.monotonic) -> str:
    """Hear one recording and answer it; see the module doc."""
    try:
        rows = registry.load() if rows is None else rows
    except Exception:  # noqa: BLE001 - without the registry no company can be named
        return ERR + "I can't look up companies right now. Try again in a minute."
    lately = recent.load()
    places = displays.current() if known is None else known
    try:
        heard = transcribe(decode(audio, content_type), hearing.prompt(lately, rows, places))
    except hearing.HearingError as exc:
        requestlog.request("hear", "hear", "", ERR + str(exc))
        return ERR + str(exc)
    except Exception as exc:  # noqa: BLE001 - never a stack trace spoken aloud
        requestlog.request("hear", "hear", "", ERR + f"hearing failed: {type(exc).__name__}")
        return ERR + "I couldn't hear that. Try again."
    requestlog.heard("hear", heard)
    if not heard:
        return f"I didn't hear anything. Say a company and a scale. {LISTENING}"

    at = now()
    got = merge(understand(heard, recent=lately, displays=places, rows=rows), _held(at))
    names = {t: resolve.spoken_name(r["n"]) for r in rows if (t := r["t"]) in got.ambiguous}
    ask = question(got, names)
    if ask:
        _hold(got, at)
        requestlog.request("hear", "ask", got.where or "", "")
        return ask
    _hold(None, at)
    return send(command(got), got.where or "")
