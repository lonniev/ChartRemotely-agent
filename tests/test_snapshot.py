"""The pure half of a snapshot: the resize command and the reply format."""

import base64
from pathlib import Path

from chartremotely import snapshot


def test_sips_resizes_and_reencodes_as_jpeg():
    argv = snapshot.sips_argv(Path("/t/a.png"), Path("/t/a.jpg"))
    assert argv[0] == "sips"
    assert argv[argv.index("-Z") + 1] == "1600"
    assert ["-s", "format", "jpeg"] == argv[3:6]
    assert ["-s", "formatOptions", "70"] == argv[6:9]
    assert argv[-3:] == ["/t/a.png", "--out", "/t/a.jpg"]


def test_sips_honours_a_custom_size_and_quality():
    argv = snapshot.sips_argv(Path("a"), Path("b"), max_side=800, quality=40)
    assert "800" in argv and "40" in argv


def test_the_reply_is_a_jpeg_data_url_that_round_trips():
    jpeg = b"\xff\xd8\xff\xe0fake"
    reply = snapshot.as_reply(jpeg)
    assert reply.startswith("data:image/jpeg;base64,")
    assert base64.b64decode(reply[len(snapshot.PREFIX):], validate=True) == jpeg
    assert "\n" not in reply


# Geometry measured on the owner's Mac mini, 2026-09-24: a 1920x1050 window,
# three containers reported, the symbol field at (386, 116).
WINDOW = (0, 30, 1920, 1050)
PANES = [(371, 59, 1546, 1018), (3, 59, 1914, 1018), (0, 30, 1920, 1050)]


def test_the_crop_is_the_smallest_pane_around_the_chart():
    # Everything left of x=371 (account info, watchlist, news) and the top bar
    # holding the account number stay on the machine.
    assert snapshot.chart_crop((386, 116), PANES, WINDOW, (1920, 1050)) == (371, 29, 1546, 1018)


def test_retina_pixels_scale_the_crop():
    assert snapshot.chart_crop((386, 116), PANES, WINDOW, (3840, 2100)) == (742, 58, 3092, 2036)


def test_the_whole_window_is_never_a_crop():
    # A layout that exposes no container but the window would send the
    # account panel along with the chart. No snapshot is the answer.
    import pytest
    with pytest.raises(snapshot.ChartNotIsolated):
        snapshot.chart_crop((386, 116), [WINDOW], WINDOW, (1920, 1050))


def test_a_point_outside_every_pane_is_refused():
    import pytest
    with pytest.raises(snapshot.ChartNotIsolated):
        snapshot.chart_crop((5000, 5000), PANES, WINDOW, (1920, 1050))


def test_the_crop_never_runs_past_the_image():
    x, y, w, h = snapshot.chart_crop((10, 10), [(-50, -50, 400, 400)], (0, 0, 1000, 1000), (1000, 1000))
    assert (x, y) == (0, 0) and w <= 1000 and h <= 1000
