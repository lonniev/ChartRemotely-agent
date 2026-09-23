"""Spoken time-frame vocabulary. Pure logic, no macOS dependency.

Kept apart from the driver so it can be imported anywhere - by CI on Linux,
and by the operator, which needs to validate a spoken phrase before it has
any agent to send it to.

The mnemonics are chosen for phonetic distance rather than literal
accuracy. Digits are the worst thing to say to a recogniser: "fifteen" and
"fifty" collide, "one" and "won" collide. None of these ten do.
"""

from __future__ import annotations

import re

MNEMONIC = {
    "1d1m": "minute", "5d5m": "scalp", "5d15m": "quarter", "10d30m": "half",
    "20d1h": "hourly", "180d4h": "swing", "1y1d": "daily", "3yw": "weekly",
    "1d133t": "ticks", "1d10t": "micro",
}

ALIAS = {
    "minute": "1d1m", "scalp": "5d5m", "quarter": "5d15m", "half": "10d30m",
    "hourly": "20d1h", "swing": "180d4h", "daily": "1y1d", "weekly": "3yw",
    "ticks": "1d133t", "micro": "1d10t",
    # variants people actually say
    "tick": "1d133t", "ten tick": "1d10t", "quarter hour": "5d15m",
    "half hour": "10d30m", "hour": "20d1h", "day": "1y1d", "week": "3yw",
    "intraday": "1d1m", "swing trade": "180d4h",
}

AS_IS = {"as is", "as-is", "asis", "same", "leave it", "unchanged",
         "no change", "keep it", "current", "skip", "none", ""}

_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
          "seven": 7, "eight": 8, "nine": 9, "ten": 10, "fifteen": 15,
          "twenty": 20, "thirty": 30, "sixty": 60, "ninety": 90}
_UNIT = {"d": "d", "day": "d", "days": "d", "daily": "d", "y": "y",
         "year": "y", "years": "y", "w": "w", "week": "w", "weekly": "w",
         "weeks": "w", "m": "m", "min": "m", "minute": "m", "minutes": "m",
         "h": "h", "hour": "h", "hours": "h", "t": "t", "tick": "t",
         "ticks": "t"}


def canon(text: str) -> str:
    """'5 D : 5m' and 'five day five minute' both give '5d5m'.

    Returns "" when nothing parses. Callers MUST treat that as a refusal:
    every string ends with "", so a loose endswith match against menu
    labels would otherwise select whichever preset came first.
    """
    s = re.sub(r"[^a-z0-9 ]", " ", text.lower().replace(":", " ").replace("/", " "))
    for word, n in _WORDS.items():
        s = re.sub(rf"\b{word}\b", str(n), s)
    s = re.sub(r"(\d)\s*([a-z])", r"\1\2", s)
    out = []
    for token in s.split():
        m = re.match(r"^(\d+)([a-z]+)$", token)
        if m and m.group(2) in _UNIT:
            out.append(m.group(1) + _UNIT[m.group(2)])
        elif token in _UNIT and out:
            out.append(_UNIT[token])
    return "".join(out)


def to_code(phrase: str) -> str:
    return ALIAS.get(phrase.lower().strip(), canon(phrase))


def mnemonic_for(phrase: str) -> str | None:
    """The word we say back, or None if the phrase names no preset."""
    return MNEMONIC.get(to_code(phrase))


def spoken_options() -> str:
    """What to read aloud when someone says something unrecognised."""
    return ", ".join(MNEMONIC.values())
