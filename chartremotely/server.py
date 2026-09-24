"""Loopback listener fronting the command vocabulary.

Bound to 127.0.0.1 only. TLS is terminated by Tailscale Serve, which proxies
to this socket - so the wire carries a real certificate while the socket is
never exposed on the LAN.

Clients talk to it with an ordinary HTTPS request, which matters more than it
sounds: Shortcuts' SSH action re-prompts for permission every time the
shortcut is edited and needs a key per device, while Get Contents of URL
needs neither.
"""

from __future__ import annotations

import json
import secrets
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer

from . import config, forward, push
from .vocab import answer


class Handler(BaseHTTPRequestHandler):
    token = ""

    def _reply(self, code: int, text: str) -> None:
        body = (text + "\n").encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorised(self, offered) -> bool:
        return bool(offered) and secrets.compare_digest(str(offered), self.token)

    def do_POST(self) -> None:
        if urllib.parse.urlparse(self.path).path not in ("/chart", "/"):
            return self._reply(404, "ERR not found")
        if not self._authorised(self.headers.get("X-Token")):
            return self._reply(403, "ERR forbidden")
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length).decode("utf-8", "replace").strip()
        where = ""
        # Shortcuts posts JSON most cleanly; curl and scripts post raw text.
        if raw.startswith("{"):
            try:
                body = json.loads(raw)
                raw = str(body.get("cmd") or "").strip()
                where = str(body.get("where") or "").strip()
            except (ValueError, AttributeError):
                return self._reply(400, "ERR bad JSON")
        self._answer(raw, where)

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path not in ("/chart", "/"):
            return self._reply(404, "ERR not found")
        query = urllib.parse.parse_qs(parsed.query)
        if not self._authorised((query.get("t") or [None])[0]):
            return self._reply(403, "ERR forbidden")
        self._answer((query.get("cmd") or [""])[0].strip(),
                     (query.get("where") or [""])[0].strip())

    def _answer(self, request: str, where: str = "") -> None:
        """Reply first; only then schedule the picture of a changed chart.

        ``where`` names the display the command is for, as dictated. Another
        display's command is forwarded and its reply spoken; that display
        pushes its own picture, so none is scheduled here.
        """
        elsewhere = forward.route(request, where) if where and request else None
        if elsewhere is not None:
            return self._reply(200, elsewhere)
        result = answer(request)
        self._reply(200, result.reply)
        push.after_reply(request, result.reply, result.symbol)

    def log_message(self, *args) -> None:
        """Silence. Requests carry spoken input; do not write it to a log."""


def serve(port: int | None = None) -> None:
    cfg = config.load()
    Handler.token = config.ensure_token()
    HTTPServer(("127.0.0.1", port or cfg["port"]), Handler).serve_forever()
