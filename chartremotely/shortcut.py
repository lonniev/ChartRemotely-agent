"""Make this Mac's own copy of the ChartRemotely Shortcut.

One Shortcut, "ChartRemotely", from one template (``shortcut.plist``) with
placeholders where its address and token go. Talk, or type when it asks:

* It records one sentence - "Palantir, half, on mac mini" - posts it to this
  Mac, which hears it with Whisper (:mod:`voice`), and speaks the reply. When
  the reply is a question (it ends "I'm listening.") it records again; the
  third spoken miss asks its question in the text box instead.
* When nothing usable was recorded (no microphone, silence, noise) the reply
  is ``TYPE:`` and a prompt: the Shortcut shows that prompt in a one-line
  text box and posts the typed sentence instead. On a Mac it goes straight
  to the box - Record Audio waits forever on a Mac without a microphone.

Filling it in is string substitution and nothing more: rebuilding a
Shortcut's steps by hand has twice produced one that Siri runs differently
from the original.
"""

from __future__ import annotations

import plistlib
import subprocess
import tempfile
from collections.abc import Callable
from importlib import resources
from pathlib import Path

URL_MARK = "__CHARTREMOTELY_URL__"
TOKEN_MARK = "__CHARTREMOTELY_TOKEN__"
NAME = "ChartRemotely"
#: The Shortcut older setups made, removed from the library by setup. The
#: ``shortcuts`` command can list but not delete; "Shortcuts Events" can.
RETIRED = "ChartRemotely Ask"
#: Speak Text's rate (0 to 1; Siri's own is 0.5). Replies are short and
#: expected, so a person follows them brisker than Siri's default.
SPEAK_RATE = 0.6


def template() -> bytes:
    return resources.files("chartremotely").joinpath("assets/shortcut.plist").read_bytes()


def fill(raw: bytes, url: str, token: str) -> dict:
    """The template with its placeholders replaced, as a Shortcut workflow."""
    for value, mark in ((url, URL_MARK), (token, TOKEN_MARK)):
        if not value or mark in value:
            raise ValueError(f"no value for {mark}")
    workflow = plistlib.loads(raw)

    def walk(node):
        if isinstance(node, dict):
            return {k: walk(v) for k, v in node.items()}
        if isinstance(node, list):
            return [walk(v) for v in node]
        if isinstance(node, str):
            return node.replace(URL_MARK, url).replace(TOKEN_MARK, token)
        return node

    return walk(workflow)


def build(url: str, token: str, out_dir: Path | None = None) -> Path:
    """Write, sign and return this Mac's Shortcut. The file name is its library name."""
    folder = Path(out_dir or tempfile.mkdtemp(prefix="chartremotely-"))
    unsigned = folder / "unsigned.shortcut"
    signed = folder / f"{NAME}.shortcut"
    unsigned.write_bytes(plistlib.dumps(fill(template(), url, token), fmt=plistlib.FMT_BINARY))
    try:
        subprocess.run(["shortcuts", "sign", "-m", "anyone", "-i", str(unsigned), "-o", str(signed)],
                       capture_output=True, check=True)
    finally:
        unsigned.unlink(missing_ok=True)
    return signed


def retired(run: Callable[..., subprocess.CompletedProcess] = subprocess.run) -> list[str]:
    """The retired Shortcuts still in this Mac's library ("ChartRemotely Ask", "… Ask 2")."""
    try:
        listed = run(["shortcuts", "list"], capture_output=True, text=True, check=False, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return []
    names = [n.strip() for n in (getattr(listed, "stdout", "") or "").splitlines()]
    return [n for n in names if n == RETIRED or n.startswith(RETIRED + " ")]


def remove(name: str, run: Callable[..., subprocess.CompletedProcess] = subprocess.run) -> bool:
    """Delete one retired Shortcut from the library, by AppleScript. Returns whether it went."""
    if name != RETIRED and not name.startswith(RETIRED + " "):
        raise ValueError(f"{name!r} is not a retired ChartRemotely Shortcut")
    quoted = name.replace("\\", "\\\\").replace('"', '\\"')
    try:
        done = run(["osascript", "-e", f'tell application "Shortcuts Events" to delete shortcut "{quoted}"'],
                   capture_output=True, text=True, check=False, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return False
    return getattr(done, "returncode", 1) == 0


def remove_retired(run: Callable[..., subprocess.CompletedProcess] = subprocess.run) -> tuple[list[str], list[str]]:
    """Remove every retired Shortcut in the library. Returns (removed, left for the human)."""
    removed, left = [], []
    for name in retired(run):
        (removed if remove(name, run) else left).append(name)
    return removed, left
