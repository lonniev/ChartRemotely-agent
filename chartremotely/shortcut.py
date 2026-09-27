"""Make this Mac's own copies of the ChartRemotely Shortcuts.

Two, from two templates, each with placeholders where its address and token go:

* **ChartRemotely** (``shortcut-voice.plist``): records one sentence -
  "Palantir, half, on mac mini" - posts it to this Mac, which hears it with
  Whisper (:mod:`voice`), and speaks the reply. When the reply is a question
  (it ends "I'm listening.") it records again, at most three times.
* **ChartRemotely Ask** (``shortcut-ask.plist``): the three typed-or-dictated
  questions, Which company? What scale? Where? - the fallback, and the way to
  type a request.

Filling them in is string substitution and nothing more: rebuilding a
Shortcut's steps by hand has twice produced one that Siri runs differently
from the original.
"""

from __future__ import annotations

import plistlib
import subprocess
import tempfile
from importlib import resources
from pathlib import Path

URL_MARK = "__CHARTREMOTELY_URL__"
TOKEN_MARK = "__CHARTREMOTELY_TOKEN__"
NAME = "ChartRemotely"
ASK_NAME = "ChartRemotely Ask"
#: Library name -> template asset, the primary (voice) one first.
TEMPLATES = {NAME: "shortcut-voice.plist", ASK_NAME: "shortcut-ask.plist"}


def template(name: str = ASK_NAME) -> bytes:
    return resources.files("chartremotely").joinpath(f"assets/{TEMPLATES[name]}").read_bytes()


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


def build(url: str, token: str, out_dir: Path | None = None, name: str = NAME) -> Path:
    """Write, sign and return one of this Mac's Shortcuts. The file name is its library name."""
    folder = Path(out_dir or tempfile.mkdtemp(prefix="chartremotely-"))
    unsigned = folder / "unsigned.shortcut"
    signed = folder / f"{name}.shortcut"
    unsigned.write_bytes(plistlib.dumps(fill(template(name), url, token), fmt=plistlib.FMT_BINARY))
    try:
        subprocess.run(["shortcuts", "sign", "-m", "anyone", "-i", str(unsigned), "-o", str(signed)],
                       capture_output=True, check=True)
    finally:
        unsigned.unlink(missing_ok=True)
    return signed


def build_all(url: str, token: str, out_dir: Path | None = None) -> list[Path]:
    """Both Shortcuts, signed, the voice one first."""
    folder = Path(out_dir or tempfile.mkdtemp(prefix="chartremotely-"))
    return [build(url, token, folder, name) for name in TEMPLATES]
