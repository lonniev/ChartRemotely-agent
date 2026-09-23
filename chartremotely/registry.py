"""The SEC company registry, cached locally.

Roughly 10,500 US issuers including ETFs. Ordered by prominence in the
source file, which makes the index a usable tie-breaker: NVDA, AAPL and
GOOGL are the first three entries.
"""

from __future__ import annotations

import json
import time
import urllib.request

from .config import DATA_DIR

SEC_URL = "https://www.sec.gov/files/company_tickers.json"
CACHE = DATA_DIR / "tickers.json"
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


def _fresh() -> bool:
    return CACHE.exists() and time.time() - CACHE.stat().st_mtime < MAX_AGE


def refresh() -> list[dict]:
    request = urllib.request.Request(SEC_URL, headers={"User-Agent": _user_agent()})
    with urllib.request.urlopen(request, timeout=20) as response:
        raw = json.load(response)
    rows = [{"t": v["ticker"], "n": v["title"], "r": rank}
            for rank, v in enumerate(raw.values())]
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CACHE.with_suffix(".tmp")
    tmp.write_text(json.dumps(rows))
    tmp.replace(CACHE)
    return rows


def load(force: bool = False) -> list[dict]:
    if force or not _fresh():
        return refresh()
    return json.loads(CACHE.read_text())
