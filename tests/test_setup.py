"""`chartremotely setup`, with the Mac, the operator and the Keychain stood in for.

Runs on Linux CI: every macOS and SDK import in the code under test is lazy,
and these tests replace them. What they pin is where a patron's key may go
- the Keychain's secret field and a pipe - and where it must never go.
"""

import json
import plistlib
import re
import sys
import types

import pytest

from chartremotely import config, keystore, mcpclient, relay, services, setup, shortcut

NSEC = "nsec1" + "q" * 58
NPUB = "npub1" + "p" * 58


# -- the MCP client -------------------------------------------------------------

def test_a_json_answer_and_an_sse_answer_read_the_same():
    msg = {"jsonrpc": "2.0", "id": 1, "result": {"ok": True}}
    assert mcpclient.parse_body(json.dumps(msg)) == msg
    sse = "event: message\ndata: " + json.dumps(msg) + "\n\n"
    assert mcpclient.parse_body(sse) == msg


def test_a_tool_answer_prefers_structured_content_then_text_json():
    assert mcpclient.tool_payload({"structuredContent": {"a": 1}}) == {"a": 1}
    assert mcpclient.tool_payload({"content": [{"type": "text", "text": '{"b": 2}'}]}) == {"b": 2}


# -- the voice Shortcut ---------------------------------------------------------

def test_the_template_carries_placeholders_and_no_ones_address_or_token():
    raw = shortcut.template().decode()
    assert raw.count(shortcut.URL_MARK) >= 1 and raw.count(shortcut.TOKEN_MARK) >= 1
    assert ".ts.net" not in raw, "a real tailnet address leaked into the template"
    # Agent tokens are 43-character urlsafe strings; none may sit in a <string>.
    assert not re.search(r"<string>[A-Za-z0-9_-]{40,}</string>", raw)


def test_filling_the_template_changes_the_placeholders_and_nothing_else():
    raw = shortcut.template()
    filled = shortcut.fill(raw, "https://mac.example.ts.net/chart", "T0KEN")
    text = plistlib.dumps(filled).decode()
    assert shortcut.URL_MARK not in text and shortcut.TOKEN_MARK not in text
    back = text.replace("https://mac.example.ts.net/chart", shortcut.URL_MARK).replace("T0KEN", shortcut.TOKEN_MARK)
    assert plistlib.loads(back.encode()) == plistlib.loads(raw), "only the two values may differ"


def test_a_missing_value_is_refused_rather_than_left_as_a_placeholder():
    with pytest.raises(ValueError):
        shortcut.fill(shortcut.template(), "", "T0KEN")


# -- launchd --------------------------------------------------------------------

def test_a_service_plist_runs_the_installed_command_and_keeps_it_alive():
    plist = plistlib.loads(services.render("com.chartremotely.relay", ["/usr/local/bin/chartremotely", "relay"],
                                           keep_alive=True, log=services.LOG_DIR / "x.log").encode())
    assert plist["Label"] == "com.chartremotely.relay"
    assert plist["ProgramArguments"] == ["/usr/local/bin/chartremotely", "relay"]
    assert plist["KeepAlive"] is True and plist["RunAtLoad"] is True


def test_plist_values_are_escaped():
    text = services.render("a&b", ["/p<q>"], keep_alive=False, log=services.LOG_DIR / "x.log")
    assert plistlib.loads(text.encode())["ProgramArguments"] == ["/p<q>"]


# -- the Keychain and the clipboard ---------------------------------------------

@pytest.fixture
def fake_security(monkeypatch):
    calls = {"add": [], "update": []}
    mod = types.SimpleNamespace(
        kSecClass="class", kSecClassInternetPassword="inet", kSecAttrServer="server",
        kSecAttrAccount="account", kSecAttrLabel="label", kSecValueData="data",
        SecItemAdd=lambda q, _: calls["add"].append(q) or (calls.get("status", 0), None),
        SecItemUpdate=lambda q, attrs: calls["update"].append((q, attrs)) or 0,
    )
    monkeypatch.setitem(sys.modules, "Security", mod)
    return calls


def test_the_key_goes_into_the_keychains_secret_field_and_nowhere_else(fake_security):
    keystore.save(NPUB, NSEC)
    [query] = fake_security["add"]
    assert query["data"] == NSEC.encode()
    assert all(NSEC not in str(v) for k, v in query.items() if k != "data")
    assert query["account"] == NPUB and query["server"] == keystore.SERVER


def test_an_existing_entry_is_updated_not_duplicated(fake_security):
    fake_security["status"] = keystore.ERR_DUPLICATE
    keystore.save(NPUB, NSEC)
    [(query, attrs)] = fake_security["update"]
    assert attrs == {"data": NSEC.encode()} and "data" not in query


def test_the_clipboard_is_fed_on_a_pipe_never_a_command_line(monkeypatch):
    seen = []
    monkeypatch.setattr(keystore.subprocess, "run", lambda argv, **kw: seen.append((argv, kw)))
    keystore.copy(NSEC)
    [(argv, kw)] = seen
    assert argv == ["pbcopy"] and kw["input"] == NSEC.encode()
    assert NSEC not in " ".join(argv)


def test_the_clipboard_is_cleared_only_while_it_still_holds_the_key(monkeypatch):
    runs = []

    def run(argv, **kw):
        runs.append(argv)
        return types.SimpleNamespace(stdout=b"something else")
    monkeypatch.setattr(keystore.subprocess, "run", run)
    assert keystore.clear_if_unchanged(NSEC) is False
    assert runs == [["pbpaste"]], "a clipboard the patron has since used is left alone"


# -- proving an npub by DM --------------------------------------------------------

class StubClient:
    def __init__(self, answers):
        self.answers, self.calls = answers, []

    def call(self, tool, args):
        self.calls.append((tool, args))
        return self.answers[tool]


def test_an_existing_npub_is_proven_by_dm_and_no_key_is_asked_for():
    client = StubClient({"chart_request_npub_proof": {"dpop_token": "seven-amber-door"},
                         "chart_receive_npub_proof": {"success": True, "dpop_token": "seven-amber-door"}})
    asked, said = [], []
    token = setup.prove_by_dm(client, NPUB, lambda q: asked.append(q) or "", said.append)
    assert token == "seven-amber-door"
    assert [t for t, _ in client.calls] == ["chart_request_npub_proof", "chart_receive_npub_proof"]
    assert any("seven-amber-door" in s for s in said), "the human sees the code to compare"
    assert not any("nsec" in q.lower() for q in asked)


def test_a_dm_that_was_not_answered_stops_setup():
    client = StubClient({"chart_request_npub_proof": {"dpop_token": "x"},
                         "chart_receive_npub_proof": {"error": "no reply yet"}})
    with pytest.raises(setup.SetupError, match="no reply yet"):
        setup.prove_by_dm(client, NPUB, lambda q: "", lambda s: None)


# -- pairing, with no code to copy ------------------------------------------------

def test_setup_adopts_its_own_pairing_code(monkeypatch):
    monkeypatch.setattr(relay, "open_code", lambda base: ("ABC234", 900.0))
    collected = []
    monkeypatch.setattr(relay, "collect", lambda base, code, exp: collected.append(code) or {"agent_id": "a1"})
    client = StubClient({"chart_pair_agent": {"ok": True, "display": "Desk", "agent_id": "a1"}})
    setup.pair(client, "https://op.test", NPUB, "PROOF", "Desk")
    assert client.calls == [("chart_pair_agent", {"code": "ABC234", "label": "Desk", "npub": NPUB,
                                                  "dpop_token": "PROOF"})]
    assert collected == ["ABC234"]


def test_a_refused_pairing_says_why(monkeypatch):
    monkeypatch.setattr(relay, "open_code", lambda base: ("ABC234", 900.0))
    client = StubClient({"chart_pair_agent": {"success": False, "error": "prove it"}})
    with pytest.raises(setup.SetupError, match="prove it"):
        setup.pair(client, "https://op.test", NPUB, "PROOF", "Desk")


# -- the whole run never keeps the key -------------------------------------------

def test_a_made_key_never_reaches_the_agents_config(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(setup, "new_key", lambda: (NPUB, NSEC))
    monkeypatch.setattr(setup, "sign_once", lambda nsec, tool: f"proof-for-{tool}")
    kept = []
    monkeypatch.setattr(setup, "keep_for_human", lambda npub, nsec, ask, say: kept.append(npub))
    monkeypatch.setattr(relay, "open_code", lambda base: ("ABC234", 900.0))
    monkeypatch.setattr(relay, "collect", lambda base, code, exp: config.update(
        operator_url=base, agent_id="a1", agent_secret="agent-secret"))
    monkeypatch.setattr(mcpclient, "Client", lambda base: StubClient(
        {"chart_pair_agent": {"ok": True, "display": "Desk", "agent_id": "a1"}}))

    from chartremotely import tailnet
    monkeypatch.setattr(tailnet, "status", lambda: {"Self": {"DNSName": "mac.example.ts.net."}})
    monkeypatch.setattr(tailnet, "serve", lambda port: None)
    monkeypatch.setattr(services, "install", lambda command: None)
    monkeypatch.setattr(services, "probe_permissions",
                        lambda request, out: {"accessibility": True, "screen_recording": True})
    built = []
    monkeypatch.setattr(shortcut, "build", lambda url, token: built.append(url) or tmp_path / "x.shortcut")
    monkeypatch.setattr(setup.subprocess, "run", lambda *a, **k: None)

    answers = iter(["3", "Desk"])
    said = []
    assert setup.run(ask=lambda q: next(answers), say=said.append) == 0

    stored = (tmp_path / "config.json").read_text()
    assert NSEC not in stored and "proof-for" not in stored
    assert json.loads(stored)["agent_id"] == "a1"
    assert kept == [NPUB], "the made key is handed to the human's Keychain"
    assert built == ["https://mac.example.ts.net/chart"]
    assert not any(NSEC in s for s in said), "the key is never printed"
