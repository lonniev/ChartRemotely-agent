#!/usr/bin/env python3
"""Move shipped CHANGELOG lines out of ``## [Unreleased]`` into dated release sections.

An automatic release publishes from main without committing to it, so its lines stay
under ``[Unreleased]``. This puts them where they belong, afterwards, from main's
CHANGELOG and the ``vX.Y.Z`` tags:

  * every tag newer than the newest ``## [x.y.z]`` section is a release still to stamp;
  * a release's lines are the ``[Unreleased]`` entries at its tag that were not already
    there at the tag before it - the same rule the release notes use, so a line is
    announced and filed exactly once;
  * only entries still under ``[Unreleased]`` on main move (a line reworded since stays
    put), keeping their ``###`` subsection, and ``## [Unreleased]`` is left empty above
    the new sections.

It is idempotent: with nothing left to stamp the file is untouched.

    stamp_changelog.py                     stamp CHANGELOG.md in place
    stamp_changelog.py --notes VERSION     print the section VERSION would get if it were
                                           released from HEAD now (for the release notes)
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

UNRELEASED = "Unreleased"
REPO_PATH = "CHANGELOG.md"  # where history lives; --changelog may name a copy
_SECTION = re.compile(r"^## \[?([^\]\s]+)\]?")
_VERSION = re.compile(r"^\d+\.\d+\.\d+$")

# An entry is one bullet with its continuation lines; its subsection is the ### above it.
Entry = tuple[str, str]  # (subsection heading, full entry text)


def _key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def split_sections(text: str) -> tuple[list[str], list[tuple[str, list[str]]]]:
    """The lines before the first ``## `` heading, then each ``## `` section's name and lines."""
    preamble: list[str] = []
    sections: list[tuple[str, list[str]]] = []
    for line in text.splitlines():
        match = _SECTION.match(line)
        if match:
            sections.append((match.group(1), [line]))
        elif sections:
            sections[-1][1].append(line)
        else:
            preamble.append(line)
    return preamble, sections


def entries(body: list[str]) -> list[Entry]:
    """The bullets of a section body (heading line excluded), each under its ``###``."""
    found: list[Entry] = []
    heading = ""
    current: list[str] = []

    def flush() -> None:
        if current:
            found.append((heading, "\n".join(current).rstrip()))
            current.clear()

    for line in body:
        if line.startswith("### "):
            flush()
            heading = line
        elif line.startswith("- "):
            flush()
            current.append(line)
        elif current and line.strip():
            current.append(line)
        else:
            flush()
    flush()
    return found


def unreleased_entries(text: str) -> list[Entry]:
    _, sections = split_sections(text)
    for name, lines in sections:
        if name == UNRELEASED:
            return entries(lines[1:])
    return []


def render(items: list[Entry]) -> list[str]:
    """Entries grouped under their subsections, in first-seen order; repeats merged."""
    order: list[str] = []
    grouped: dict[str, list[str]] = {}
    for heading, text in items:
        if heading not in grouped:
            order.append(heading)
            grouped[heading] = []
        grouped[heading].append(text)
    out: list[str] = []
    for heading in order:
        if heading:
            out += ["", heading]
        elif out:
            out.append("")
        out += grouped[heading]
    return out


def added(at_release: list[Entry], at_previous: list[Entry]) -> list[Entry]:
    before = {text for _, text in at_previous}
    return [item for item in at_release if item[1] not in before]


def stamp(text: str, releases: list[tuple[str, str, list[Entry]]]) -> str:
    """Stamp ``releases`` (oldest first: version, date, entries it added) into ``text``.

    Versions that already have a section, and entries no longer under [Unreleased],
    are skipped. Returns ``text`` unchanged when nothing moves.
    """
    preamble, sections = split_sections(text)
    names = [name for name, _ in sections]
    if UNRELEASED not in names:
        return text
    remaining = entries(sections[names.index(UNRELEASED)][1][1:])

    new_sections: list[list[str]] = []
    for version, date, items in releases:
        if version in names:
            continue
        texts = {t for _, t in items}
        moving = [item for item in remaining if item[1] in texts]
        if not moving:
            continue
        remaining = [item for item in remaining if item[1] not in texts]
        new_sections.insert(0, [f"## [{version}] - {date}", *render(moving), ""])
    if not new_sections:
        return text

    unreleased = [f"## [{UNRELEASED}]", *render(remaining), ""]
    out = list(preamble)
    for name, lines in sections:
        if name == UNRELEASED:
            out += unreleased
            for block in new_sections:
                out += block
        else:
            out += lines
    return "\n".join(out).rstrip("\n") + "\n"


# --- git glue -------------------------------------------------------------------------


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout


def _changelog_at(ref: str) -> str:
    try:
        return _git("show", f"{ref}:{REPO_PATH}")
    except subprocess.CalledProcessError:
        return ""


def _tags() -> list[str]:
    versions = [t[1:] for t in _git("tag", "-l", "v*").split() if _VERSION.match(t[1:])]
    return sorted(versions, key=_key)


def _previous(version: str, tags: list[str]) -> str | None:
    older = [t for t in tags if _key(t) < _key(version)]
    return older[-1] if older else None


def _added_at(ref: str, version: str, tags: list[str]) -> list[Entry]:
    prev = _previous(version, tags)
    before = unreleased_entries(_changelog_at(f"v{prev}")) if prev else []
    return added(unreleased_entries(_changelog_at(ref)), before)


def pending_releases(text: str) -> list[tuple[str, str, list[Entry]]]:
    stamped = [n for n, _ in split_sections(text)[1] if _VERSION.match(n)]
    newest = max(stamped, key=_key) if stamped else "0.0.0"
    tags = _tags()
    return [
        (v, _git("log", "-1", "--format=%cs", f"v{v}").strip(), _added_at(f"v{v}", v, tags))
        for v in tags
        if _key(v) > _key(newest)
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.add_argument("--changelog", default="CHANGELOG.md")
    parser.add_argument("--notes", metavar="VERSION")
    args = parser.parse_args()

    if args.notes:
        items = _added_at("HEAD", args.notes, _tags())
        print("\n".join(render(items)).strip("\n"))
        return 0

    path = Path(args.changelog)
    text = path.read_text()
    stamped = stamp(text, pending_releases(text))
    if stamped != text:
        path.write_text(stamped)
        print(f"stamped {path}")
    else:
        print(f"{path}: nothing to stamp")
    return 0


if __name__ == "__main__":
    sys.exit(main())
