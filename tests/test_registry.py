"""The registry merges SEC issuers with Nasdaq Trader's ETFs.

The ETF rows exist because "XBI swing scale" found nothing: the SEC file
lists a fund only when it files as its own company, and the sector ETFs
file as a series of a parent trust.
"""

import pytest

from chartremotely import registry
from chartremotely.resolve import TICKER, resolve
from chartremotely.understand import understand

# The real directory's header, rows as published, and its closing line.
DIRECTORY = """\
Nasdaq Traded|Symbol|Security Name|Listing Exchange|Market Category|ETF|Round Lot Size|Test Issue|Financial Status|CQS Symbol|NASDAQ Symbol|NextShares
Y|XBI|State Street SPDR S&P Biotech ETF|P| |Y|100|N||XBI|XBI|N
Y|XLE|State Street Energy Select Sector SPDR ETF|P| |Y|100|N||XLE|XLE|N
Y|QQQ|Invesco QQQ Trust, Series 1|Q|G|Y|40|N|N||QQQ|N
Y|SPY|SPDR S&P 500 ETF Trust|P| |Y|100|N||SPY|SPY|N
Y|STRC|Strategy Inc - Variable Rate Series A Perpetual Stretch Preferred Stock|Q|Q|N|100|N|N||STRC|N
Y|ZXZZT|NASDAQ TEST STOCK|Q|G|Y|100|Y|N||ZXZZT|N
N|GONE|Delisted Example ETF|P| |Y|100|N||GONE|GONE|N
File Creation Time: 1021202609:01|||||||||||
"""

SEC = [
    {"t": "NVDA", "n": "NVIDIA CORP", "r": 0},
    {"t": "PLTR", "n": "Palantir Technologies Inc.", "r": 1},
    {"t": "XOM", "n": "EXXON MOBIL CORP", "r": 2},
    {"t": "KRYS", "n": "Krystal Biotech, Inc.", "r": 3},
    {"t": "SPY", "n": "SPDR S&P 500 ETF TRUST", "r": 4},
]


def test_only_live_etfs_are_taken():
    assert registry.parse_etfs(DIRECTORY) == [
        ["XBI", "State Street SPDR S&P Biotech ETF"],
        ["XLE", "State Street Energy Select Sector SPDR ETF"],
        ["QQQ", "Invesco QQQ Trust, Series 1"],
        ["SPY", "SPDR S&P 500 ETF Trust"],
    ]


@pytest.mark.parametrize("text", ["", "not a directory\n", "Symbol|Name\nXBI|x\n"])
def test_an_unexpected_directory_yields_nothing(text):
    assert registry.parse_etfs(text) == []


def test_etfs_rank_after_every_sec_issuer_and_never_duplicate_one():
    rows = registry.merge(SEC, registry.parse_etfs(DIRECTORY))
    assert [r["t"] for r in rows] == ["NVDA", "PLTR", "XOM", "KRYS", "SPY", "XBI", "XLE", "QQQ"]
    assert [r["r"] for r in rows] == list(range(8))
    # The SEC's own SPY row wins over the directory's.
    assert next(r for r in rows if r["t"] == "SPY")["n"] == "SPDR S&P 500 ETF TRUST"


@pytest.fixture
def caches(tmp_path, monkeypatch):
    monkeypatch.setattr(registry, "DATA_DIR", tmp_path)
    monkeypatch.setattr(registry, "CACHE", tmp_path / "tickers.json")
    monkeypatch.setattr(registry, "ETF_CACHE", tmp_path / "etfs.json")
    monkeypatch.setattr(registry, "refresh", lambda: list(SEC))
    return tmp_path


def test_unreachable_directory_serves_the_last_copy(caches, monkeypatch):
    registry._store(registry.ETF_CACHE, [["XBI", "State Street SPDR S&P Biotech ETF"]])

    def down():
        raise OSError("nasdaqtrader.com unreachable")

    monkeypatch.setattr(registry, "refresh_etfs", down)
    rows = registry.load(force=True)
    assert [r["t"] for r in rows][-1] == "XBI"


def test_unreachable_directory_with_no_copy_still_loads_the_sec_file(caches, monkeypatch):
    def down():
        raise OSError("nasdaqtrader.com unreachable")

    monkeypatch.setattr(registry, "refresh_etfs", down)
    assert registry.load(force=True) == SEC


@pytest.mark.parametrize("shape", [
    "PLTR", "F", "BRK/B", "BTC/USD", "ETH/USD", "$SPX", ".SPX", "/ES", "/ESZ25:XCME", "XBI",
])
def test_ticker_shapes_thinkorswim_shows(shape):
    assert TICKER.match(shape)


@pytest.mark.parametrize("junk", ["", "palantir", "PLTR INC", "12AB", "BTC/USDTXX", "/"])
def test_not_ticker_shaped(junk):
    assert not TICKER.match(junk)


ROWS = registry.merge(SEC, registry.parse_etfs(DIRECTORY))


@pytest.mark.parametrize("said,expected", [
    ("XBI", "XBI"),
    ("x b i", "XBI"),
    ("ex bee eye", "XBI"),
    ("XLE", "XLE"),
    ("x l e", "XLE"),
    ("q q q", "QQQ"),
    ("energy select sector", "XLE"),
    # Companies still find themselves first.
    ("palantir", "PLTR"),
    ("exxon mobil", "XOM"),
])
def test_etfs_resolve_by_ticker_and_by_name(said, expected):
    assert resolve(said, ROWS) == expected


def test_an_etf_with_a_scale_and_a_display():
    u = understand("XBI swing scale on Mac mini", recent=[], displays=["Mac mini"], rows=ROWS)
    assert (u.ticker, u.scale, u.where) == ("XBI", "swing", "Mac mini")
