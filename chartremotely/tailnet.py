"""This Mac's place on the patron's tailnet.

The voice Shortcut reaches the agent at an HTTPS address that exists only
inside the patron's Tailscale network. ``tailscale serve`` gives the Mac that
address and forwards ``/chart`` to the agent's loopback listener.
"""

from __future__ import annotations

import json
import shutil
import subprocess

DOWNLOAD = "https://tailscale.com/download/mac"
APP_CLI = "/Applications/Tailscale.app/Contents/MacOS/Tailscale"


class TailnetError(RuntimeError):
    """Tailscale is missing, signed out, or refused."""


def cli() -> str:
    found = shutil.which("tailscale")
    if found:
        return found
    if shutil.which(APP_CLI) or subprocess.run(["test", "-x", APP_CLI], check=False).returncode == 0:
        return APP_CLI
    raise TailnetError(f"Tailscale is not installed. Install it from {DOWNLOAD}, sign in, then run setup again.")


def status() -> dict:
    ran = subprocess.run([cli(), "status", "--json"], capture_output=True, text=True, check=False)
    if ran.returncode != 0:
        raise TailnetError("Tailscale is not running or not signed in. Open Tailscale and sign in.")
    return json.loads(ran.stdout or "{}")


def chart_url(state: dict) -> str:
    """The Shortcut's address: this Mac's tailnet name plus ``/chart``."""
    name = ((state.get("Self") or {}).get("DNSName") or "").rstrip(".")
    if not name:
        raise TailnetError("Tailscale reports no name for this Mac. Is MagicDNS on?")
    return f"https://{name}/chart"


def serve(port: int) -> None:
    """Forward ``/chart`` on the tailnet address to the agent. Persistent and tailnet-only."""
    ran = subprocess.run([cli(), "serve", "--bg", "--set-path", "/chart", f"http://127.0.0.1:{port}"],
                         capture_output=True, text=True, check=False)
    if ran.returncode != 0:
        raise TailnetError(f"tailscale serve refused: {(ran.stderr or ran.stdout).strip()[:200]}")
