"""How ``chartremotely setup`` looks: a header, numbered steps, quiet detail.

Colour only on a terminal that wants it (not piped, no ``NO_COLOR``, not
``TERM=dumb``); everywhere else the same lines print plain, so tests read
exactly what a person reads.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable

INDENT = "    "


def wants_color(stream=sys.stdout) -> bool:
    return (hasattr(stream, "isatty") and stream.isatty()
            and not os.environ.get("NO_COLOR") and os.environ.get("TERM") != "dumb")


class Terminal:
    """Lines for a person: :meth:`step` headings, :meth:`ok` and :meth:`warn` marks,
    :meth:`say` detail and :meth:`ask` prompts, all indented under their step."""

    def __init__(self, write: Callable[[str], None] = print, read: Callable[[str], str] = input,
                 color: bool = False):
        self.write, self.read, self.color = write, read, color

    def _paint(self, code: str, text: str) -> str:
        return f"\033[{code}m{text}\033[0m" if self.color else text

    def bold(self, text: str) -> str:
        return self._paint("1", text)

    def dim(self, text: str) -> str:
        return self._paint("2", text)

    def title(self, name: str, summary: str) -> None:
        self.write("")
        self.write(self.bold(name))
        self.write(self.dim(summary))

    def facts(self, rows: list[tuple[str, str]]) -> None:
        """Label/value rows, labels aligned."""
        width = max(len(label) for label, _ in rows)
        self.write("")
        for label, value in rows:
            self.write(f"  {self.dim(label.ljust(width))}  {value}")

    def plan(self, heading: str, steps: list[tuple[str, str]]) -> None:
        width = max(len(name) for name, _ in steps)
        self.write("")
        self.write(heading)
        for i, (name, what) in enumerate(steps, 1):
            self.write(f"  {self._paint('36', str(i))}  {self.bold(name.ljust(width))}  {what}")

    def step(self, number: int, total: int, name: str) -> None:
        self.write("")
        self.write(f"{self._paint('36', f'[{number}/{total}]')} {self.bold(name)}")

    def say(self, text: str) -> None:
        self.write(f"{INDENT}{text}" if text else "")

    def ok(self, text: str) -> None:
        self.write(f"  {self._paint('32', '✓')} {text}")

    def warn(self, text: str) -> None:
        self.write(f"  {self._paint('33', '!')} {text}")

    def ask(self, prompt: str) -> str:
        return self.read(f"  {self._paint('36', '›')} {prompt}")

    def confirm(self, prompt: str) -> bool:
        return not self.ask(f"{prompt} [Y/n] ").strip().lower().startswith("n")
