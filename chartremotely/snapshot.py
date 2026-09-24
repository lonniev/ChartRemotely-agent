"""Shrink a chart capture into something that can travel.

A window capture on a Retina display is a multi-megabyte PNG. It crosses the
relay as text inside a JSON reply and sits for a moment in the operator's
database, so it is re-encoded as a modest JPEG first: enough to read the
chart, small enough not to matter.

Pure on purpose. The capture itself needs the macOS drivers; turning bytes
into a reply does not, so this module stays importable - and testable -
where PyObjC is absent. ``sips`` is the system's own image tool, which keeps
the dependency list empty.
"""

from __future__ import annotations

import base64
import subprocess
import tempfile
from pathlib import Path

#: Longest side of the image sent back, in pixels.
MAX_SIDE = 1600
#: JPEG quality, 0-100.
QUALITY = 70
#: What every successful reply starts with. The operator checks for it.
PREFIX = "data:image/jpeg;base64,"


def sips_argv(src: Path, dst: Path, max_side: int = MAX_SIDE,
              quality: int = QUALITY) -> list[str]:
    """The ``sips`` command that resizes and re-encodes one capture."""
    return ["sips", "-Z", str(max_side),
            "-s", "format", "jpeg",
            "-s", "formatOptions", str(quality),
            str(src), "--out", str(dst)]


def as_reply(jpeg: bytes) -> str:
    """A JPEG, as the one-line text reply the relay carries."""
    return PREFIX + base64.b64encode(jpeg).decode("ascii")


def shrink(png: bytes) -> bytes:
    """Re-encode a PNG capture as a downscaled JPEG."""
    with tempfile.TemporaryDirectory() as tmp:
        src, dst = Path(tmp) / "chart.png", Path(tmp) / "chart.jpg"
        src.write_bytes(png)
        subprocess.run(sips_argv(src, dst), check=True, capture_output=True)
        return dst.read_bytes()
