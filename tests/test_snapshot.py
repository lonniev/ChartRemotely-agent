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
