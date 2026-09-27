"""One recorded sentence, from what was heard to what is said back.

Hearing and the operator are stand-ins: the sentence arrives as text, and
the priced call is recorded rather than made.
"""

import importlib
import sys
import threading
import types
import urllib.request

import pytest
from test_understand import DISPLAYS, ROWS

from chartremotely import hearing, recent, voice


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    voice._hold(None, 0.0)
    monkeypatch.setattr(voice.requestlog, "heard", lambda *a: None)
    monkeypatch.setattr(voice.requestlog, "request", lambda *a: None)


class Ear:
    """Says what a test scripted, one sentence per recording; records the prompt."""

    def __init__(self, *sentences):
        self.sentences = list(sentences)
        self.prompts = []
        self.sent = []
        self.clock = 1000.0

    def respond(self, audio=b"m4a", **kwargs):
        def transcribe(pcm, prompt):
            assert pcm == b"pcm"
            self.prompts.append(prompt)
            return self.sentences.pop(0)

        def send(command, where):
            self.sent.append((command, where))
            return f"sent {command} to {where or 'this Mac'}"

        return voice.respond(audio, "audio/m4a", decode=lambda a, t: b"pcm", transcribe=transcribe,
                             send=send, rows=ROWS, known=DISPLAYS, now=lambda: self.clock, **kwargs)


def test_a_whole_sentence_is_one_priced_call():
    ear = Ear("Palantir half on mac mini.")
    assert ear.respond() == "sent set PLTR | half to mac mini"
    assert ear.sent == [("set PLTR | half", "mac mini")]
    assert "Displays: Mac mini, Studio, Desk." in ear.prompts[0]


def test_as_is_sends_no_scale_and_no_where_means_this_mac():
    ear = Ear("apple as is")
    ear.respond()
    assert ear.sent == [("set AAPL | ", "")]


def test_a_missing_scale_is_asked_for_and_the_answer_completes_the_request():
    ear = Ear("Nvidia on the studio", "daily")
    first = ear.respond()
    assert first == f"I heard Nvidia but no scale. Say the scale, like half or daily. {voice.LISTENING}"
    assert ear.sent == []
    ear.clock += 10
    assert ear.respond() == "sent set NVDA | daily to studio"


def test_a_missing_company_is_asked_for_with_the_scale_kept():
    ear = Ear("four hours", "Shopify")
    assert ear.respond() == f"Which company at swing? {voice.LISTENING}"
    assert ear.respond() == "sent set SHOP | swing to this Mac"


def test_too_close_to_call_is_a_question_and_the_named_one_is_charted():
    ear = Ear("square daily on studio", "Pershing Square")
    ask = ear.respond()
    assert ask.startswith("Did you mean PS (Pershing Square) or MSGS (Madison Square Garden)?")
    assert ask.endswith(voice.LISTENING) and ear.sent == []
    assert ear.respond() == "sent set PS | daily to studio"


def test_a_follow_up_expires():
    ear = Ear("Nvidia", "daily")
    ear.respond()
    ear.clock += voice.FOLLOW_UP_SECONDS + 1
    assert ear.respond() == f"Which company at daily? {voice.LISTENING}"


def test_a_completed_request_is_not_carried_into_the_next():
    ear = Ear("Palantir half", "daily")
    ear.respond()
    assert ear.respond() == f"Which company at daily? {voice.LISTENING}"


def test_nothing_heard_is_asked_again():
    ear = Ear("")
    assert ear.respond() == f"I didn't hear anything. Say a company and a scale. {voice.LISTENING}"


def test_a_recording_that_cannot_be_heard_is_spoken_as_an_err_and_never_asks_again():
    def refuse(audio, content_type):
        raise hearing.HearingError("That was longer than 15 seconds. Say it shorter.")
    said = voice.respond(b"x", "audio/m4a", decode=refuse, rows=ROWS, known=DISPLAYS,
                         send=lambda c, w: pytest.fail("no call"))
    assert said == "ERR That was longer than 15 seconds. Say it shorter."
    assert voice.LISTENING not in said


def test_a_hearing_crash_is_never_a_stack_trace():
    def boom(pcm, prompt):
        raise RuntimeError("Metal device lost at 0xdeadbeef")
    said = voice.respond(b"x", None, decode=lambda a, t: b"pcm", transcribe=boom, rows=ROWS,
                         known=DISPLAYS, send=lambda c, w: pytest.fail("no call"))
    assert said == "ERR I couldn't hear that. Try again."


def test_recent_symbols_prime_the_model(tmp_path):
    recent.remember("SHOP")
    ear = Ear("Shopify daily")
    ear.respond()
    assert "Companies: Shopify." in ear.prompts[0]


# -- the listener ---------------------------------------------------------------------------

@pytest.fixture
def listener(monkeypatch):
    """The listener with stand-in vocab and voice. Returns (post, heard)."""
    heard = []
    fake_vocab = types.ModuleType("chartremotely.vocab")
    fake_vocab.answer = lambda cmd: pytest.fail("a recording is not a typed command")
    monkeypatch.setitem(sys.modules, "chartremotely.vocab", fake_vocab)
    monkeypatch.delitem(sys.modules, "chartremotely.server", raising=False)
    server = importlib.import_module("chartremotely.server")
    monkeypatch.setattr(voice, "respond", lambda audio, ctype: heard.append((audio, ctype)) or "Chart sent.")
    server.Handler.token = "T0KEN"
    from http.server import HTTPServer
    http = HTTPServer(("127.0.0.1", 0), server.Handler)
    threading.Thread(target=http.serve_forever, daemon=True).start()

    def post(body, query="?hear=1", ctype="audio/x-m4a", token="T0KEN"):
        request = urllib.request.Request(
            f"http://127.0.0.1:{http.server_address[1]}/chart{query}", data=body, method="POST",
            headers={"Content-Type": ctype, "X-Token": token})
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, response.read().decode().strip()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode().strip()

    yield post, heard
    http.shutdown()


def test_a_recording_on_the_chart_path_is_heard(listener):
    post, heard = listener
    assert post(b"m4a-bytes") == (200, "Chart sent.")
    assert heard == [(b"m4a-bytes", "audio/x-m4a")]


def test_an_audio_type_alone_marks_a_recording(listener):
    post, _ = listener
    assert post(b"m4a-bytes", query="") == (200, "Chart sent.")


def test_a_recording_needs_the_token(listener):
    post, heard = listener
    assert post(b"m4a-bytes", token="wrong")[0] == 403
    assert heard == []


def test_too_long_a_recording_is_refused_unread(listener):
    post, heard = listener
    code, said = post(b"x" * (hearing.MAX_BYTES + 1))
    assert (code, said) == (200, "ERR That was longer than 15 seconds. Say it shorter.")
    assert heard == []


def test_is_recording_tells_a_sentence_from_a_command(listener):
    server = importlib.import_module("chartremotely.server")
    assert server.is_recording("hear=1", "application/octet-stream")
    assert server.is_recording("", "audio/mp4")
    assert not server.is_recording("", "application/json")
