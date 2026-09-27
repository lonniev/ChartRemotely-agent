"""One utterance -> company, scale, where. Each row is a transcription as
Siri or Whisper produced it (mis-hearings included), and what it must mean.
"""

import pytest
from test_resolve import AMBIGUOUS

from chartremotely.understand import understand

ROWS = AMBIGUOUS + [
    {"t": "SMCI", "n": "Super Micro Computer, Inc.", "r": 110},
    {"t": "TTD", "n": "Trade Desk, Inc.", "r": 180},
    {"t": "AMZN", "n": "AMAZON COM INC", "r": 3},
]
DISPLAYS = ["Mac mini", "Studio", "Desk"]


@pytest.mark.parametrize("heard,ticker,scale,where", [
    ("Palantir half on mac mini", "PLTR", "half", "mac mini"),
    ("shop thirty minutes", "SHOP", "half", None),
    ("GE daily on the studio", "GE", "daily", "studio"),
    ("Nvidia", "NVDA", None, None),
    ("apple as is on desk", "AAPL", "as is", "desk"),
    # mis-hearings
    ("pal and tear half on the mini", "PLTR", "half", "mini"),
    ("shop if y daily", "SHOP", "daily", None),
    ("Palantir have", "PLTR", "half", None),
    ("Palantir alf on studio", "PLTR", "half", "studio"),
    ("volunteer halve", "PLTR", "half", None),
    ("in video quarter", "NVDA", "quarter", None),
    ("net flicks four hours", "NFLX", "swing", None),
    ("amazon the mini", "AMZN", None, "mini"),
    ("Palantir on mack meeny", "PLTR", None, "mack meeny"),
    # phrasing
    ("Show me Palantir at half scale on the Mac mini.", "PLTR", "half", "Mac mini"),
    ("coinbase half an hour on the mini", "COIN", "half", "mini"),
    ("Palantir on mac mini half", "PLTR", "half", "mac mini"),
    ("apple daily studio", "AAPL", "daily", "studio"),
    ("walmart an hour", "WMT", "hourly", None),
    ("ford 5 minutes", "F", "scalp", None),
    ("apple same", "AAPL", "as is", None),
    ("Nvidia to the studio", "NVDA", None, "studio"),
    ("Palantir half on the kitchen", "PLTR", "half", "kitchen"),  # the operator judges names
    # a company's own words are never taken as a scale or a display
    ("super micro", "SMCI", None, None),
    ("super micro daily", "SMCI", "daily", None),
    ("john deere", "DE", None, None),
    ("the trade desk daily on studio", "TTD", "daily", "studio"),
    ("at and t daily", "T", "daily", None),
])
def test_utterances(heard, ticker, scale, where):
    u = understand(heard, recent=[], displays=DISPLAYS, rows=ROWS)
    assert (u.ticker, u.scale, u.where) == (ticker, scale, where)
    assert u.heard == heard
    assert u.ambiguous == []


def test_what_is_missing_is_named():
    u = understand("four hours", recent=[], displays=DISPLAYS, rows=ROWS)
    assert (u.ticker, u.company, u.scale, u.missing) == (None, None, "swing", ["company"])
    u = understand("Nvidia", recent=[], displays=DISPLAYS, rows=ROWS)
    assert u.missing == ["scale"] and u.company == "Nvidia"
    u = understand("", recent=[], displays=DISPLAYS, rows=ROWS)
    assert u.missing == ["company", "scale"] and u.where is None


def test_too_close_to_call_comes_back_as_options():
    u = understand("square daily on studio", recent=[], displays=DISPLAYS, rows=ROWS)
    assert u.ticker is None and u.ambiguous == ["PS", "MSGS"]
    assert (u.scale, u.where, u.company, u.missing) == ("daily", "studio", "square", [])


def test_the_prior_settles_it():
    u = understand("square daily", recent=["MSGS"], displays=DISPLAYS, rows=ROWS)
    assert u.ticker == "MSGS" and u.ambiguous == []


def test_noise_is_not_a_company():
    u = understand("um what half", recent=[], displays=DISPLAYS, rows=ROWS)
    assert (u.ticker, u.company, u.scale) == (None, None, "half")


def test_at_needs_a_known_display_but_on_does_not():
    u = understand("show at and t weekly", recent=[], displays=DISPLAYS, rows=ROWS)
    assert (u.ticker, u.where) == ("T", None)
    u = understand("apple on somewhere new", recent=[], displays=DISPLAYS, rows=ROWS)
    assert (u.ticker, u.where) == ("AAPL", "somewhere new")
