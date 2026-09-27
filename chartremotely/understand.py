"""One spoken request, understood: which company, what scale, where.

Siri's dictation (and, next, a Whisper transcription of the whole
utterance) matches against all of English. What we need back is small: a
company from the SEC list, one of ten time frames, and the name of a
display. This module takes the text as heard - "Palantir half on mac mini",
"shop thirty minutes", "GE daily on the studio", "apple as is on desk" - and
recovers those three, refusing rather than guessing.

It works right to left, the way people say it:

1. **Where.** The last "on / at / to (the) <name>" whose name loosely matches
   a known display ("on" is taken even when it matches none - the operator
   re-matches every name authoritatively and says which it knows), or a
   trailing display name said without one.
2. **Scale.** A time-frame phrase ending what is left ("half", "thirty
   minutes", "half an hour", "four hours", "as is"), or one mis-heard last
   word that sounds like exactly one mnemonic ("have", "alf"). Words that
   belong to the company's own name are never taken: "super micro" is Super
   Micro Computer, not Super at micro.
3. **Company.** Whatever remains, through :func:`resolve.decide` with the
   symbols charted lately as a prior. Too close to call is an answer too:
   the options, so the reply can ask.

Pure and deterministic: no LLM, no network beyond the cached SEC registry.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import resolve, scales

__all__ = ["Understanding", "understand"]

#: Words that introduce a display. "in" is not one: "in video" is Nvidia.
PREPOSITIONS = {"on", "at", "to", "onto"}
#: Of these, only "on" is taken without a known display: "at" and "to" also
#: begin company names ("at and t").
TRUSTED = {"on", "onto"}
ARTICLES = {"the", "my", "our", "a"}
AS_IS = scales.AS_IS - {"", "none", "current", "skip"}
MAX_SCALE_WORDS = 4


@dataclass
class Understanding:
    """What one utterance asked for.

    ``ticker``: the symbol, when the company is clear. ``company``: its name
    as the registry has it when resolved, else the words taken as the
    company (None when there were none). ``scale``: a mnemonic or "as is",
    None when none was said. ``where``: the display as said, for the
    operator to match. ``ambiguous``: ticker options when the company was
    too close to call. ``heard``: the text as given. ``missing``: what still
    has to be asked for, of "company" and "scale".
    """

    ticker: str | None
    company: str | None
    scale: str | None
    where: str | None
    ambiguous: list[str] = field(default_factory=list)
    heard: str = ""
    missing: list[str] = field(default_factory=list)


def _tokens(text: str) -> list[tuple[str, str]]:
    """(as said, normalised) pairs; punctuation that is only punctuation goes."""
    spaced = re.sub(r"[&/\-]", lambda m: " and " if m.group() == "&" else " ", text)
    out = []
    for raw in spaced.split():
        said = raw.strip(".,;:!?\"'()[]")
        norm = re.sub(r"[^a-z0-9]", "", said.lower())
        if norm:
            out.append((said, norm))
    return out


def _key(words: list[str]) -> str:
    return "".join(words)


def _names_display(words: list[str], displays: list[str], *, strict: bool = False) -> bool:
    """Do these words loosely name one of ``displays``? A cheap, local mirror
    of the operator's matching - it decides only how the sentence splits."""
    if not words:
        return False
    k = _key(words)
    for display in displays:
        dwords = [w for w in re.sub(r"[^a-z0-9]+", " ", display.lower()).split() if w]
        dk = _key(dwords)
        if not dk:
            continue
        if k == dk or set(words) == set(dwords):
            return True
        sound = resolve.phonetic(k)
        if len(sound) >= 3 and sound == resolve.phonetic(dk):
            return True
        if strict:
            continue
        if set(words) <= set(dwords) or (len(k) >= 3 and dk.startswith(k)):
            return True
        long = [w for w in words if len(w) >= 3]
        if long and all(any(dw.startswith(w) for dw in dwords) for w in long):
            return True
    return False


def _scale_span(norms: list[str]) -> tuple[int, str] | None:
    """(start, scale) for a time-frame phrase that ends ``norms``, longest first."""
    for n in range(min(MAX_SCALE_WORDS, len(norms)), 0, -1):
        span = norms[-n:]
        phrase = " ".join(span)
        if phrase in AS_IS:
            return len(norms) - n, "as is"
        if all(scales.is_scale_word(w) for w in span):
            code = scales.preset(phrase)
            if code:
                return len(norms) - n, scales.MNEMONIC[code]
    return None


def _split_where(toks: list[tuple[str, str]], displays: list[str], owns=lambda words: False):
    """(tokens left, where as said) - see the module doc, step 1.

    ``owns(words)`` says whether words said with no preposition belong to
    the company instead: "the trade desk" is The Trade Desk, not "desk".
    """
    norms = [n for _, n in toks]
    for i in range(len(toks) - 1, 0, -1):
        if norms[i] not in PREPOSITIONS:
            continue
        j = i + 1
        while j < len(toks) and norms[j] in ARTICLES:
            j += 1
        tail = toks[j:]
        if not tail:
            continue
        tnorms = [n for _, n in tail]
        # Longest run of the tail that names a display; what follows it goes
        # back for the scale ("on mac mini half").
        for end in range(len(tail), 0, -1):
            if _names_display(tnorms[:end], displays):
                return toks[:i] + tail[end:], " ".join(s for s, _ in tail[:end])
        if norms[i] not in TRUSTED and displays:
            continue
        scale = _scale_span(tnorms)
        keep = tail[:scale[0]] if scale else tail
        if not keep:
            continue  # "at half": a scale, not a place
        rest = tail[scale[0]:] if scale else []
        return toks[:i] + rest, " ".join(s for s, _ in keep)
    # A display named with no preposition, at the very end: "apple daily
    # studio" exactly, or loosely after an article: "amazon the mini".
    for start in range(1, len(toks)):
        words = norms[start:]
        if words[0] in ARTICLES:
            continue
        loose = norms[start - 1] in ARTICLES
        if _names_display(words, displays, strict=not loose) and not owns(words):
            cut = start
            while cut > 1 and norms[cut - 1] in ARTICLES:
                cut -= 1
            return toks[:cut], " ".join(s for s, _ in toks[start:])
    return toks, None


def _name_of(ticker: str | None, rows: list[dict]) -> str | None:
    return next((r["n"] for r in rows if r["t"] == ticker), None) if ticker else None


def _own_words(words: list[str], ticker: str | None, rows: list[dict]) -> bool:
    """Are these words part of the named company's own name?"""
    name = _name_of(ticker, rows)
    return bool(name) and set(words) <= set(resolve.normalize(name).split())


def understand(text: str, *, recent: list[str], displays: list[str],
               rows: list[dict] | None = None) -> Understanding:
    """Parse one utterance; see the module doc.

    ``recent``: symbols charted lately, most recent first (:mod:`recent`).
    ``displays``: the owner's display names, to split off "where". ``rows``:
    the SEC registry, loaded from its cache when not given.
    """
    if rows is None:
        from . import registry
        rows = registry.load()
    heard = " ".join((text or "").split())
    toks = _tokens(heard)
    said = resolve.decide(" ".join(n for _, n in toks), rows, recent) if toks else None
    toks, where = _split_where(
        toks, displays, lambda words: _own_words(words, said and said.ticker, rows))
    norms = [n for _, n in toks]

    scale = None
    whole = resolve.decide(" ".join(norms), rows, recent) if norms else resolve.Decision()
    span = _scale_span(norms)
    if span and span[0] > 0 and _own_words(norms[span[0]:], whole.ticker, rows):
        span = None
    if span is None and len(norms) >= 2:
        heard_scale = scales.sounds_like(norms[-1])
        if heard_scale and not _own_words(norms[-1:], whole.ticker, rows):
            span = (len(norms) - 1, heard_scale)
    if span:
        scale = span[1]
        toks, norms = toks[:span[0]], norms[:span[0]]

    words = " ".join(norms)
    decision = resolve.decide(words, rows, recent) if words else resolve.Decision()
    company = None
    if decision.ticker:
        company = resolve.spoken_name(_name_of(decision.ticker, rows) or decision.ticker)
    elif any(n not in resolve.STOPWORDS for n in norms):
        company = " ".join(s for s, _ in toks)

    missing = []
    if not decision.ticker and not decision.options:
        missing.append("company")
    if scale is None:
        missing.append("scale")
    return Understanding(
        ticker=decision.ticker, company=company, scale=scale, where=where,
        ambiguous=[t for t, _ in decision.options], heard=heard, missing=missing)
