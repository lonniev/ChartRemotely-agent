"""What a spoken time frame names: exact phrases, bar sizes, and one careful
phonetic fallback. Two-sided, like the resolver's suite: what must match and
what must be refused."""

import itertools

import pytest

from chartremotely import scales
from chartremotely.scales import KEYS, mnemonic_for, sound_key, sounds_like, to_code


@pytest.mark.parametrize("said,word", [
    # a bar size for every preset, as digits and as words
    ("one minute", "minute"), ("1 minute", "minute"), ("a minute", "minute"),
    ("five minutes", "scalp"), ("5m", "scalp"),
    ("fifteen minutes", "quarter"), ("quarter hour", "quarter"),
    ("a quarter of an hour", "quarter"),
    ("thirty minutes", "half"), ("30 minutes", "half"), ("half an hour", "half"),
    ("half hour", "half"),
    ("an hour", "hourly"), ("one hour", "hourly"), ("sixty minutes", "hourly"),
    ("four hours", "swing"), ("4 hour", "swing"),
    ("a day", "daily"), ("one day", "daily"),
    ("a week", "weekly"), ("one week", "weekly"),
    ("ten ticks", "micro"), ("133 ticks", "ticks"),
    # filler around the phrase
    ("at half scale", "half"), ("the daily chart", "daily"),
    # full codes still work
    ("5d5m", "scalp"), ("10 D 30m", "half"), ("3yw", "weekly"),
])
def test_bar_sizes_and_phrases_name_a_preset(said, word):
    assert mnemonic_for(said) == word


def test_thirty_minutes_is_the_half_preset_for_the_chart_too():
    """timeframe.set_scale matches menu labels by to_code: it must get the preset."""
    assert to_code("thirty minutes") == "10d30m"
    assert to_code("four hours") == "180d4h"


@pytest.mark.parametrize("heard", ["have", "halve", "haff", "alf", "alpha", "calf"])
def test_half_as_siri_hears_it(heard):
    assert mnemonic_for(heard) == "half"


@pytest.mark.parametrize("heard", [
    "hal",            # one edit from half, hourly AND daily: no coin toss
    "what", "the", "hi", "five", "ten",
    "42 fortnights", "fifty two", "palantir",
    "5x5q",           # digits never reach the phonetic key
])
def test_what_names_no_scale_is_refused(heard):
    assert mnemonic_for(heard) is None


def test_no_two_mnemonics_share_a_key_or_sit_one_edit_apart():
    assert len(KEYS) == len(scales.MNEMONIC)
    for a, b in itertools.combinations(KEYS, 2):
        assert scales._distance(a, b) >= 2, (KEYS[a], KEYS[b])


def test_every_mnemonic_sounds_like_itself():
    for word in scales.MNEMONIC.values():
        assert sounds_like(word) == word


def test_the_key():
    assert sound_key("half") == sound_key("halve") == "hlf"
    assert sound_key("alpha") == "alf"
    assert sound_key("ticks") == "tks"
