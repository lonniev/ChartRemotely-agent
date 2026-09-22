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
# The SEC asks for a contactable agent; anonymous requests get blocked.
USER_AGENT = "ChartRemotely agent (https://github.com/lonniev/ChartRemotely-agent)"


def _fresh() -> bool:
    return CACHE.exists() and time.time() - CACHE.stat().st_mtime < MAX_AGE


def refresh() -> list[dict]:
    request = urllib.request.Request(SEC_URL, headers={"User-Agent": USER_AGENT})
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
