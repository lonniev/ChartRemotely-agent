"""The personal prior: tickers only, most recent first, bounded, never fatal."""

from chartremotely import recent


def test_most_recent_first_without_repeats():
    for t in ("PLTR", "NVDA", "PLTR"):
        recent.remember(t)
    assert recent.load() == ["PLTR", "NVDA"]


def test_only_ticker_shaped_values_are_written():
    recent.remember("palantir technologies")
    recent.remember("")
    recent.remember("brk-b")
    assert recent.load() == ["BRK-B"]


def test_bounded():
    for i in range(recent.KEEP + 10):
        recent.remember(f"T{i}")
    kept = recent.load()
    assert len(kept) == recent.KEEP and kept[0] == f"T{recent.KEEP + 9}"


def test_a_damaged_file_is_an_empty_prior():
    recent.PATH.write_text("{not json")
    assert recent.load() == []
    recent.remember("AAPL")
    assert recent.load() == ["AAPL"]
