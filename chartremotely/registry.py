"""The security registry: SEC issuers plus listed ETFs, cached locally.

The SEC file holds roughly 10,500 US issuers, ordered by prominence, which
makes the index a usable tie-breaker: NVDA, AAPL and GOOGL are the first
three entries. It lists a fund only when the fund files as its own company
(SPY, GLD), so the sector and thematic ETFs that file as a series of a
parent trust - XBI, XLE, QQQ, SMH - are absent from it.

Nasdaq Trader's symbol directory fills that gap: every US-listed security,
each flagged as an ETF or not, with its full name. Only its ETF rows are
taken, ranked after every SEC issuer, so a spoken company name still finds
the company before a fund that shares a word with it.
"""

from __future__ import annotations

import json
import time
import urllib.request

from .config import DATA_DIR

SEC_URL = "https://www.sec.gov/files/company_tickers.json"
NASDAQ_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqtraded.txt"
CACHE = DATA_DIR / "tickers.json"
ETF_CACHE = DATA_DIR / "etfs.json"
MAX_AGE = 7 * 24 * 3600
# The SEC requires a User-Agent carrying a contact address and answers 403
# without one. A repository URL alone is not enough.
DEFAULT_CONTACT = "chartremotely@example.com"


def _user_agent() -> str:
    from .config import load
    contact = load().get("contact") or DEFAULT_CONTACT
    # SEC's documented format is plain "Name email". Anything fancier is
    # rejected: a User-Agent carrying a URL answers 403, as does one with no
    # contact address at all.
    return f"ChartRemotely {contact}"


def _fresh(path=CACHE) -> bool:
    return path.exists() and time.time() - path.stat().st_mtime < MAX_AGE


def _store(path, rows: list) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(rows))
    tmp.replace(path)


def refresh() -> list[dict]:
    request = urllib.request.Request(SEC_URL, headers={"User-Agent": _user_agent()})
    with urllib.request.urlopen(request, timeout=20) as response:
        raw = json.load(response)
    rows = [{"t": v["ticker"], "n": v["title"], "r": rank}
            for rank, v in enumerate(raw.values())]
    _store(CACHE, rows)
    return rows


def parse_etfs(text: str) -> list[list[str]]:
    """``[symbol, name]`` for each live ETF in a Nasdaq Trader directory.

    Pipe-delimited with a header row and a closing "File Creation Time"
    line. Test issues and symbols no longer traded are dropped.
    """
    lines = text.splitlines()
    if not lines:
        return []
    head = lines[0].split("|")
    try:
        traded, sym, name, etf, test = (head.index(c) for c in (
            "Nasdaq Traded", "Symbol", "Security Name", "ETF", "Test Issue"))
    except ValueError:
        return []
    out = []
    for line in lines[1:]:
        f = line.split("|")
        if len(f) < len(head):
            continue
        if f[traded] == "Y" and f[etf] == "Y" and f[test] == "N" and f[sym]:
            out.append([f[sym].strip(), f[name].strip()])
    return out


def refresh_etfs() -> list[list[str]]:
    request = urllib.request.Request(NASDAQ_URL, headers={"User-Agent": _user_agent()})
    with urllib.request.urlopen(request, timeout=20) as response:
        etfs = parse_etfs(response.read().decode("utf-8", "replace"))
    if etfs:
        _store(ETF_CACHE, etfs)
    return etfs


def _etfs(force: bool) -> list[list[str]]:
    """The ETF rows, refreshed weekly. Never what breaks a lookup: when the
    directory cannot be fetched, the last copy serves, else no ETFs."""
    if force or not _fresh(ETF_CACHE):
        try:
            etfs = refresh_etfs()
            if etfs:
                return etfs
        except (OSError, ValueError):
            pass
    try:
        return json.loads(ETF_CACHE.read_text())
    except (OSError, ValueError):
        return []


def merge(sec: list[dict], etfs: list[list[str]]) -> list[dict]:
    """SEC rows first, then each ETF the SEC file lacks, ranked after them."""
    have = {r["t"] for r in sec}
    extra = [(t, n) for t, n in etfs if t not in have]
    return sec + [{"t": t, "n": n, "r": len(sec) + i} for i, (t, n) in enumerate(extra)]


def load(force: bool = False) -> list[dict]:
    sec = refresh() if force or not _fresh() else json.loads(CACHE.read_text())
    return merge(sec, _etfs(force))
