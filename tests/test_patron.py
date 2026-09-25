"""The listener as a patron: voice commands are the operator's priced tool calls.

The operator is a stand-in MCP client and the Keychain a dict, so this runs on
Linux without the macOS drivers.
"""

import importlib
import json
import plistlib
import sys
import threading
import time
import types
import urllib.request

import pytest

from chartremotely import config, keystore, mcpclient, patron, shortcut
from chartremotely.answer import Answer

NPUB = "npub1" + "p" * 58
TOKEN = "seven-amber-door"


class FakeOperator:
    """Answers tool calls with what a test sets, optionally after a gate opens."""

    def __init__(self):
        self.calls = []
        self.answers = {"chart_show_chart": {"ok": True, "display": "Desk", "result": "Showing PLTR"},
                        "chart_read_chart": {"ok": True, "display": "Desk", "result": "PLTR at daily"},
                        "chart_request_npub_proof": {"success": True, "dpop_token": "fresh-code"},
                        "chart_receive_npub_proof": [{"success": True, "dpop_token": "fresh-code"}]}
        self.gate = threading.Event()
        self.gate.set()
        self.lock = threading.Lock()

    def client(self, base, timeout=60.0):
        operator = self

        class Client:
            def call(self, tool, args):
                with operator.lock:
                    operator.calls.append((tool, dict(args)))
                if tool not in ("chart_request_npub_proof", "chart_receive_npub_proof"):
                    operator.gate.wait(10)
                answer = operator.answers[tool]
                if isinstance(answer, list):
                    return answer.pop(0) if len(answer) > 1 else answer[0]
                if isinstance(answer, Exception):
                    raise answer
                return answer
        return Client()

    def tools(self):
        return [t for t, _ in self.calls]


@pytest.fixture
def operator(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    config.update(operator_url="https://op.test", agent_id="a1", agent_secret="s1", owner_npub=NPUB)
    fake = FakeOperator()
    monkeypatch.setattr(mcpclient, "Client", fake.client)
    vault = {NPUB: TOKEN}
    monkeypatch.setattr(keystore, "load_token", lambda npub: vault.get(npub))
    monkeypatch.setattr(keystore, "save_token", lambda npub, token: vault.__setitem__(npub, token))
    monkeypatch.setattr(patron, "RENEW_DELAYS", (0.0,) * 5)
    fake.vault = vault
    yield fake
    fake.gate.set()
    _wait_for_renewal()


def _wait_for_renewal(seconds=5.0):
    """Block until no renewal holds the lock (it releases when it ends)."""
    assert patron._renewing.acquire(timeout=seconds), "a renewal never finished"
    patron._renewing.release()


# -- the envelope ------------------------------------------------------------------

def test_a_set_calls_chart_show_chart_as_the_owner_with_this_macs_id_when_where_is_blank(operator):
    said = patron.send("set PLTR | half", "")
    assert said == "Chart PLTR at half scale sent to this Mac. Good luck."
    assert operator.calls == [("chart_show_chart", {
        "security": "PLTR", "scale": "half", "display": "a1", "npub": NPUB, "dpop_token": TOKEN})]


def test_a_named_display_goes_as_said_and_the_hand_off_names_it(operator):
    assert (patron.send("set PLTR\n | half\n", " Mac-mini\n")
            == "Chart PLTR at half scale sent to Mac-mini. Good luck.")
    [(_, args)] = operator.calls
    assert args["display"] == "Mac-mini" and args["security"] == "PLTR" and args["scale"] == "half"


@pytest.mark.parametrize(("cmd", "said"), [
    ("set PLTR | as is", "Chart PLTR sent to desk. Good luck."),
    ("set PLTR", "Chart PLTR sent to desk. Good luck."),
    ("john deere", "Chart john deere sent to desk. Good luck."),
])
def test_as_is_leaves_the_scale_out_of_the_call_and_the_words(operator, cmd, said):
    assert patron.send(cmd, "desk") == said
    assert operator.calls[0][1]["scale"] == ""


def test_read_calls_chart_read_chart_and_speaks_what_it_shows(operator):
    assert patron.send("read", "") == "PLTR at daily"
    assert operator.tools() == ["chart_read_chart"]


def test_a_snapshot_is_not_bought_by_voice(operator):
    assert patron.send("snapshot", "").startswith("ERR A picture cannot be spoken")
    assert operator.calls == []


# -- the hand-off ----------------------------------------------------------------------

@pytest.mark.parametrize(("answer", "said"), [
    ({"success": False, "error_code": "insufficient_balance",
      "error": "Insufficient balance: 2 sats available, 3 required for chart_show_chart."},
     "ERR Insufficient balance: 2 sats available, 3 required for chart_show_chart."),
    ({"success": False, "error_code": "tool_input_invalid", "error": "no display named 'kitchen'"},
     "ERR no display named 'kitchen'"),
    ({"success": False, "error_code": "tool_input_invalid",
      "error": "the display did not answer; is the agent running?"},
     "ERR the display did not answer; is the agent running?"),
    ({"ok": False, "display": "Desk", "result": "ERR thinkorswim is not running"},
     "ERR thinkorswim is not running"),
])
def test_an_early_refusal_is_spoken(operator, answer, said):
    operator.answers["chart_show_chart"] = answer
    assert patron.send("set PLTR | half", "kitchen") == said


def test_an_unreachable_operator_is_spoken_not_raised(operator):
    operator.answers["chart_show_chart"] = mcpclient.McpError("could not reach the operator: refused")
    assert patron.send("set PLTR | half", "").startswith("ERR could not reach the operator")


def test_a_slow_call_is_handed_off_at_once_and_its_outcome_logged_later(operator, monkeypatch, capsys):
    monkeypatch.setattr(patron, "HANDOFF_SECONDS", 0.2)
    operator.gate.clear()
    started = time.monotonic()
    assert patron.send("set PLTR | half", "Mac-mini") == "Chart PLTR at half scale sent to Mac-mini. Good luck."
    assert time.monotonic() - started < 1.0
    operator.answers["chart_show_chart"] = {"success": False, "error": "Mac-mini did not answer"}
    operator.gate.set()
    for _ in range(50):
        if "tool=chart_show_chart" in capsys.readouterr().err:
            break
        time.sleep(0.05)
    else:
        pytest.fail("the call's outcome was never logged")


def test_the_real_hand_off_window_is_about_three_seconds():
    assert 2.0 <= patron.HANDOFF_SECONDS <= 3.5


# -- the sign-in -------------------------------------------------------------------------

def test_an_expired_sign_in_is_spoken_and_renewed_once(operator, monkeypatch):
    monkeypatch.setattr(patron, "RENEW_DELAYS", (0.5, 0.0, 0.0, 0.0))  # still waiting at the 2nd command
    operator.answers["chart_show_chart"] = {"success": False, "error_code": "proof_refresh_needed",
                                            "error": "proof expired"}
    operator.answers["chart_receive_npub_proof"] = [
        {"success": False, "error_code": "courier_not_found", "error": "No reply found"},
        {"success": False, "error_code": "courier_not_found", "error": "No reply found"},
        {"success": True, "dpop_token": "fresh-code"}]
    assert patron.send("set PLTR | half", "") == patron.EXPIRED
    assert patron.send("set PLTR | half", "") == patron.EXPIRED
    _wait_for_renewal()
    assert operator.tools().count("chart_request_npub_proof") == 1, "one renewal at a time"
    assert operator.tools().count("chart_receive_npub_proof") == 3
    request = next(a for t, a in operator.calls if t == "chart_request_npub_proof")
    assert request["patron_npub"] == NPUB and "nsec" not in json.dumps(request).lower()
    assert operator.vault[NPUB] == "fresh-code"


def test_no_sign_in_yet_starts_the_dm_without_calling_the_paid_tool(operator):
    operator.vault.clear()
    assert patron.send("set PLTR | half", "") == patron.EXPIRED
    _wait_for_renewal()
    assert "chart_show_chart" not in operator.tools()
    assert operator.vault[NPUB] == "fresh-code"


def test_a_renewal_that_is_refused_stops_rather_than_polling_on(operator):
    operator.vault.clear()
    operator.answers["chart_receive_npub_proof"] = [{"success": False, "error_code": "courier_expired",
                                                     "error": "that request expired"}]
    patron.send("set PLTR | half", "")
    _wait_for_renewal()
    assert operator.tools().count("chart_receive_npub_proof") == 1
    assert NPUB not in operator.vault


def test_the_sign_in_is_never_logged_or_written_to_the_config(operator, capsys, monkeypatch):
    monkeypatch.setattr(patron, "HANDOFF_SECONDS", 0.2)
    patron.send("set PLTR | half", "desk")
    operator.answers["chart_show_chart"] = {"success": False, "error_code": "proof_invalid", "error": "bad"}
    patron.send("set PLTR | half", "desk")
    _wait_for_renewal()
    time.sleep(0.1)
    logged = capsys.readouterr().err
    assert TOKEN not in logged and "fresh-code" not in logged and "PLTR" not in logged
    stored = config.CONFIG_PATH.read_text()
    assert TOKEN not in stored and "fresh-code" not in stored
    assert json.loads(stored)["owner_npub"] == NPUB


def test_an_unpaired_or_ownerless_mac_says_to_run_setup(operator):
    config.update(owner_npub=None)
    assert "does not know whose display" in patron.send("set PLTR", "")
    config.update(agent_id=None, owner_npub=NPUB)
    assert "not paired" in patron.send("set PLTR", "")
    assert operator.calls == []


# -- the listener ---------------------------------------------------------------------------

@pytest.fixture
def listener(operator, monkeypatch):
    """The Shortcut's listener with a stand-in vocab. Returns (post, ran)."""
    ran = []
    fake_vocab = types.ModuleType("chartremotely.vocab")
    fake_vocab.answer = lambda cmd: ran.append(cmd) or Answer("PLTR")
    monkeypatch.setitem(sys.modules, "chartremotely.vocab", fake_vocab)
    monkeypatch.delitem(sys.modules, "chartremotely.server", raising=False)
    server = importlib.import_module("chartremotely.server")
    server.Handler.token = "T0KEN"
    from http.server import HTTPServer
    http = HTTPServer(("127.0.0.1", 0), server.Handler)
    threading.Thread(target=http.serve_forever, daemon=True).start()

    def post(body):
        request = urllib.request.Request(
            f"http://127.0.0.1:{http.server_address[1]}/chart", data=json.dumps(body).encode(),
            method="POST", headers={"Content-Type": "application/json", "X-Token": "T0KEN"})
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.read().decode().strip()

    yield post, ran
    http.shutdown()


def test_the_listener_hands_a_change_to_the_priced_tool_and_never_drives_the_chart(listener, operator):
    post, ran = listener
    assert post({"cmd": "set PLTR | half", "where": ""}) == "Chart PLTR at half scale sent to this Mac. Good luck."
    assert ran == [], "the relay drives the chart, never the listener"
    assert operator.tools() == ["chart_show_chart"]


@pytest.mark.parametrize("cmd", ["resolve palantir", "scale half"])
def test_lookups_are_answered_here_and_never_sent(listener, operator, cmd):
    post, ran = listener
    post({"cmd": cmd, "where": "desk"})
    assert ran == [cmd] and operator.calls == []


# -- the Shortcut --------------------------------------------------------------------------

def test_the_shortcut_asks_where_after_scale_and_sends_it_beside_cmd():
    actions = plistlib.loads(shortcut.template())["WFWorkflowActions"]
    prompts = [a["WFWorkflowActionParameters"].get("WFAskActionPrompt") for a in actions]
    assert prompts.index("Where?") > prompts.index("What scale?")
    final = next(a for a in actions[prompts.index("Where?"):]
                 if a["WFWorkflowActionIdentifier"].endswith(".downloadurl"))["WFWorkflowActionParameters"]
    fields = {i["WFKey"]["Value"]["string"]: i["WFValue"]["Value"]
              for i in final["WFJSONValues"]["Value"]["WFDictionaryFieldValueItems"]}
    assert fields["cmd"]["string"] == "set ￼ | ￼", "the vocab grammar is unchanged"
    where = actions[prompts.index("Where?")]["WFWorkflowActionParameters"]["UUID"]
    assert fields["where"]["attachmentsByRange"]["{0, 1}"]["OutputUUID"] == where
