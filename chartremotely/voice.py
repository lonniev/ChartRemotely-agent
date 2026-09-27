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
"Palantir half" then "PLTR" after "Did you mean PLTR or PLTX?". Speech gets
:data:`VOICE_TRIES` chances, as Siri gives: the last spoken miss asks its
question in the text box instead, with what was heard so far still held.

When nothing usable was recorded - no microphone, silence, noise - the
reply is not a sentence but :data:`TYPE` and a prompt. The Shortcut shows
that prompt in a one-line text box and posts what is typed back as
``{"said": ...}`` (:func:`respond_typed`), which is understood the same way
and makes the same priced call. A typed request that is missing something
is asked for with another :data:`TYPE` reply, so a typist is never asked to
speak. One Shortcut, then: talk, or type when it asks.

Never raises: every path returns a sentence to speak or a box to show.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import replace

from . import displays, hearing, patron, recent, registry, requestlog, resolve
from .understand import Understanding, understand

ERR = "ERR "
#: The machine marker for "show a text box": the rest of the reply is its prompt.
TYPE = "TYPE:"
TYPE_PROMPT = "Type your request, e.g. Palantir half on mac mini"
#: Longest typed request read; a sentence is a few words.
TYPED_MAX = 200
#: The word every follow-up question ends with; the Shortcut listens again on it.
LISTENING = "I'm listening."
FOLLOW_UP_SECONDS = 45.0
#: Spoken tries at one request before the question moves to the text box.
VOICE_TRIES = 3

_pending: dict = {}
_pending_lock = threading.Lock()


def _held(now: float) -> tuple[Understanding | None, int]:
    """The request being completed and how many spoken tries it has had."""
    with _pending_lock:
        got = _pending.get("u")
        if got and now - _pending.get("at", 0.0) <= FOLLOW_UP_SECONDS:
            return got, _pending.get("misses", 0)
        _pending.clear()
        return None, 0


def _hold(u: Understanding | None, now: float, misses: int = 0) -> None:
    with _pending_lock:
        _pending.clear()
        if u is not None:
            _pending.update(u=u, at=now, misses=misses)


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


def question(u: Understanding, names: dict[str, str], verb: str = "Say") -> str | None:
    """What to ask for, or None when the request is complete. ``verb`` is Say or Type."""
    if u.ambiguous:
        options = [f"{t} ({names[t]})" if t in names else t for t in u.ambiguous[:3]]
        said = " or ".join([", ".join(options[:-1]), options[-1]]) if len(options) > 1 else options[0]
        return f"Did you mean {said}? {verb} the one you meant."
    if "company" in u.missing and "scale" in u.missing:
        return f"I didn't catch a company or a scale. {verb} both, like Palantir half."
    if "company" in u.missing:
        return f"Which company{' at ' + u.scale if u.scale and u.scale != 'as is' else ''}?"
    if "scale" in u.missing:
        return f"I heard {u.company or u.ticker} but no scale. {verb} the scale, like half or daily."
    return None


def typing(prompt: str = TYPE_PROMPT) -> str:
    """The reply that makes the Shortcut show a text box with ``prompt``."""
    return TYPE + prompt


def command(u: Understanding) -> str:
    """The vocabulary's command for a complete request (see :func:`patron.tool_for`)."""
    return f"set {u.ticker} | {'' if u.scale == 'as is' else u.scale}"


def _answer(text: str, rows: list[dict], lately: list[str], places: list[str],
            send: Callable[[str, str], str], at: float, typed: bool) -> str:
    """Understand one request, spoken or typed: ask for what is missing, or send it."""
    old, misses = _held(at)
    got = merge(understand(text, recent=lately, displays=places, rows=rows), old)
    names = {t: resolve.spoken_name(r["n"]) for r in rows if (t := r["t"]) in got.ambiguous}
    misses = misses if typed else misses + 1
    typed = typed or misses >= VOICE_TRIES
    ask = question(got, names, "Type" if typed else "Say")
    if ask:
        _hold(got, at, misses)
        requestlog.request("type" if typed else "hear", "ask", got.where or "", "")
        return typing(ask) if typed else f"{ask} {LISTENING}"
    _hold(None, at)
    return send(command(got), got.where or "")


def respond(audio: bytes, content_type: str | None = None, *,
            decode: Callable[..., bytes] = hearing.decode,
            usable: Callable[[bytes], bool] = hearing.usable,
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
        pcm = decode(audio, content_type)
        if not usable(pcm):
            raise hearing.Unheard("silence")
        heard = transcribe(pcm, hearing.prompt(lately, rows, places))
    except hearing.Unheard as exc:
        requestlog.request("hear", "hear", "", ERR + f"unheard: {exc}")
        return typing()
    except hearing.HearingError as exc:
        requestlog.request("hear", "hear", "", ERR + str(exc))
        return ERR + str(exc)
    except Exception as exc:  # noqa: BLE001 - never a stack trace; typing still works
        requestlog.request("hear", "hear", "", ERR + f"hearing failed: {type(exc).__name__}")
        return typing()
    requestlog.heard("hear", heard)
    if hearing.filler(heard):
        return typing()
    return _answer(heard, rows, lately, places, send, now(), typed=False)


def respond_typed(text: str, *,
                  send: Callable[[str, str], str] = patron.send,
                  rows: list[dict] | None = None,
                  known: list[str] | None = None,
                  now: Callable[[], float] = time.monotonic) -> str:
    """Answer one typed request exactly as a spoken one; blank asks for the typing box."""
    said = " ".join("".join(c if c.isprintable() else " " for c in str(text or ""))[:TYPED_MAX].split())
    if not said:
        return typing()
    try:
        rows = registry.load() if rows is None else rows
    except Exception:  # noqa: BLE001 - without the registry no company can be named
        return ERR + "I can't look up companies right now. Try again in a minute."
    requestlog.heard("type", said)
    places = displays.current() if known is None else known
    return _answer(said, rows, recent.load(), places, send, now(), typed=True)
