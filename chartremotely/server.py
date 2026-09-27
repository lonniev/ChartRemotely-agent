"""Loopback listener fronting the command vocabulary.

Bound to 127.0.0.1 only. TLS is terminated by Tailscale Serve, which proxies
to this socket - so the wire carries a real certificate while the socket is
never exposed on the LAN.

Clients talk to it with an ordinary HTTPS request, which matters more than it
sounds: Shortcuts' SSH action re-prompts for permission every time the
shortcut is edited and needs a key per device, while Get Contents of URL
needs neither.

A POST marked ``?hear`` (or sent as ``audio/*``) is a recorded sentence
instead of a command: see :mod:`voice`. A JSON body ``{"said": ...}`` is a
typed sentence - what the Shortcut posts from its typing box - understood the
same way (:func:`voice.respond_typed`).
"""

from __future__ import annotations

import json
import secrets
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer

from . import config, displays, hearing, patron, requestlog
from .vocab import answer

#: Verbs answered here, for free: they look something up and leave the chart alone.
LOOKUPS = frozenset({"resolve", "scale"})


def is_recording(query: str, content_type: str | None) -> bool:
    """Is this POST a recorded sentence rather than a typed command?

    Tailscale Serve forwards only ``/chart``, so a recording arrives on the
    same path, told apart by ``?hear`` (the Shortcut's flag) or an audio
    Content-Type.
    """
    if "hear" in urllib.parse.parse_qs(query, keep_blank_values=True):
        return True
    kind = (content_type or "").split(";")[0].strip().lower()
    return kind.startswith("audio/")


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
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path not in ("/chart", "/"):
            return self._reply(404, "ERR not found")
        if not self._authorised(self.headers.get("X-Token")):
            return self._reply(403, "ERR forbidden")
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return self._reply(400, "ERR bad length")
        if is_recording(parsed.query, self.headers.get("Content-Type")):
            return self._hear(length)
        raw = self.rfile.read(length).decode("utf-8", "replace").strip()
        where = ""
        # Shortcuts posts JSON most cleanly; curl and scripts post raw text.
        if raw.startswith("{"):
            try:
                body = json.loads(raw)
                if "said" in body:
                    return self._typed(body.get("said"))
                raw = str(body.get("cmd") or "").strip()
                where = str(body.get("where") or "").strip()
            except (ValueError, AttributeError, TypeError):
                return self._reply(400, "ERR bad JSON")
        self._answer(raw, where)

    def _typed(self, said) -> None:
        """A typed sentence from the Shortcut's text box (see :mod:`voice`)."""
        from . import voice

        self._reply(200, voice.respond_typed(said if isinstance(said, str) else ""))

    def _hear(self, length: int) -> None:
        """A recorded sentence: hear it, understand it, answer it (see :mod:`voice`).

        Too long a recording is refused without being kept, in words the
        Shortcut can speak.
        """
        if length > hearing.MAX_BYTES:
            self._discard(length)
            return self._reply(200, f"ERR That was longer than {int(hearing.MAX_SECONDS)} seconds. Say it shorter.")
        audio = self.rfile.read(length) if length > 0 else b""
        from . import voice

        reply = voice.respond(audio, self.headers.get("Content-Type"))
        self._reply(200, reply)

    def _discard(self, length: int, limit: int = 32 * 1024 * 1024) -> None:
        """Read and drop a body we refuse, so the client hears the refusal
        rather than a reset connection; past ``limit``, just hang up after."""
        if length > limit:
            self.close_connection = True
            return
        while length > 0:
            chunk = self.rfile.read(min(length, 65536))
            if not chunk:
                break
            length -= len(chunk)

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
        """Answer a lookup here; ask the operator's priced tool for the rest.

        ``resolve`` and ``scale`` are the Shortcut's free checks before it
        asks for a change: they read a table, never the chart. Everything
        else is a patron's tool call (see :mod:`patron`) - ``where`` names the
        display as dictated, blank meaning this Mac. The reply is the
        hand-off, spoken at once; the chart changes after, through a relay,
        which also takes its picture.
        """
        if request.partition(" ")[0].lower() in LOOKUPS:
            reply = answer(request).reply
        elif request:
            reply = patron.send(request, where)
        else:
            reply = "ERR I didn't catch that."
        self._reply(200, reply)
        requestlog.request("serve", request, where, reply)

    def log_message(self, *args) -> None:
        """Silence the stock access log: its request line can carry ``?t=<token>``.

        Each handled command is logged by :mod:`requestlog` instead, verb only.
        """


def serve(port: int | None = None) -> None:
    cfg = config.load()
    Handler.token = config.ensure_token()
    # Load the speech model and the display names now, not on the first sentence.
    hearing.warm_in_background()
    displays.refresh_in_background()
    HTTPServer(("127.0.0.1", port or cfg["port"]), Handler).serve_forever()
