"""Crop a capture to the chart, and shrink it into something that can travel.

Only the chart's own pane leaves the machine. A thinkorswim window also shows
the account number, net liquidation value, buying power and cash, and a
snapshot is a picture sent to wherever the patron is — so the crop is the
point, not a nicety. When the chart's pane cannot be told apart from the whole
window, there is no snapshot: failing closed is the only safe answer.

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

Rect = tuple[int, int, int, int]


class ChartNotIsolated(LookupError):
    """The chart's own pane could not be told apart from the whole window."""


def chart_crop(hit: tuple[int, int], panes: list[Rect], window: Rect,
               image: tuple[int, int]) -> Rect:
    """The chart's pane, in the capture's own pixels.

    ``hit`` is a point inside the chart (its symbol field), ``panes`` the
    containers the accessibility tree reports and ``window`` the window, all
    in screen points. ``image`` is the capture's size in pixels, which differs
    from the window's size in points on a Retina display.

    The chart's pane is the smallest container around the symbol field. The
    window itself never counts: sending it would send the account panel.
    """
    wx, wy, ww, wh = window
    hx, hy = hit
    inside = [r for r in panes
              if r[0] <= hx < r[0] + r[2] and r[1] <= hy < r[1] + r[3]
              and r[2] * r[3] < ww * wh]
    if not inside:
        raise ChartNotIsolated("could not tell the chart apart from the rest of the window")
    x, y, w, h = min(inside, key=lambda r: r[2] * r[3])
    sx, sy = image[0] / ww, image[1] / wh
    left, top = max(0, round((x - wx) * sx)), max(0, round((y - wy) * sy))
    right = min(image[0], round((x - wx + w) * sx))
    bottom = min(image[1], round((y - wy + h) * sy))
    return left, top, right - left, bottom - top


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
