"""Turn a spoken security name into a ticker.

Speech recognition is the weak link in voice-driven charting. Dictation
matches against the whole English language, so "Palantir" arrives as
"Volunteer" and "Qualcomm" as "Callalon". This module repairs what it can
without ever inventing an answer: every tier is gated so that noise is
refused rather than mapped confidently onto some unrelated company.

Matching runs in tiers, highest score wins:

    1000  the query IS a ticker
     900  exact company name
     800  the name starts with the query
     700  every spoken word appears in the name
     650  the query COVERS the name, plus extra words   ("john deere")
     600  consonant skeletons match                     ("volunteer")
     400  fuzzy, as a last resort
"""

from __future__ import annotations

import difflib
import re

__all__ = ["candidates", "normalize", "phonetic", "resolve", "spelled"]

# Corporate furniture, stripped from both sides before comparison. "and"
# is here because "&" normalises to it, so DEERE & CO reduces to "deere".
SUFFIXES = {
    "inc", "incorporated", "corp", "corporation", "co", "company", "ltd",
    "limited", "plc", "lp", "llc", "holdings", "holding", "group", "trust",
    "the", "sa", "nv", "ag", "adr", "ads", "class", "a", "b", "c", "etf",
    "fund", "common", "stock", "shares", "new", "series", "and",
}

# Filler, pronouns and contraction fragments. Without these the phonetic
# tier maps conversation onto companies: "whatever" codes like DOV, and
# "i don t" codes exactly like "at and t".
STOPWORDS = {
    "the", "a", "an", "and", "um", "uh", "er", "hey", "hi", "ok", "okay",
    "what", "who", "how", "why", "when", "yes", "no", "please", "thanks",
    "siri", "show", "me", "go", "to", "open", "chart", "stock", "symbol",
    "it", "that", "this", "is", "whatever", "something", "nothing",
    "anything", "everything", "nevermind", "never", "mind", "forget",
    "cancel", "stop", "quit", "wait", "hold", "on", "hmm", "hello",
    "sorry", "maybe", "dunno", "know", "guess", "again", "i", "you", "we",
    "my", "your", "don", "dont", "doesn", "doesnt", "can", "cant", "wont",
    "im", "ive", "id", "let", "just", "well", "yeah", "yep", "nope", "like",
}

# Transcripts that discard the consonant skeleton entirely, so no algorithm
# recovers them, plus renames the SEC registry has not caught up with.
# Grow this only from transcripts actually observed in the wild.
ALIASES = {
    "kuehn": "COIN",        # nasal "Coin"
    "koon": "COIN",
    "pierre": "PLTR",       # Siri's web-search guess for "Palantir"
    "callalon": "QCOM",     # nasal "Qualcomm"
    "ge aerospace": "GE",   # still filed as GENERAL ELECTRIC CO
    "ge aviation": "GE",
}

# Soundex-style consonant coding: vowels carry almost no information in a
# mis-hearing, consonants carry nearly all of it.
_SOUNDEX = {
    **dict.fromkeys("bfpv", "1"), **dict.fromkeys("cgjkqsxz", "2"),
    **dict.fromkeys("dt", "3"), "l": "4",
    **dict.fromkeys("mn", "5"), "r": "6",
}

LETTER_WORDS = {
    "ay": "a", "eh": "a", "bee": "b", "be": "b", "see": "c", "sea": "c",
    "dee": "d", "de": "d", "ee": "e", "eff": "f", "ef": "f", "gee": "g",
    "aitch": "h", "haitch": "h", "eye": "i", "aye": "i", "jay": "j",
    "kay": "k", "el": "l", "ell": "l", "em": "m", "en": "n", "oh": "o",
    "owe": "o", "pee": "p", "pea": "p", "cue": "q", "queue": "q", "ar": "r",
    "are": "r", "arr": "r", "ess": "s", "es": "s", "tee": "t", "tea": "t",
    "you": "u", "yoo": "u", "vee": "v", "doubleyou": "w", "ex": "x",
    "ecks": "x", "why": "y", "wye": "y", "zee": "z", "zed": "z",
}

MIN_PHONETIC = 3          # shorter skeletons collide with everything
PHONETIC_MIN_RATIO = 0.45  # a skeleton match must also look plausible
MIN_PREFIX = 4
MIN_FUZZY = 5
FUZZY_FLOOR = 0.82
NAME_COVERAGE = 0.6       # how much of the company name the query must cover


def normalize(text: str) -> str:
    t = text.lower().replace("&", " and ")
    return " ".join(re.sub(r"[^a-z0-9 ]+", " ", t).split())


def strip_suffixes(norm: str) -> str:
    return " ".join(w for w in norm.split() if w not in SUFFIXES) or norm


def phonetic(text: str) -> str:
    """Consonant skeleton. 'palantir' and 'volunteer' both give '14536'."""
    out: list[str] = []
    last = ""
    for ch in text.lower():
        code = _SOUNDEX.get(ch)
        if code and code != last:
            out.append(code)
        if ch.isalpha():
            last = code or ""
    return "".join(out)


def deinflect(word: str) -> set[str]:
    """Dictation returns inflected words: 'volunteered' for 'Palantir'."""
    forms = {word}
    for suf in ("ing", "ed", "es", "s"):
        if word.endswith(suf) and len(word) - len(suf) >= 5:
            forms.add(word[: -len(suf)])
    return forms


def spelled(query: str) -> str | None:
    """'p l t r' / 'pee ell tee are' / 'P-L-T-R' -> 'PLTR', else None."""
    raw = re.sub(r"[^a-z0-9 ]+", " ", query.lower()).replace("double u", "doubleyou")
    toks = raw.split()
    if not 2 <= len(toks) <= 6:
        return None
    out = []
    for t in toks:
        if len(t) == 1 and t.isalpha():
            out.append(t)
        elif t in LETTER_WORDS:
            out.append(LETTER_WORDS[t])
        else:
            return None
    return "".join(out).upper()


def candidates(query: str, rows: list[dict]) -> list[tuple[float, str, str]]:
    """Score every row. `rows` are {"t": ticker, "n": name, "r": rank}."""
    q = normalize(query)
    qs = strip_suffixes(q)
    tokens = set(qs.split()) - STOPWORDS
    if not tokens:
        return []
    qs = " ".join(w for w in qs.split() if w not in STOPWORDS) or qs
    qtokens = tokens

    forms = set()
    for base in (q, qs):
        forms |= deinflect(base)
    skeletons = {p for p in (phonetic(f) for f in forms) if len(p) >= MIN_PHONETIC}

    out = []
    for row in rows:
        ticker, name, rank = row["t"], row["n"], row.get("r", 0)
        n = normalize(name)
        ns = strip_suffixes(n)
        heads = {ns, ns.split()[0]} if ns else {""}

        if q == ticker.lower():
            score = 1000.0
        elif qs == ns or q == n:
            score = 900.0
        elif len(qs) >= MIN_PREFIX and (ns.startswith(qs) or n.startswith(q)):
            score = 800 - min(len(ns) - len(qs), 99) * 0.1
        elif qtokens <= set(ns.split()) and all(len(t) >= 3 for t in qtokens):
            score = 700 - min(len(ns.split()) - len(qtokens), 99) * 0.5
        elif ns and (overlap := qtokens & set(ns.split())):
            # The query CONTAINS the company name plus extras: "john deere"
            # for DEERE & CO. Requiring the query to cover most of the NAME
            # keeps a single shared word from winning - otherwise "in video"
            # matches Video River Networks.
            cov = len(overlap) / max(len(set(ns.split())), 1)
            strong = any(len(w) >= 4 and w not in SUFFIXES for w in overlap)
            if not strong or cov < NAME_COVERAGE:
                continue
            score = 650 + cov * 60
        elif skeletons and any(phonetic(h) in skeletons for h in heads):
            ratio = max(difflib.SequenceMatcher(None, a, h).ratio()
                        for a in forms for h in heads)
            if ratio < PHONETIC_MIN_RATIO:
                continue
            score = 600 + ratio * 60
        elif len(qs) >= MIN_FUZZY:
            ratio = max(difflib.SequenceMatcher(None, qs, h).ratio() for h in heads)
            if ratio < FUZZY_FLOOR:
                continue
            score = 400 + ratio * 100
        else:
            continue

        out.append((score - rank * 0.002, ticker, name))

    out.sort(key=lambda x: -x[0])
    return out


def resolve(query: str, rows: list[dict]) -> str | None:
    """Best ticker for a spoken query, or None when nothing is convincing."""
    letters = spelled(query)
    if letters and any(r["t"] == letters for r in rows):
        return letters
    direct = ALIASES.get(normalize(query))
    if direct:
        return direct
    ranked = candidates(query, rows)
    return ranked[0][1] if ranked else None
