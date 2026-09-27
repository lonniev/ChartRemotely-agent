"""Hearing a recorded sentence: decoding, priming, size caps, the display list.

afconvert, Whisper and the operator are stand-ins, so this runs on Linux
with neither MLX nor numpy installed.
"""

import json
import plistlib
import subprocess
import wave
from pathlib import Path

import pytest
from test_understand import ROWS

from chartremotely import displays, hearing, keystore, shortcut


def _wav(path: Path, frames: int, rate: int = hearing.RATE, channels: int = 1) -> None:
    with wave.open(str(path), "wb") as out:
        out.setnchannels(channels)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(b"\x01\x00" * frames * channels)


class FakeAfconvert:
    """Writes a WAV where afconvert would, and remembers what it was asked."""

    def __init__(self, frames=hearing.RATE, fail=False, channels=1):
        self.frames, self.fail, self.channels = frames, fail, channels
        self.args, self.folder = None, None

    def __call__(self, args, **kwargs):
        self.args = args
        source, target = Path(args[-2]), Path(args[-1])
        self.folder = source.parent
        assert source.read_bytes() == b"m4a-bytes", "the recording is handed over as sent"
        if not self.fail:
            _wav(target, self.frames, channels=self.channels)
        return subprocess.CompletedProcess(args, 1 if self.fail else 0)


# -- decoding ------------------------------------------------------------------------

def test_decode_asks_afconvert_for_16k_mono_pcm_and_leaves_nothing_behind():
    run = FakeAfconvert()
    pcm = hearing.decode(b"m4a-bytes", "audio/x-m4a", run=run)
    assert run.args[:7] == [hearing.AFCONVERT, "-f", "WAVE", "-d", "LEI16@16000", "-c", "1"]
    assert run.args[-2].endswith(".m4a")
    assert len(pcm) == hearing.RATE * 2
    assert not run.folder.exists(), "the recording must not outlive the reply"


def test_the_recording_type_picks_what_afconvert_reads():
    assert hearing.suffix_for("audio/wav") == ".wav"
    assert hearing.suffix_for("audio/x-caf; codecs=aac") == ".caf"
    assert hearing.suffix_for(None) == ".m4a"
    assert hearing.suffix_for("application/octet-stream") == ".m4a"


@pytest.mark.parametrize("audio,run,said", [
    (b"", FakeAfconvert(), "didn't hear anything"),
    (b"x" * (hearing.MAX_BYTES + 1), FakeAfconvert(), "longer than 15 seconds"),
    (b"m4a-bytes", FakeAfconvert(fail=True), "couldn't read"),
    (b"m4a-bytes", FakeAfconvert(frames=int(hearing.RATE * 16)), "longer than 15 seconds"),
    (b"m4a-bytes", FakeAfconvert(channels=2), "not in a shape"),
])
def test_a_recording_that_cannot_be_heard_says_why(audio, run, said):
    with pytest.raises(hearing.HearingError, match=said):
        hearing.decode(audio, "audio/m4a", run=run)


def test_samples_are_float32_between_minus_one_and_one():
    np = pytest.importorskip("numpy")
    got = hearing.samples(b"\x00\x80\xff\x7f\x00\x00")
    assert got.dtype == np.float32
    assert got.tolist() == [-1.0, pytest.approx(32767 / 32768), 0.0]


def test_transcription_without_mlx_is_a_sentence_not_a_crash(monkeypatch):
    def missing(audio, prompt):
        raise ImportError("mlx_whisper")
    monkeypatch.setattr(hearing, "samples", lambda pcm: pcm)
    monkeypatch.setattr(hearing, "_transcribe", missing)
    with pytest.raises(hearing.HearingError, match="cannot hear yet"):
        hearing.transcribe(b"\x00\x00")


def test_warming_never_raises_where_whisper_cannot_run(monkeypatch):
    monkeypatch.setattr(hearing, "available", lambda: False)
    assert hearing.warm() is False


# -- priming ----------------------------------------------------------------------------

def test_the_prompt_names_the_scales_the_displays_and_recent_companies():
    text = hearing.prompt(["PLTR", "SHOP"], ROWS, ["Mac mini", "Studio"])
    assert text.startswith("Palantir Technologies half on Mac mini.")
    for word in ("minute", "scalp", "quarter", "half", "hourly", "swing", "daily", "weekly",
                 "ticks", "micro", "thirty minutes", "as is"):
        assert word in text
    assert "Displays: Mac mini, Studio." in text
    assert "Companies: Palantir Technologies, Shopify." in text


def test_the_prompt_is_capped_and_scales_are_never_crowded_out():
    rows = [{"t": f"T{i}", "n": f"Company Number {i} Holdings", "r": i} for i in range(300)]
    text = hearing.prompt([r["t"] for r in rows], rows, ["Desk"])
    assert len(text) <= hearing.PROMPT_CHARS
    assert "weekly" in text and "Displays: Desk." in text
    assert text.endswith("."), "companies are dropped whole, never cut mid-name"


def test_a_prompt_with_nothing_known_still_primes_the_grammar():
    text = hearing.prompt([], ROWS, [])
    assert text.startswith("Palantir half on mac mini.") and "Companies" not in text


# -- the display list ------------------------------------------------------------------------

STATUS = {"displays": [{"label": "Studio", "agent_id": "b2", "connected": True},
                       {"label": "Mac mini", "agent_id": "a1", "connected": True},
                       {"label": "Studio", "agent_id": "c3", "connected": False}]}


def test_display_labels_put_this_mac_first_and_name_each_once():
    assert displays.labels_from(STATUS, "a1") == ["Mac mini", "Studio"]
    assert displays.labels_from({"error": "nope"}, "a1") == []


def test_the_list_is_fetched_as_the_owner_and_cached_without_a_token(monkeypatch, tmp_path):
    calls = []

    class Client:
        def __init__(self, base, timeout):
            self.base = base

        def call(self, tool, args):
            calls.append((self.base, tool, dict(args)))
            return STATUS

    monkeypatch.setattr(keystore, "load_token", lambda npub: "seven-amber-door")
    cfg = {"operator_url": "https://op.example/", "agent_id": "a1", "owner_npub": "npub1x"}
    path = tmp_path / "displays.json"
    assert displays.refresh(cfg, client_for=Client, path=path) == ["Mac mini", "Studio"]
    assert calls == [("https://op.example", "chart_agent_status",
                      {"npub": "npub1x", "dpop_token": "seven-amber-door"})]
    assert "seven-amber-door" not in path.read_text()
    assert displays.load(path) == ["Mac mini", "Studio"]
    assert not displays.stale(path)
    assert displays.stale(path, now=lambda: json.loads(path.read_text())["fetched_at"] + displays.MAX_AGE + 1)


def test_no_list_is_asked_for_without_a_pairing_or_a_sign_in(monkeypatch, tmp_path):
    monkeypatch.setattr(keystore, "load_token", lambda npub: None)
    path = tmp_path / "displays.json"
    assert displays.refresh({"operator_url": "https://op", "agent_id": "a1", "owner_npub": "npub1x"},
                            client_for=lambda *a, **k: pytest.fail("no call"), path=path) is None
    assert displays.refresh({"operator_url": None}, path=path) is None
    assert displays.load(path) == [] and displays.stale(path)


# -- the voice Shortcut ------------------------------------------------------------------------

def _voice_actions():
    return plistlib.loads(shortcut.template(shortcut.NAME))["WFWorkflowActions"]


def test_the_voice_shortcut_records_posts_the_file_and_speaks_the_reply():
    actions = _voice_actions()
    kinds = [a["WFWorkflowActionIdentifier"].removeprefix("is.workflow.actions.") for a in actions]
    assert kinds == ["repeat.count", "recordaudio", "downloadurl", "speaktext",
                     "conditional", "conditional", "exit", "conditional", "repeat.count"]
    record, post, speak = (a["WFWorkflowActionParameters"] for a in actions[1:4])
    assert (record["WFRecordingStart"], record["WFRecordingEnd"]) == ("Immediately", "After Time")
    assert record["WFRecordingTimeInterval"]["Value"] == {"Magnitude": "6", "Unit": "sec"}
    assert post["WFHTTPMethod"] == "POST" and post["WFHTTPBodyType"] == "File"
    assert post["WFURL"] == shortcut.URL_MARK + "?hear=1"
    assert post["WFRequestVariable"]["Value"]["OutputUUID"] == record["UUID"]
    headers = {i["WFKey"]["Value"]["string"]: i["WFValue"]["Value"]["string"]
               for i in post["WFHTTPHeaders"]["Value"]["WFDictionaryFieldValueItems"]}
    assert headers == {"X-Token": shortcut.TOKEN_MARK}
    assert speak["WFText"]["Value"]["attachmentsByRange"]["{0, 1}"]["OutputUUID"] == post["UUID"]


def test_the_voice_shortcut_listens_again_only_after_a_question():
    from chartremotely import voice
    actions = _voice_actions()
    test = actions[4]["WFWorkflowActionParameters"]
    assert test["WFCondition"] == 99 and test["WFConditionalActionString"].lower() in voice.LISTENING.lower()
    assert [a["WFWorkflowActionParameters"]["WFControlFlowMode"] for a in actions[4:8] if "conditional" in
            a["WFWorkflowActionIdentifier"]] == [0, 1, 2], "otherwise: stop"
    assert actions[0]["WFWorkflowActionParameters"]["WFRepeatCount"] == 3


def test_both_shortcuts_are_built_and_signed_under_their_library_names(monkeypatch, tmp_path):
    signed = []
    monkeypatch.setattr(shortcut.subprocess, "run", lambda args, **k: signed.append(Path(args[-1]))
                        or Path(args[-1]).write_bytes(Path(args[-3]).read_bytes()))
    made = shortcut.build_all("https://mac.example.ts.net/chart", "T0KEN", tmp_path)
    assert [p.name for p in made] == ["ChartRemotely.shortcut", "ChartRemotely Ask.shortcut"]
    voice = plistlib.loads(made[0].read_bytes())
    assert voice["WFWorkflowActions"][2]["WFWorkflowActionParameters"]["WFURL"] == \
        "https://mac.example.ts.net/chart?hear=1"
    assert not (tmp_path / "unsigned.shortcut").exists()
