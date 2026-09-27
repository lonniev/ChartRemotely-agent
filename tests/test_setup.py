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


# -- the Shortcut ---------------------------------------------------------------

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


def test_only_the_one_template_ships():
    from importlib import resources
    assets = sorted(p.name for p in resources.files("chartremotely").joinpath("assets").iterdir())
    assert assets == ["shortcut.plist"]


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


@pytest.fixture
def fake_launchd(monkeypatch, tmp_path):
    """A launchd that lets go of a label only after a few polls, as the real one does."""
    state = {"loaded": True, "polls_until_gone": 3, "bootstrap_failures": 0, "calls": []}

    def loaded(label):
        if state["loaded"] and state.get("booted_out"):
            state["polls_until_gone"] -= 1
            if state["polls_until_gone"] <= 0:
                state["loaded"] = False
        return state["loaded"]

    def run(args, **kwargs):
        state["calls"].append(args[1])
        if args[1] == "bootout":
            state["booted_out"] = True
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")
        if state["loaded"] or state["bootstrap_failures"] > 0:
            state["bootstrap_failures"] = max(0, state["bootstrap_failures"] - 1)
            return types.SimpleNamespace(returncode=5, stdout="", stderr="Bootstrap failed: 5: Input/output error")
        state["loaded"] = True
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(services, "AGENTS_DIR", tmp_path)
    monkeypatch.setattr(services, "loaded", loaded)
    monkeypatch.setattr(services.subprocess, "run", run)
    monkeypatch.setattr(services.time, "sleep", lambda s: None)
    monkeypatch.setattr(services, "executable", lambda: "/usr/local/bin/chartremotely")
    return state


def test_reinstalling_a_running_service_waits_for_launchd_to_let_go(fake_launchd):
    services.install("serve")
    assert fake_launchd["calls"] == ["bootout", "bootstrap"]
    assert fake_launchd["loaded"] is True


def test_a_bootstrap_refused_while_launchd_settles_is_tried_again(fake_launchd):
    fake_launchd["bootstrap_failures"] = 2
    services.install("serve")
    assert fake_launchd["calls"].count("bootstrap") == 3


def test_a_bootstrap_that_never_succeeds_stops_setup_with_launchds_reason(fake_launchd, monkeypatch):
    fake_launchd["bootstrap_failures"] = 10**6
    with pytest.raises(services.ServiceError, match="Input/output error"):
        services.install("serve", settle=0)


# -- the Keychain and the clipboard ---------------------------------------------

@pytest.fixture
def fake_security(monkeypatch):
    calls = {"add": [], "update": []}
    mod = types.SimpleNamespace(
        kSecClass="class", kSecClassInternetPassword="inet", kSecAttrServer="server",
        kSecAttrAccount="account", kSecAttrLabel="label", kSecValueData="data",
        kSecClassGenericPassword="generic", kSecAttrService="service",
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


def test_the_voice_sign_in_goes_into_its_own_keychain_item_and_nowhere_else(fake_security):
    keystore.save_token(NPUB, "seven-amber-door")
    [query] = fake_security["add"]
    assert query["data"] == b"seven-amber-door"
    assert all("seven-amber-door" not in str(v) for k, v in query.items() if k != "data")
    assert query["class"] == "generic" and query["service"] == keystore.TOKEN_SERVICE
    assert query["account"] == NPUB and "server" not in query, "never mixed with a saved key"


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
    assert any("cache_duration" in s and "unlimited" in s for s in said), "a longer sign-in is offered"
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
    monkeypatch.setattr(shortcut, "remove_retired", lambda: ([], []))
    _no_hearing(monkeypatch)
    monkeypatch.setattr(setup.subprocess, "run", lambda *a, **k: None)

    answers = iter(["3", "Desk", "n"])
    said = []
    assert setup.run(ask=lambda q: next(answers), say=said.append) == 0

    stored = (tmp_path / "config.json").read_text()
    assert NSEC not in stored and "proof-for" not in stored
    assert json.loads(stored)["agent_id"] == "a1"
    assert kept == [NPUB], "the made key is handed to the human's Keychain"
    assert built == ["https://mac.example.ts.net/chart"]
    assert not any(NSEC in s for s in said), "the key is never printed"


def _no_hearing(monkeypatch):
    """No test downloads the speech model or asks the operator for display names."""
    from chartremotely import displays, hearing
    monkeypatch.setattr(hearing, "fetch_model", lambda say: False)
    monkeypatch.setattr(displays, "refresh", lambda *a, **k: None)


def _stand_in_the_mac(monkeypatch, tmp_path, answers):
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(relay, "open_code", lambda base: ("ABC234", 900.0))
    monkeypatch.setattr(relay, "collect", lambda base, code, exp: config.update(
        operator_url=base, agent_id="a1", agent_secret="agent-secret"))
    monkeypatch.setattr(mcpclient, "Client", lambda base: StubClient(answers))
    from chartremotely import tailnet
    monkeypatch.setattr(tailnet, "status", lambda: {"Self": {"DNSName": "mac.example.ts.net."}})
    monkeypatch.setattr(tailnet, "serve", lambda port: None)
    monkeypatch.setattr(services, "install", lambda command: None)
    monkeypatch.setattr(services, "probe_permissions",
                        lambda request, out: {"accessibility": True, "screen_recording": True})
    monkeypatch.setattr(shortcut, "build", lambda url, token: tmp_path / "x.shortcut")
    monkeypatch.setattr(shortcut, "remove_retired", lambda: ([], []))
    monkeypatch.setattr(setup.subprocess, "run", lambda *a, **k: None)
    _no_hearing(monkeypatch)
    vault = {}
    monkeypatch.setattr(keystore, "save_token", lambda npub, token: vault.__setitem__(npub, token))
    monkeypatch.setattr(keystore, "load_token", lambda npub: vault.get(npub))
    return vault


def test_a_dm_proven_owner_keeps_the_sign_in_in_the_keychain_not_the_config(monkeypatch, tmp_path):
    vault = _stand_in_the_mac(monkeypatch, tmp_path, {
        "chart_request_npub_proof": {"dpop_token": "seven-amber-door"},
        "chart_receive_npub_proof": {"success": True, "dpop_token": "seven-amber-door"},
        "chart_pair_agent": {"ok": True, "display": "Desk", "agent_id": "a1"}})
    answers = iter(["1", NPUB, "", "Desk"])
    said = []
    assert setup.run(ask=lambda q: next(answers), say=said.append) == 0
    assert vault == {NPUB: "seven-amber-door"}
    stored = (tmp_path / "config.json").read_text()
    assert "seven-amber-door" not in stored
    assert json.loads(stored)["owner_npub"] == NPUB


def test_an_already_paired_mac_is_signed_in_for_voice_by_dm(monkeypatch, tmp_path):
    vault = _stand_in_the_mac(monkeypatch, tmp_path, {
        "chart_request_npub_proof": {"dpop_token": "seven-amber-door"},
        "chart_receive_npub_proof": {"success": True, "dpop_token": "seven-amber-door"}})
    config.update(operator_url="https://op.test", agent_id="a1", agent_secret="agent-secret")
    answers = iter([NPUB, "y", ""])
    assert setup.run(ask=lambda q: next(answers), say=lambda s: None) == 0
    assert vault == {NPUB: "seven-amber-door"}
    assert "seven-amber-door" not in (tmp_path / "config.json").read_text()


def test_setup_removes_a_retired_ask_shortcut_and_names_any_it_could_not(monkeypatch, tmp_path):
    _stand_in_the_mac(monkeypatch, tmp_path, {
        "chart_request_npub_proof": {"dpop_token": "seven-amber-door"},
        "chart_receive_npub_proof": {"success": True, "dpop_token": "seven-amber-door"}})
    config.update(operator_url="https://op.test", agent_id="a1", agent_secret="agent-secret")
    monkeypatch.setattr(shortcut, "remove_retired", lambda: (["ChartRemotely Ask"], ["ChartRemotely Ask 2"]))
    answers = iter([NPUB, "y", ""])
    said = []
    assert setup.run(ask=lambda q: next(answers), say=said.append) == 0
    assert "Removed “ChartRemotely Ask”; “ChartRemotely” does it all now." in said
    assert "Delete “ChartRemotely Ask 2” in the Shortcuts app; “ChartRemotely” does it all now." in said


class Library:
    """The Shortcuts library as `shortcuts list` and Shortcuts Events see it."""

    def __init__(self, *names, refuse=()):
        self.names, self.refuse, self.scripts = list(names), set(refuse), []

    def __call__(self, args, **kwargs):
        import subprocess
        if args[:2] == ["shortcuts", "list"]:
            return subprocess.CompletedProcess(args, 0, stdout="\n".join(self.names) + "\n")
        assert args[:2] == ["osascript", "-e"]
        self.scripts.append(args[2])
        name = args[2].split('delete shortcut "', 1)[1][:-1]
        if name in self.refuse:
            return subprocess.CompletedProcess(args, 1)
        self.names.remove(name)
        return subprocess.CompletedProcess(args, 0)


def test_only_the_ask_shortcuts_are_removed_and_the_real_one_is_kept():
    library = Library("ChartRemotely", "ChartRemotely Ask", "ChartRemotely Ask 2", "ChartRemotely 3", "Ask Me",
                      refuse={"ChartRemotely Ask 2"})
    assert shortcut.remove_retired(run=library) == (["ChartRemotely Ask"], ["ChartRemotely Ask 2"])
    assert library.names == ["ChartRemotely", "ChartRemotely Ask 2", "ChartRemotely 3", "Ask Me"]
    assert all("Shortcuts Events" in s for s in library.scripts)


def test_nothing_but_a_retired_shortcut_can_be_removed():
    with pytest.raises(ValueError):
        shortcut.remove("ChartRemotely", run=lambda *a, **k: pytest.fail("never asked"))


def test_no_shortcuts_command_means_nothing_to_remove():
    def missing(*a, **k):
        raise OSError("no shortcuts")
    assert shortcut.remove_retired(run=missing) == ([], [])
