"""Just enough of an MCP client to call three operator tools.

``setup`` proves who the patron is and pairs this machine, which means
calling ``chart_request_npub_proof``, ``chart_receive_npub_proof`` and
``chart_pair_agent``. A full MCP SDK would be the only reason this agent
grew a dependency tree, so this speaks the streamable-HTTP transport
directly: initialize, the initialized notification, then ``tools/call``,
reading JSON or server-sent-event answers and carrying the session header.

Stdlib only, importable anywhere.
"""

from __future__ import annotations

import itertools
import json
import urllib.request

PROTOCOL_VERSION = "2025-06-18"


class McpError(RuntimeError):
    """The operator could not be reached, or answered with an error."""


def parse_body(raw: str) -> dict:
    """One JSON-RPC message, from a JSON body or the last SSE ``data:`` line."""
    raw = raw.strip()
    if not raw:
        return {}
    if raw.startswith("{"):
        return json.loads(raw)
    data = [line[5:].strip() for line in raw.splitlines() if line.startswith("data:")]
    if not data:
        raise McpError("the operator sent an answer this client cannot read")
    return json.loads(data[-1])


def tool_payload(result: dict) -> dict:
    """What a tool answered: its structured content, else its first text block as JSON."""
    if isinstance(result.get("structuredContent"), dict):
        return result["structuredContent"]
    for block in result.get("content") or []:
        if block.get("type") == "text":
            try:
                parsed = json.loads(block.get("text") or "")
            except ValueError:
                return {"text": block.get("text")}
            return parsed if isinstance(parsed, dict) else {"value": parsed}
    return {}


class Client:
    """A session with one operator's ``/mcp`` endpoint."""

    def __init__(self, base_url: str, timeout: float = 60.0) -> None:
        self.url = base_url.rstrip("/") + "/mcp"
        self.timeout = timeout
        self.session: str | None = None
        self._ids = itertools.count(1)

    def _send(self, message: dict) -> dict:
        headers = {"Content-Type": "application/json",
                   "Accept": "application/json, text/event-stream"}
        if self.session:
            headers["mcp-session-id"] = self.session
        request = urllib.request.Request(
            self.url, data=json.dumps(message).encode(), headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                self.session = response.headers.get("mcp-session-id") or self.session
                return parse_body(response.read().decode("utf-8", "replace"))
        except OSError as exc:
            raise McpError(f"could not reach the operator: {exc}") from None

    def _start(self) -> None:
        if self.session:
            return
        answer = self._send({
            "jsonrpc": "2.0", "id": next(self._ids), "method": "initialize",
            "params": {"protocolVersion": PROTOCOL_VERSION, "capabilities": {},
                       "clientInfo": {"name": "chartremotely-setup", "version": "1"}}})
        if "error" in answer:
            raise McpError(str(answer["error"].get("message", answer["error"])))
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def call(self, tool: str, arguments: dict) -> dict:
        """Call a tool and return what it answered. Raises McpError on a protocol error."""
        self._start()
        answer = self._send({"jsonrpc": "2.0", "id": next(self._ids), "method": "tools/call",
                             "params": {"name": tool, "arguments": arguments}})
        if "error" in answer:
            raise McpError(str(answer["error"].get("message", answer["error"])))
        result = answer.get("result") or {}
        payload = tool_payload(result)
        if result.get("isError"):
            raise McpError(payload.get("text") or json.dumps(payload) or "the tool failed")
        return payload
