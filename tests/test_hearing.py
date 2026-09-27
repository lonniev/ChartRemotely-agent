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

#: A recording big enough to be one: anything under hearing.MIN_BYTES is a bare header.
M4A = b"m4a-bytes" * 100


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
        assert source.read_bytes() == M4A, "the recording is handed over as sent"
        if not self.fail:
            _wav(target, self.frames, channels=self.channels)
        return subprocess.CompletedProcess(args, 1 if self.fail else 0)


# -- decoding ------------------------------------------------------------------------

def test_decode_asks_afconvert_for_16k_mono_pcm_and_leaves_nothing_behind():
    run = FakeAfconvert()
    pcm = hearing.decode(M4A, "audio/x-m4a", run=run)
    assert run.args[:7] == [hearing.AFCONVERT, "-f", "WAVE", "-d", "LEI16@16000", "-c", "1"]
    assert run.args[-2].endswith(".m4a")
    assert len(pcm) == hearing.RATE * 2
    assert not run.folder.exists(), "the recording must not outlive the reply"


def test_the_recording_type_picks_what_afconvert_reads():
    assert hearing.suffix_for("audio/wav") == ".wav"
    assert hearing.suffix_for("audio/x-caf; codecs=aac") == ".caf"
    assert hearing.suffix_for(None) == ".m4a"
    assert hearing.suffix_for("application/octet-stream") == ".m4a"


@pytest.mark.parametrize("audio,run,said,unheard", [
    (b"", FakeAfconvert(), "didn't hear anything", True),
    # What a Mac mini (no microphone) sends once Record Audio is stopped: 28 bytes, a header.
    (bytes.fromhex("0000001c667479704d344120000000004d3441206d70343269736f6d"),
     FakeAfconvert(), "didn't hear anything", True),
    (b"x" * (hearing.MAX_BYTES + 1), FakeAfconvert(), "longer than 15 seconds", False),
    (M4A, FakeAfconvert(fail=True), "couldn't read", True),
    (M4A, FakeAfconvert(frames=int(hearing.RATE * 16)), "longer than 15 seconds", False),
    (M4A, FakeAfconvert(channels=2), "not in a shape", True),
])
def test_a_recording_that_cannot_be_heard_says_why(audio, run, said, unheard):
    with pytest.raises(hearing.HearingError, match=said) as got:
        hearing.decode(audio, "audio/m4a", run=run)
    assert isinstance(got.value, hearing.Unheard) is unheard, "only too long a recording is spoken"


def _pcm(level: int, seconds: float) -> bytes:
    return int(level).to_bytes(2, "little", signed=True) * int(hearing.RATE * seconds)


def test_silence_and_a_blip_are_not_usable_and_speech_is():
    assert not hearing.usable(b"")
    assert not hearing.usable(_pcm(0, 6)), "a Mac with no microphone records digital silence"
    assert not hearing.usable(_pcm(20, 6)), "a quiet room"
    assert not hearing.usable(_pcm(3000, 0.1)), "too short to be a word"
    assert hearing.usable(_pcm(3000, 1.0))
    assert hearing.usable(_pcm(-3000, 1.0))


@pytest.mark.parametrize("text", ["", " ", ".", "Thank you.", "you", "Thanks for watching!", "[Music]", "Um..."])
def test_what_whisper_makes_of_silence_is_filler(text):
    assert hearing.filler(text)


@pytest.mark.parametrize("text", ["Palantir half on mac mini.", "PLTR", "half", "Apple as is"])
def test_a_request_is_not_filler(text):
    assert not hearing.filler(text)


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
    with pytest.raises(hearing.Unheard, match="cannot hear yet"):
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


# -- the Shortcut: talk, or type when it asks ----------------------------------------------

def _actions():
    return plistlib.loads(shortcut.template())["WFWorkflowActions"]


def _kinds(actions):
    return [a["WFWorkflowActionIdentifier"].removeprefix("is.workflow.actions.") for a in actions]


def _params(actions, kind):
    return [a["WFWorkflowActionParameters"] for a in actions if _kinds([a])[0] == kind]


def _said(post):
    """The JSON a POST sends: {key: text or the output it carries}."""
    got = {}
    for item in post["WFJSONValues"]["Value"]["WFDictionaryFieldValueItems"]:
        value = item["WFValue"]["Value"]
        got[item["WFKey"]["Value"]["string"]] = value["attachmentsByRange"]["{0, 1}"]["OutputUUID"] \
            if "attachmentsByRange" in value else value["string"]
    return got


def _headers(post):
    return {i["WFKey"]["Value"]["string"]: i["WFValue"]["Value"]["string"]
            for i in post["WFHTTPHeaders"]["Value"]["WFDictionaryFieldValueItems"]}


def test_the_shortcut_records_posts_branches_on_the_marker_asks_one_line_posts_the_text_and_speaks():
    from chartremotely import voice
    actions = _actions()
    kinds = _kinds(actions)
    assert kinds == ["getdevicedetails", "repeat.count",
                     "conditional", "downloadurl", "conditional", "recordaudio", "downloadurl", "conditional",
                     "setvariable",
                     "conditional", "repeat.count", "text.replace", "ask", "downloadurl", "setvariable",
                     "conditional", "conditional", "speaktext", "exit", "conditional", "repeat.count", "exit",
                     "conditional",
                     "speaktext", "conditional", "conditional", "exit", "conditional", "repeat.count"]
    record = actions[5]["WFWorkflowActionParameters"]
    audio = actions[6]["WFWorkflowActionParameters"]
    assert (record["WFRecordingStart"], record["WFRecordingEnd"]) == ("Immediately", "After Time")
    assert record["WFRecordingTimeInterval"]["Value"] == {"Magnitude": "6", "Unit": "sec"}
    assert audio["WFHTTPMethod"] == "POST" and audio["WFHTTPBodyType"] == "File"
    assert audio["WFURL"] == shortcut.URL_MARK + "?hear=1"
    assert audio["WFRequestVariable"]["Value"]["OutputUUID"] == record["UUID"]
    assert _headers(audio) == {"X-Token": shortcut.TOKEN_MARK}

    marker = actions[9]["WFWorkflowActionParameters"]
    assert (marker["WFCondition"], marker["WFConditionalActionString"]) == (99, voice.TYPE)
    assert marker["WFInput"]["Variable"]["Value"]["VariableName"] == "Reply"
    strip = actions[11]["WFWorkflowActionParameters"]
    assert (strip["WFReplaceTextFind"], strip["WFReplaceTextReplace"]) == (voice.TYPE, "")

    asks = _params(actions, "ask")
    assert len(asks) == 1, "one text box"
    ask = asks[0]
    assert ask["WFAskActionAllowsMultilineText"] is False, "Return sends it"
    assert ask["WFInputType"] == "Text"
    assert ask["WFAskActionPrompt"]["Value"]["attachmentsByRange"]["{0, 1}"]["OutputUUID"] == strip["UUID"], \
        "the prompt is the listener's, after TYPE:"

    typed = actions[13]["WFWorkflowActionParameters"]
    assert typed["WFURL"] == shortcut.URL_MARK and typed["WFHTTPBodyType"] == "JSON"
    assert _said(typed) == {"said": ask["UUID"]}
    assert _headers(typed) == {"Content-Type": "application/json", "X-Token": shortcut.TOKEN_MARK}
    spoken = actions[17]["WFWorkflowActionParameters"]["WFText"]["Value"]["attachmentsByRange"]["{0, 1}"]
    assert spoken["OutputUUID"] == typed["UUID"], "the typed reply is spoken, then the Shortcut stops"


def test_a_mac_goes_straight_to_the_typing_box():
    actions = _actions()
    device = actions[0]["WFWorkflowActionParameters"]
    assert device["WFDeviceDetail"] == "Device Model"
    mac = actions[2]["WFWorkflowActionParameters"]
    assert (mac["WFCondition"], mac["WFConditionalActionString"]) == (99, "Mac")
    assert mac["WFInput"]["Variable"]["Value"]["OutputUUID"] == device["UUID"]
    blank = actions[3]["WFWorkflowActionParameters"]
    assert _said(blank) == {"said": ""}, "a blank typed request asks for the box"
    assert _kinds(actions[4:7]) == ["conditional", "recordaudio", "downloadurl"], "otherwise: record"
    joined = actions[7]["WFWorkflowActionParameters"]
    assert actions[8]["WFWorkflowActionParameters"]["WFInput"]["Value"]["OutputUUID"] == joined["UUID"]


def test_a_spoken_question_records_again_and_a_typed_one_asks_again():
    from chartremotely import voice
    actions = _actions()
    listen = actions[24]["WFWorkflowActionParameters"]
    assert listen["WFCondition"] == 99 and listen["WFConditionalActionString"].lower() in voice.LISTENING.lower()
    assert _kinds(actions[25:27]) == ["conditional", "exit"], "otherwise: stop"
    again = actions[15]["WFWorkflowActionParameters"]
    assert again["WFConditionalActionString"] == voice.TYPE, "a typed question comes back as TYPE:"
    assert actions[1]["WFWorkflowActionParameters"]["WFRepeatCount"] == 3
    assert actions[10]["WFWorkflowActionParameters"]["WFRepeatCount"] == 3
    groups = {}
    for a in actions:
        p = a["WFWorkflowActionParameters"]
        if "GroupingIdentifier" in p:
            groups.setdefault(p["GroupingIdentifier"], []).append(p["WFControlFlowMode"])
    assert all(modes[0] == 0 and modes[-1] == 2 for modes in groups.values()), "every block is closed"


def test_the_one_shortcut_is_built_and_signed_under_its_library_name(monkeypatch, tmp_path):
    monkeypatch.setattr(shortcut.subprocess, "run", lambda args, **k:
                        Path(args[-1]).write_bytes(Path(args[-3]).read_bytes()))
    made = shortcut.build("https://mac.example.ts.net/chart", "T0KEN", tmp_path)
    assert made.name == "ChartRemotely.shortcut"
    posts = _params(plistlib.loads(made.read_bytes())["WFWorkflowActions"], "downloadurl")
    assert [p["WFURL"] for p in posts] == ["https://mac.example.ts.net/chart",
                                           "https://mac.example.ts.net/chart?hear=1",
                                           "https://mac.example.ts.net/chart"]
    assert not (tmp_path / "unsigned.shortcut").exists()
