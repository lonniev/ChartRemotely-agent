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

from . import registry, resolve, scales, symbol, timeframe, window

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
    """Put a ticker on the chart, optionally at a given scale.

    Degrades deliberately: an unparseable scale leaves the chart alone and
    says which scale it is actually on, so the answer is never ambiguous to
    someone who cannot see the screen.
    """
    ticker = ticker.strip().replace(" ", "")
    if not ticker:
        return ERR + "No symbol to show."
    try:
        symbol.show(ticker)
    except Exception as exc:
        return ERR + _short(exc)

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
        return f"Showing {ticker} at {word}. Good luck."
    try:
        _, current = timeframe.current()
        return f"Showing {ticker} at {current}, as is. Good luck."
    except Exception:
        return f"Showing {ticker}. Good luck."


def cmd_read() -> str:
    """Report the chart's current symbol and scale."""
    try:
        ticker = symbol.current()
        _, word = timeframe.current()
        return f"{ticker} at {word}"
    except Exception as exc:
        return ERR + _short(exc)


def dispatch(request: str) -> str:
    """Route one request. Anything unrecognised is treated as a company name.

    The entire surface:

        resolve <spoken name>              -> TICKER | ERR
        scale   <spoken time frame>        -> mnemonic | ERR
        set     <TICKER> | <time frame>    -> spoken summary
        read                               -> current symbol and scale
        <spoken name>                      -> resolve, then set
    """
    request = (request or "").strip()
    if not request:
        return ERR + "I didn't catch that."

    verb, _, rest = request.partition(" ")
    verb = verb.lower()

    if verb == "resolve":
        return cmd_resolve(rest)
    if verb == "scale":
        return cmd_scale(rest)
    if verb == "read":
        return cmd_read()
    if verb == "set":
        ticker, sep, scale = rest.partition("|")
        return cmd_set(ticker, scale if sep else "")

    # Bare name: resolve and show it.
    ticker = cmd_resolve(request)
    if ticker.startswith(ERR):
        return ticker
    return cmd_set(ticker)
