"""What a command answers: the words for the caller, and what it put on the chart.

Stdlib only, so the relay and the push can carry it without importing the
macOS drivers.
"""

from __future__ import annotations

from typing import NamedTuple


class Answer(NamedTuple):
    """A command's reply, plus the symbol it put on the chart when it did.

    ``symbol`` is set only by a successful chart change that named one; the
    picture of that change is labelled with it, so a label never depends on
    how the reply happens to be worded.
    """

    reply: str
    symbol: str | None = None
