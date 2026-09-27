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
    "a quarter hour": "5d15m", "quarter of an hour": "5d15m",
    "a quarter of an hour": "5d15m",
    "half hour": "10d30m", "half an hour": "10d30m", "half a hour": "10d30m",
    "hour": "20d1h", "an hour": "20d1h", "a hour": "20d1h",
    "day": "1y1d", "a day": "1y1d", "week": "3yw", "a week": "3yw",
    "a minute": "1d1m", "intraday": "1d1m", "swing trade": "180d4h",
}

#: A preset by its bar size alone: "thirty minutes" canon's to "30m", which is
#: no preset's full code, but it is exactly one preset's bar.
BAR = {
    "1m": "1d1m", "5m": "5d5m", "15m": "5d15m", "30m": "10d30m",
    "1h": "20d1h", "60m": "20d1h", "4h": "180d4h", "240m": "180d4h",
    "1d": "1y1d", "1w": "3yw", "w": "3yw", "133t": "1d133t", "10t": "1d10t",
}

#: Words said around a scale that name no scale: "at half scale", "the daily chart".
FILLER = {"at", "on", "the", "scale", "time", "frame", "timeframe", "chart", "bars",
          "bar", "candles", "candle", "please", "use", "make", "it", "set", "to"}

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


#: Every word a spoken scale can be made of. A span of an utterance names a
#: scale only when all its words are these, so "apple one day" is never
#: read as "one day" with "apple" ignored.
SCALE_WORDS = ({w for phrase in ALIAS for w in phrase.split()} | set(_WORDS) | set(_UNIT)
               | FILLER | {"an", "of"})


def is_scale_word(word: str) -> bool:
    """True for a word :func:`preset` could use: see :data:`SCALE_WORDS`."""
    return word in SCALE_WORDS or bool(re.fullmatch(r"\d+[a-z]*(\d+[a-z]*)*", word))


def _words(phrase: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", phrase.lower().replace("-", " ")).split())


def preset(phrase: str) -> str | None:
    """The preset code a phrase names exactly, or None. No guessing.

    A mnemonic or an alias ("half an hour"), a full code ("10 D 30m"), or a
    bar size alone ("thirty minutes", "4h", "one day"), with filler such as
    "at ... scale" ignored.
    """
    said = _words(phrase)
    bare = " ".join(w for w in said.split() if w not in FILLER)
    for form in (said, bare):
        if form in ALIAS:
            return ALIAS[form]
        if form.replace(" ", "") in MNEMONIC:
            return form.replace(" ", "")
    code = canon(bare)
    if code in MNEMONIC:
        return code
    bar = re.search(r"(\d*[a-z])$", code)
    if bar and re.fullmatch(r"\d*[a-z]", code):
        return BAR.get(bar.group(1))
    return None


def sound_key(word: str) -> str:
    """A deliberately crude phonetic key for one word.

    ph/gh/v sound as f, c/k/q as k; after the first letter the vowels and
    h/w/y go; repeats collapse. "half", "halve", "haff" and "alpha" all land
    within one edit of "hlf".
    """
    w = re.sub(r"[^a-z]", "", word.lower()).replace("ph", "f").replace("gh", "f")
    w = w.translate(str.maketrans("vcq", "fkk"))
    if not w:
        return ""
    out = [w[0]]
    for ch in w[1:]:
        if ch in "aeiouhwy" or ch == out[-1]:
            continue
        out.append(ch)
    return "".join(out)


def _distance(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


KEYS = {sound_key(word): word for word in MNEMONIC.values()}


def sounds_like(word: str) -> str | None:
    """The one mnemonic a mis-heard word is within an edit of, else None.

    Two candidates within reach is a refusal, not a coin toss: "hal" is one
    edit from half, hourly and daily, so it names none of them.
    """
    if not word.isalpha():
        return None
    key = sound_key(word)
    if len(key) < 2:
        return None
    near = {mn for k, mn in KEYS.items() if _distance(key, k) <= 1}
    return near.pop() if len(near) == 1 else None


def to_code(phrase: str) -> str:
    """The preset code for a phrase, else its raw canon() (possibly "")."""
    return preset(phrase) or canon(phrase)


def mnemonic_for(phrase: str) -> str | None:
    """The word we say back, or None if the phrase names no preset.

    Exact first (:func:`preset`); a single mis-heard word falls back to
    :func:`sounds_like`.
    """
    code = preset(phrase)
    if code:
        return MNEMONIC[code]
    words = [w for w in _words(phrase).split() if w not in FILLER]
    return sounds_like(words[0]) if len(words) == 1 else None


def spoken_options() -> str:
    """What to read aloud when someone says something unrecognised."""
    return ", ".join(MNEMONIC.values())
