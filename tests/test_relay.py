"""Relay client, against a stub operator.

Exercises the wire contract without a real operator, a network, or a GUI,
so CI can run it on Linux.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import ClassVar

import pytest

from chartremotely import relay


class StubOperator(BaseHTTPRequestHandler):
    """Implements the four agent routes from PROTOCOL.md."""

    code = "ABC234"
    claimed = False
    commands: ClassVar[list] = []
    results: ClassVar[list] = []

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        route = self.path

        if route == "/agent/open":
            payload = {"code": self.code, "expires_in": 900}
        elif route == "/agent/collect":
            payload = ({"paired": True, "agent_id": "a1", "secret": "s1"}
                       if type(self).claimed else {"paired": False})
        elif route == "/agent/poll":
            if body.get("agent_id") != "a1" or body.get("secret") != "s1":
                self.send_response(403); self.end_headers(); return
            payload = type(self).commands.pop(0) if type(self).commands else {}
        elif route == "/agent/result":
            type(self).results.append(body)
            payload = {"accepted": True}
        else:
            self.send_response(404); self.end_headers(); return

        raw = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *args):
        pass


@pytest.fixture
def operator(monkeypatch, tmp_path):
    StubOperator.claimed = False
    StubOperator.commands = []
    StubOperator.results = []
    server = HTTPServer(("127.0.0.1", 0), StubOperator)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    # Keep pairing state out of the developer's real config.
    from chartremotely import config
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(relay, "CLAIM_INTERVAL", 0.01)
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


def test_pairing_stores_the_identity(operator):
    StubOperator.claimed = True
    shown = []
    cfg = relay.pair(operator, on_code=shown.append)
    assert shown == [StubOperator.code]
    assert cfg["agent_id"] == "a1"
    assert cfg["agent_secret"] == "s1"
    assert cfg["operator_url"] == operator


def test_pairing_gives_up_when_nobody_claims(operator, monkeypatch):
    monkeypatch.setattr(relay, "CLAIM_INTERVAL", 0.01)
    original = relay._post

    def expire(url, payload, timeout):
        result = original(url, payload, timeout)
        if url.endswith("/agent/open"):
            result["expires_in"] = 0.05
        return result

    monkeypatch.setattr(relay, "_post", expire)
    with pytest.raises(relay.PairingError, match="expired"):
        relay.pair(operator, on_code=lambda c: None)


def test_a_relayed_command_is_dispatched_and_answered(operator, monkeypatch):
    StubOperator.claimed = True
    relay.pair(operator, on_code=lambda c: None)
    StubOperator.commands.append({"id": "r1", "command": "read"})
    # The vocabulary is the agent's own; stub it so no GUI is required.
    monkeypatch.setattr(relay, "execute", lambda cmd: f"dispatched:{cmd}")
    relay.run(once=True)
    assert StubOperator.results == [
        {"agent_id": "a1", "secret": "s1", "id": "r1", "reply": "dispatched:read"}]


def test_an_idle_poll_reports_nothing(operator, monkeypatch):
    StubOperator.claimed = True
    relay.pair(operator, on_code=lambda c: None)
    monkeypatch.setattr(relay, "execute", lambda cmd: "should not be called")
    relay.run(once=True)
    assert StubOperator.results == []


def test_running_unpaired_is_refused(monkeypatch, tmp_path):
    from chartremotely import config
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "none.json")
    with pytest.raises(relay.PairingError, match="not paired"):
        relay.run("http://127.0.0.1:1")


def test_an_unreachable_operator_is_survivable(monkeypatch, tmp_path):
    """The display must keep working locally when the operator is down."""
    from chartremotely import config
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    config.update(operator_url="http://127.0.0.1:1", agent_id="a1", agent_secret="s1")
    relay.run(once=True)   # returns rather than raising


def test_the_wire_logic_imports_without_the_macos_drivers():
    """A guard, because this boundary has been broken twice.

    relay, resolve and scales must stay importable where PyObjC is absent -
    that is what lets CI run the logic on Linux. Importing vocab at module
    scope in relay silently breaks it, and the failure only shows up in CI.
    """
    import ast
    from pathlib import Path

    forbidden = {"Quartz", "AppKit", "ApplicationServices", "CoreFoundation"}
    for name in ("relay", "resolve", "scales", "config", "registry", "snapshot", "push",
                 "mcpclient", "keystore", "services", "tailnet", "shortcut", "setup"):
        tree = ast.parse(Path(f"chartremotely/{name}.py").read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                names = {(node.module or "").split(".")[0]}
            else:
                continue
            # Only module-scope imports matter; lazy ones inside functions
            # are the sanctioned escape hatch.
            if node.col_offset == 0:
                assert not (names & forbidden), f"{name}.py imports {names & forbidden} at module scope"
