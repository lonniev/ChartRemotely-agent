"""Every case here is a transcript or failure observed against live dictation.

The suite is deliberately two-sided: it asserts what must resolve AND what
must be refused. Loosening a threshold to fix a miss tends to break the
refusals, which is exactly the regression worth catching.
"""

import pytest

from chartremotely.resolve import phonetic, resolve, spelled

# A slice of the SEC registry, ranked as the real file is (lower = more
# prominent). Includes the specific collisions that caused wrong answers.
ROWS = [
    {"t": "NVDA", "n": "NVIDIA CORP", "r": 0},
    {"t": "AAPL", "n": "Apple Inc.", "r": 1},
    {"t": "PLTR", "n": "Palantir Technologies Inc.", "r": 10},
    {"t": "TSM", "n": "TAIWAN SEMICONDUCTOR MANUFACTURING CO LTD", "r": 20},
    {"t": "COIN", "n": "Coinbase Global, Inc.", "r": 329},
    {"t": "QCOM", "n": "QUALCOMM INC/DE", "r": 40},
    {"t": "WMT", "n": "Walmart Inc.", "r": 15},
    {"t": "DE", "n": "DEERE & CO", "r": 60},
    {"t": "KMI", "n": "KINDER MORGAN, INC.", "r": 120},
    {"t": "T", "n": "AT&T INC.", "r": 30},
    {"t": "GE", "n": "GENERAL ELECTRIC CO", "r": 35},
    {"t": "HWM", "n": "Howmet Aerospace Inc.", "r": 300},
    {"t": "NIHK", "n": "Video River Networks, Inc.", "r": 9000},
    {"t": "NFLX", "n": "NETFLIX INC", "r": 25},
    {"t": "AVGO", "n": "Broadcom Inc.", "r": 12},
    {"t": "MCHP", "n": "MICROCHIP TECHNOLOGY INC", "r": 200},
    {"t": "DOV", "n": "DOVER Corp", "r": 400},
    {"t": "HOOD", "n": "Robinhood Markets, Inc.", "r": 150},
]


@pytest.mark.parametrize("said,expected", [
    ("palantir", "PLTR"),
    ("nvidia", "NVDA"),
    ("walmart", "WMT"),
    ("coinbase", "COIN"),
    ("taiwan semiconductor", "TSM"),
    ("at and t", "T"),
    ("general electric", "GE"),
])
def test_names_resolve(said, expected):
    assert resolve(said, ROWS) == expected


@pytest.mark.parametrize("heard,expected", [
    ("volunteer", "PLTR"),      # shares Palantir's skeleton exactly
    ("volunteered", "PLTR"),    # inflected; needs de-inflection
    ("volunteers", "PLTR"),
    ("in video", "NVDA"),       # must beat Video River Networks
    ("net flicks", "NFLX"),
    ("broad com", "AVGO"),
    ("micro chip", "MCHP"),
    ("co in base", "COIN"),     # "co" is a corporate suffix; must survive
    ("callalon", "QCOM"),       # alias: skeleton is lost
    ("kuehn", "COIN"),          # alias
    ("john deere", "DE"),       # colloquial name; DEERE & CO has no "john"
])
def test_mishearings_resolve(heard, expected):
    assert resolve(heard, ROWS) == expected


@pytest.mark.parametrize("noise", [
    "what", "the", "okay", "hey siri", "show me", "whatever", "something",
    "nothing", "i don't know", "um er ah", "gibberish blah",
])
def test_noise_is_refused(noise):
    assert resolve(noise, ROWS) is None


@pytest.mark.parametrize("said,expected", [
    ("p l t r", "PLTR"),
    ("P-L-T-R", "PLTR"),
    ("pee ell tee are", "PLTR"),
    ("cue see oh em", "QCOM"),
    ("h o o d", "HOOD"),
])
def test_spelled_tickers(said, expected):
    assert resolve(said, ROWS) == expected


def test_spelling_does_not_hijack_names():
    assert spelled("palantir") is None
    assert resolve("palantir", ROWS) == "PLTR"


def test_the_two_collisions_that_caused_wrong_answers():
    # "john deere" and "kinder" code identically, which is how a Deere
    # query once returned Kinder Morgan.
    assert phonetic("john deere") == phonetic("kinder")
    assert resolve("john deere", ROWS) == "DE"
    # A single shared word must not win: "aerospace" is half of Howmet.
    assert resolve("ge aerospace", ROWS) == "GE"
