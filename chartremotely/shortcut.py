"""Make this Mac's own copy of the ChartRemotely voice Shortcut.

The template is the working Shortcut itself, exported with two placeholders
where its address and token were. Filling them in is string substitution
and nothing more: rebuilding a Shortcut's steps by hand has twice produced
one that Siri runs differently from the original.
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


def template() -> bytes:
    return resources.files("chartremotely").joinpath("assets/shortcut-template.plist").read_bytes()


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
