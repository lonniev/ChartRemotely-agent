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
    config.update(operator_url=base, agent_id="a1", agent_secret="s1")
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
    handled = threading.Event()

    class Finishing(server.Handler):
        # The reply goes out before the picture is scheduled, so a test that
        # checks pictures must wait for the whole request, not just its reply.
        def handle(self):
            try:
                super().handle()
            finally:
                handled.set()

    http = HTTPServer(("127.0.0.1", 0), Finishing)
    threading.Thread(target=http.serve_forever, daemon=True).start()

    def post(body):
        handled.clear()
        request = urllib.request.Request(
            f"http://127.0.0.1:{http.server_address[1]}/chart", data=json.dumps(body).encode(),
            method="POST", headers={"Content-Type": "application/json", "X-Token": "T0KEN"})
        with urllib.request.urlopen(request, timeout=10) as response:
            reply = response.read().decode().strip()
        assert handled.wait(5), "the listener never finished the request"
        return reply

    yield post, ran, pictures
    http.shutdown()


# -- the listener ----------------------------------------------------------------

def test_no_where_runs_here_exactly_as_before(listener):
    post, ran, pictures = listener
    assert post({"cmd": "set PLTR | daily"}) == "Showing PLTR at daily. Good luck."
    assert ran == ["set PLTR | daily"] and len(pictures) == 1
    assert StubOperator.seen == []


@pytest.mark.parametrize("said", ["", "  ", "a1", " a1 "])
def test_blank_or_this_macs_agent_id_runs_here_without_asking(listener, said):
    post, ran, _ = listener
    post({"cmd": "set PLTR | daily", "where": said})
    assert ran == ["set PLTR | daily"] and StubOperator.seen == []


@pytest.mark.parametrize("said", ["Desk", "desk", "mini mac", "A1"])
def test_every_name_is_matched_by_the_operator_not_here(listener, said):
    post, ran, _ = listener
    StubOperator.answer = (200, {"self": True, "display": "Desk"})
    post({"cmd": "set PLTR | daily", "where": said})
    assert [body["display"] for _, body in StubOperator.seen] == [said.strip()]
    assert ran == ["set PLTR | daily"], "the operator said it is this Mac, so it runs here"


def test_is_here_is_blank_or_the_exact_agent_id():
    cfg = {"agent_id": "a1"}
    assert forward.is_here("", cfg) and forward.is_here(" a1 ", cfg)
    assert not forward.is_here("A1", cfg) and not forward.is_here("Desk", cfg)
    assert forward.is_here("", {}) and not forward.is_here("a1", {})


def test_each_request_is_logged_once_without_the_token_or_arguments(listener, capsys):
    post, _, _ = listener
    capsys.readouterr()
    post({"cmd": "set PLTR | daily", "where": "desk"})
    StubOperator.answer = (404, {"error": "no display named 'kitchen'", "displays": ["Desk"]})
    post({"cmd": "read", "where": "kitchen"})
    lines = capsys.readouterr().err.strip().splitlines()
    assert len(lines) == 2
    assert "serve verb=set where='desk'" in lines[0] and "reply=" not in lines[0]
    assert "verb=read where='kitchen' reply='ERR No display named \"kitchen\". Yours: Desk.'" in lines[1]
    for line in lines:
        assert "T0KEN" not in line and "s1" not in line and "PLTR" not in line


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

def test_the_operator_saying_self_runs_here(operator):
    StubOperator.answer = (200, {"self": True, "display": "Desk"})
    assert forward.route("read", "desk") is None


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


def test_a_forwarded_command_carries_no_newlines_from_the_shortcut(listener):
    post, ran, pictures = listener
    # The Shortcut splices this Mac's own replies ("PLTR\n", "half\n") into the command.
    post({"cmd": "set PLTR\n | half\n", "where": "Office\n"})
    _, sent = StubOperator.seen[-1]
    assert sent["cmd"] == "set PLTR | half"
    assert sent["display"] == "Office"
    assert ran == [] and pictures == []
