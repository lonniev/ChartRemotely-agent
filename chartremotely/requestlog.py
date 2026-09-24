"""One line to stderr per command handled, so a spoken ERR can be diagnosed.

launchd sends stderr to ``~/Library/Logs/chartremotely-<service>.log``. The
line carries only what is needed to tell requests apart: the time, the verb
(the command's first word, never its arguments), the "Where?" as dictated,
and the reply when it is an ERR. Never a token, a secret or a picture.

Stdlib only, like the relay, so it imports where the macOS drivers do not.
"""

from __future__ import annotations

import sys
import time

WHERE_MAX = 64
ERR_MAX = 200


def _clean(text: str, limit: int) -> str:
    """``text`` on one line, printable only, at most ``limit`` characters."""
    flat = "".join(c if c.isprintable() else " " for c in text)
    return flat[:limit]


def line(source: str, command: str, where: str, reply: str) -> str:
    """The log line for one request (see the module doc)."""
    verb = _clean((command or "").split(maxsplit=1)[0] if (command or "").strip() else "-", 32)
    parts = [time.strftime("%Y-%m-%dT%H:%M:%S%z"), source, f"verb={verb}",
             f"where={_clean(where or '', WHERE_MAX)!r}"]
    if (reply or "").startswith("ERR"):
        parts.append(f"reply={_clean(reply, ERR_MAX)!r}")
    return " ".join(parts)


def request(source: str, command: str, where: str, reply: str) -> None:
    """Write :func:`line` to stderr. Never raises: logging must not cost a reply."""
    try:
        print(line(source, command, where, reply), file=sys.stderr, flush=True)
    except (OSError, ValueError):
        pass
