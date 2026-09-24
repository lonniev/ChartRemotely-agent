"""The complete command vocabulary. This file is the security boundary.

Everything a caller can ask the agent to do is in the dispatch table below.
There is no command that opens an order ticket, submits a trade, moves
money, or reads an account. Adding one means editing this file - in public,
in this repository - which is the point.

Two rules the callers depend on:

* **Never raise.** Every path returns text. The operator relays this to a
  Shortcut, and a Shortcut treats a non-zero exit or an exception as a hard
  failure, aborting before it can read the message.
* **Keep it short.** These strings get read aloud. Nobody wants a stack
  trace spoken at them from across the room.
"""

from __future__ import annotations

from . import guilock, registry, resolve, scales, snapshot, symbol, timeframe, window
from .answer import Answer

ERR = "ERR "


def _short(text: str, limit: int = 120) -> str:
    return str(text).splitlines()[0][:limit] if text else "something went wrong"


def cmd_resolve(spoken: str) -> str:
    """A spoken company name, to a ticker."""
    if not spoken.strip():
        return ERR + "I didn't catch a company name."
    try:
        ticker = resolve.resolve(spoken, registry.load())
    except Exception as exc:
        return ERR + _short(exc)
    return ticker or ERR + f"no match for {spoken!r}"


def cmd_scale(spoken: str) -> str:
    """A spoken time frame, to a mnemonic - without touching the chart."""
    phrase = spoken.strip()
    if phrase.lower() in scales.AS_IS:
        return "as is"
    word = scales.mnemonic_for(phrase)
    if word:
        return word
    return ERR + f"You say {scales.spoken_options()}."


def cmd_set(ticker: str, scale: str = "") -> str:
    """Put a ticker on the chart; see :func:`set_chart`. Returns only the words."""
    return set_chart(ticker, scale).reply


def set_chart(ticker: str, scale: str = "") -> Answer:
    """Put a ticker on the chart, optionally at a given scale.

    Degrades deliberately: an unparseable scale leaves the chart alone and
    says which scale it is actually on, so the answer is never ambiguous to
    someone who cannot see the screen.
    """
    ticker = ticker.strip().replace(" ", "")
    if not ticker:
        return Answer(ERR + "No symbol to show.")
    try:
        symbol.show(ticker)
    except Exception as exc:
        return Answer(ERR + _short(exc))
    shown = symbol.to_ticker(ticker)

    word = None
    if scale.strip() and scale.strip().lower() not in scales.AS_IS:
        try:
            _, word = timeframe.set_scale(scale)
        except Exception:
            word = None

    # Uncover the chart: a voice answer is only useful if the screen shows it.
    try:
        window.clear()
    except Exception:
        pass

    if word:
        return Answer(f"Showing {ticker} at {word}. Good luck.", shown)
    try:
        _, current = timeframe.current()
        return Answer(f"Showing {ticker} at {current}, as is. Good luck.", shown)
    except Exception:
        return Answer(f"Showing {ticker}. Good luck.", shown)


def cmd_read() -> str:
    """Report the chart's current symbol and scale."""
    try:
        ticker = symbol.current()
        _, word = timeframe.current()
        return f"{ticker} at {word}"
    except Exception as exc:
        return ERR + _short(exc)


def cmd_snapshot() -> str:
    """A picture of the chart pane, so a caller far away can see it."""
    try:
        return snapshot.as_reply(snapshot.shrink(window.capture()))
    except Exception as exc:
        return ERR + _short(exc)


def dispatch(request: str) -> str:
    """Route one request and return only its words; see :func:`answer`."""
    return answer(request).reply


def answer(request: str) -> Answer:
    """Route one request. Anything unrecognised is treated as a company name.

    The Answer carries the symbol a successful change put on the chart, so
    the picture that follows is labelled from data, not from the reply text.

    The entire surface:

        resolve <spoken name>              -> TICKER | ERR
        scale   <spoken time frame>        -> mnemonic | ERR
        set     <TICKER> | <time frame>    -> spoken summary
        read                               -> current symbol and scale
        snapshot                           -> data:image/jpeg;base64,... | ERR
        <spoken name>                      -> resolve, then set
    """
    request = (request or "").strip()
    if not request:
        return Answer(ERR + "I didn't catch that.")

    verb, _, rest = request.partition(" ")
    verb = verb.lower()

    if verb == "resolve":
        return Answer(cmd_resolve(rest))
    if verb == "scale":
        return Answer(cmd_scale(rest))
    if verb == "read":
        return _driving(lambda: Answer(cmd_read()))
    if verb == "snapshot":
        return _driving(lambda: Answer(cmd_snapshot()))
    if verb == "set":
        ticker, sep, scale = rest.partition("|")
        return _driving(lambda: set_chart(ticker, scale if sep else ""))

    # Bare name: resolve and show it.
    ticker = cmd_resolve(request)
    if ticker.startswith(ERR):
        return Answer(ticker)
    return _driving(lambda: set_chart(ticker))


def _driving(command) -> Answer:
    """Run one command that drives the chart, never alongside another."""
    try:
        with guilock.driving():
            return command()
    except guilock.Busy as exc:
        return Answer(ERR + str(exc))
