"""One line to stderr per command handled, so a spoken ERR can be diagnosed.

launchd sends stderr to ``~/Library/Logs/chartremotely-<service>.log``. The
line carries only what is needed to tell requests apart: the time, the verb
(the command's first word), the "Where?" as dictated, and the reply when it
is an ERR. A command's arguments are never logged - except for the free
``resolve`` and ``scale`` lookups, whose argument is what Siri heard for a
company or a time frame (``heard=``, at most :data:`HEARD_MAX` characters):
not sensitive, and the only way to see why a word was not understood.
Never a token, a secret or a picture.

Stdlib only, like the relay, so it imports where the macOS drivers do not.
"""

from __future__ import annotations

import sys
import time

WHERE_MAX = 64
ERR_MAX = 200
HEARD_MAX = 60
#: A whole sentence heard by Whisper is longer than one lookup's argument.
SENTENCE_MAX = 120
#: The verbs whose argument is logged as ``heard=``; see the module doc.
HEARD_VERBS = frozenset({"resolve", "scale"})


def _clean(text: str, limit: int) -> str:
    """``text`` on one line, printable only, at most ``limit`` characters."""
    flat = "".join(c if c.isprintable() else " " for c in text)
    return flat[:limit]


def line(source: str, command: str, where: str, reply: str) -> str:
    """The log line for one request (see the module doc)."""
    first, _, rest = (command or "").strip().partition(" ")
    verb = _clean(first or "-", 32)
    parts = [time.strftime("%Y-%m-%dT%H:%M:%S%z"), source, f"verb={verb}",
             f"where={_clean(where or '', WHERE_MAX)!r}"]
    if first.lower() in HEARD_VERBS:
        parts.append(f"heard={_clean(rest.strip(), HEARD_MAX)!r}")
    if (reply or "").startswith("ERR"):
        parts.append(f"reply={_clean(reply, ERR_MAX)!r}")
    return " ".join(parts)


def request(source: str, command: str, where: str, reply: str) -> None:
    """Write :func:`line` to stderr. Never raises: logging must not cost a reply."""
    try:
        print(line(source, command, where, reply), file=sys.stderr, flush=True)
    except (OSError, ValueError):
        pass


def heard(source: str, text: str) -> None:
    """What Whisper heard for one recording (``heard=``, at most :data:`SENTENCE_MAX`
    characters). The text only - the audio is never logged. Never raises."""
    try:
        print(f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {source} heard={_clean(text or '', SENTENCE_MAX)!r}",
              file=sys.stderr, flush=True)
    except (OSError, ValueError):
        pass


def outcome(source: str, tool: str, where: str, error: str | None) -> None:
    """One line for how a background tool call ended: the tool, the "Where?",
    and the refusal when there was one. Never its arguments or the sign-in."""
    parts = [time.strftime("%Y-%m-%dT%H:%M:%S%z"), source, f"tool={_clean(tool or '-', 48)}",
             f"where={_clean(where or '', WHERE_MAX)!r}",
             f"error={_clean(error, ERR_MAX)!r}" if error else "ok"]
    try:
        print(" ".join(parts), file=sys.stderr, flush=True)
    except (OSError, ValueError):
        pass


def note(source: str, text: str) -> None:
    """One free-form line, e.g. what it took to bring the chart in front. Never raises."""
    try:
        print(f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {source} {_clean(text, ERR_MAX)}",
              file=sys.stderr, flush=True)
    except (OSError, ValueError):
        pass
