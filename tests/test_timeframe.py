"""Timeframe phrase parsing. Pure logic - no GUI, so CI can run it."""

import pytest

from chartremotely.timeframe import canon, mnemonic_for, to_code


@pytest.mark.parametrize("said,code", [
    ("5 D : 5m", "5d5m"),
    ("5d 5m", "5d5m"),
    ("five day five minute", "5d5m"),
    ("1d/1m", "1d1m"),
    ("20 day 1 hour", "20d1h"),
])
def test_numeric_phrases(said, code):
    assert canon(said) == code


@pytest.mark.parametrize("word,code", [
    ("minute", "1d1m"), ("scalp", "5d5m"), ("quarter", "5d15m"),
    ("half", "10d30m"), ("hourly", "20d1h"), ("swing", "180d4h"),
    ("daily", "1y1d"), ("weekly", "3yw"), ("ticks", "1d133t"),
    ("micro", "1d10t"),
])
def test_mnemonics(word, code):
    assert to_code(word) == code
    assert mnemonic_for(word) == word


def test_mnemonics_are_phonetically_distinct():
    """No two spoken words may share a consonant skeleton - that is the
    whole reason the vocabulary avoids digits."""
    from chartremotely.resolve import phonetic
    words = ["minute", "scalp", "quarter", "half", "hourly",
             "swing", "daily", "weekly", "ticks", "micro"]
    skeletons = [phonetic(w) for w in words]
    assert len(set(skeletons)) == len(words)


def test_unparseable_yields_empty_code():
    """Callers must treat "" as a refusal: every string ends with "", so a
    loose endswith match would otherwise select an arbitrary preset."""
    assert to_code("42 fortnights") == ""
    assert mnemonic_for("42 fortnights") is None
