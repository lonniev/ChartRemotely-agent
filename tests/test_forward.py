"""Where?: this Mac, or another of the owner's displays through the operator.

The operator is a stub HTTP server and vocab is a stand-in, so this runs on
Linux without the macOS drivers.
"""

import importlib
import json
import plistlib
import sys
import threading
import types
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import ClassVar

import pytest

from chartremotely import config, forward, shortcut
from chartremotely.answer import Answer


class StubOperator(BaseHTTPRequestHandler):
    """``/agent/forward`` answering with whatever a test queues."""

    answer: ClassVar[tuple[int, dict]] = (200, {})
    seen: ClassVar[list] = []

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)))
        type(self).seen.append((self.path, body))
        status, payload = type(self).answer
        raw = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *args):
        pass


@pytest.fixture
def operator(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    StubOperator.seen = []
    StubOperator.answer = (200, {"display": "Mac Mini", "reply": "Showing PLTR at daily. Good luck."})
    server = HTTPServer(("127.0.0.1", 0), StubOperator)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    config.update(operator_url=base, agent_id="a1", agent_secret="s1", display_label="Desk")
    yield base
    server.shutdown()


@pytest.fixture
def listener(operator, monkeypatch):
    """The Shortcut's listener, with a stand-in vocab. Returns (post, ran, pictures)."""
    ran, pictures = [], []
    fake_vocab = types.ModuleType("chartremotely.vocab")
    fake_vocab.answer = lambda cmd: ran.append(cmd) or Answer("Showing PLTR at daily. Good luck.", "PLTR")
    monkeypatch.setitem(sys.modules, "chartremotely.vocab", fake_vocab)
    monkeypatch.delitem(sys.modules, "chartremotely.server", raising=False)
    server = importlib.import_module("chartremotely.server")   # bound to the stand-in vocab
    from chartremotely import push
    monkeypatch.setattr(push, "after_reply", lambda *a: pictures.append(a))
    server.Handler.token = "T0KEN"
    http = HTTPServer(("127.0.0.1", 0), server.Handler)
    threading.Thread(target=http.serve_forever, daemon=True).start()

    def post(body):
        request = urllib.request.Request(
            f"http://127.0.0.1:{http.server_address[1]}/chart", data=json.dumps(body).encode(),
            method="POST", headers={"Content-Type": "application/json", "X-Token": "T0KEN"})
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.read().decode().strip()

    yield post, ran, pictures
    http.shutdown()


# -- the listener ----------------------------------------------------------------

def test_no_where_runs_here_exactly_as_before(listener):
    post, ran, pictures = listener
    assert post({"cmd": "set PLTR | daily"}) == "Showing PLTR at daily. Good luck."
    assert ran == ["set PLTR | daily"] and len(pictures) == 1
    assert StubOperator.seen == []


@pytest.mark.parametrize("said", ["Desk", "desk", " DESK ", "a1"])
def test_this_macs_own_name_runs_here(listener, said):
    post, ran, _ = listener
    post({"cmd": "set PLTR | daily", "where": said})
    assert ran == ["set PLTR | daily"] and StubOperator.seen == []


def test_another_name_is_forwarded_verbatim_and_its_reply_spoken(listener):
    post, ran, pictures = listener
    assert post({"cmd": "set PLTR | daily", "where": "mac-mini"}) == "Showing PLTR at daily. Good luck."
    assert StubOperator.seen == [("/agent/forward", {
        "agent_id": "a1", "secret": "s1", "display": "mac-mini", "cmd": "set PLTR | daily"})]
    assert ran == [] and pictures == [], "the target runs it and pushes its own picture"


def test_an_unknown_name_is_spoken_back_with_the_owners_names(listener):
    post, _, _ = listener
    StubOperator.answer = (404, {"error": "no display named 'kitchen'", "displays": ["Desk", "Mac Mini"]})
    assert post({"cmd": "read", "where": "kitchen"}) == 'ERR No display named "kitchen". Yours: Desk, Mac Mini.'


# -- forward.route -----------------------------------------------------------------

def test_the_operator_saying_self_runs_here_and_remembers_the_name(operator):
    config.update(display_label=None)
    StubOperator.answer = (200, {"self": True, "display": "Desk"})
    assert forward.route("read", "desk") is None
    assert config.load()["display_label"] == "Desk"


def test_an_offline_display_is_said_plainly(operator):
    StubOperator.answer = (503, {"error": "attic is offline", "display": "attic"})
    assert forward.route("read", "attic") == "ERR attic is offline"


def test_an_unpaired_mac_can_only_drive_itself(operator):
    config.update(agent_id=None, agent_secret=None)
    assert forward.route("read", "attic").startswith("ERR This Mac is not paired")
    assert forward.route("read", "") is None


def test_an_unreachable_operator_is_an_error_not_an_exception(operator):
    config.update(operator_url="http://127.0.0.1:1")
    assert forward.route("read", "attic") == "ERR I could not reach the operator."


@pytest.mark.parametrize("said", ["Mac mini", "mac-mini", "macmini", "MAC_MINI", "mac.mini"])
def test_the_name_rule_is_the_operators(said):
    assert forward.display_key(said) == "macmini"


# -- the Shortcut ------------------------------------------------------------------

def test_the_shortcut_asks_where_after_scale_and_sends_it_beside_cmd():
    actions = plistlib.loads(shortcut.template())["WFWorkflowActions"]
    prompts = [a["WFWorkflowActionParameters"].get("WFAskActionPrompt") for a in actions]
    assert prompts.index("Where?") > prompts.index("What scale?")
    final = actions[prompts.index("Where?") + 1]["WFWorkflowActionParameters"]
    fields = {i["WFKey"]["Value"]["string"]: i["WFValue"]["Value"]
              for i in final["WFJSONValues"]["Value"]["WFDictionaryFieldValueItems"]}
    assert fields["cmd"]["string"] == "set ￼ | ￼", "the vocab grammar is unchanged"
    where = actions[prompts.index("Where?")]["WFWorkflowActionParameters"]["UUID"]
    assert fields["where"]["attachmentsByRange"]["{0, 1}"]["OutputUUID"] == where
