"""The symbols this Mac charted lately: a personal prior for what was said.

When a spoken name lands between two companies, the one you chart is the one
you meant (see :func:`resolve.decide`). The list is kept most recent first,
at most :data:`KEEP` long, in ``~/.config/chartremotely/recent.json``, and is
written only when a chart change succeeded. It holds ticker symbols and
nothing else - never a token, a name as said or a secret.

Stdlib only; every function swallows its own errors, because a lost prior
must never cost a reply.
"""

from __future__ import annotations

import json
import re

from .config import CONFIG_DIR

PATH = CONFIG_DIR / "recent.json"
KEEP = 50
_TICKER = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")


def load(path=None) -> list[str]:
    """The remembered symbols, most recent first; [] when there are none."""
    try:
        data = json.loads((path or PATH).read_text())
    except (OSError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    return [t for t in data if isinstance(t, str) and _TICKER.match(t)][:KEEP]


def remember(ticker: str, path=None) -> None:
    """Put a symbol that was just charted at the front. Ignores anything not
    shaped like a ticker, so a company name as said is never written."""
    ticker = (ticker or "").strip().upper()
    if not _TICKER.match(ticker):
        return
    path = path or PATH
    kept = [ticker] + [t for t in load(path) if t != ticker]
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(kept[:KEEP]))
        tmp.replace(path)
    except OSError:
        pass
