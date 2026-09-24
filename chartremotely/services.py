"""The agent's two background services, and the one-shot checks run like them.

``serve`` (the listener a Shortcut reaches over the tailnet) and ``relay``
(the outbound poll to the operator) run under launchd as separate agents, so
a relay that loses the network cannot take the listener down with it.

macOS grants Accessibility and Screen Recording to the process that asks,
and a launchd job is its own process, distinct from the Terminal that ran
``setup``. So the permission probe runs as a one-shot launchd job too: what
it reports is what the services will actually have.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from xml.sax.saxutils import escape

LABELS = {"serve": "com.chartremotely.serve", "relay": "com.chartremotely.relay"}
PROBE_LABEL = "com.chartremotely.permissions"
AGENTS_DIR = Path(os.path.expanduser("~/Library/LaunchAgents"))
LOG_DIR = Path(os.path.expanduser("~/Library/Logs"))


def executable() -> str:
    """The installed ``chartremotely`` command, absolute."""
    found = shutil.which("chartremotely")
    return os.path.realpath(found) if found else os.path.realpath(sys.argv[0])


def render(label: str, args: list[str], *, keep_alive: bool, log: Path) -> str:
    """A LaunchAgent plist. Every value is escaped; nothing secret is ever in it."""
    arguments = "\n".join(f"    <string>{escape(a)}</string>" for a in args)
    alive = "<true/>" if keep_alive else "<false/>"
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>{escape(label)}</string>
  <key>ProgramArguments</key>
  <array>
{arguments}
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key>{alive}
  <key>ThrottleInterval</key><integer>10</integer>
  <key>StandardOutPath</key><string>{escape(str(log))}</string>
  <key>StandardErrorPath</key><string>{escape(str(log))}</string>
</dict>
</plist>
"""


def _domain() -> str:
    return f"gui/{os.getuid()}"


def loaded(label: str) -> bool:
    return subprocess.run(["launchctl", "print", f"{_domain()}/{label}"],
                          capture_output=True, check=False).returncode == 0


def install(command: str) -> Path:
    """Write and (re)start one service. Idempotent."""
    label = LABELS[command]
    path = AGENTS_DIR / f"{label}.plist"
    AGENTS_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(render(label, [executable(), command], keep_alive=True,
                           log=LOG_DIR / f"chartremotely-{command}.log"))
    if loaded(label):
        subprocess.run(["launchctl", "bootout", f"{_domain()}/{label}"], capture_output=True, check=False)
    subprocess.run(["launchctl", "bootstrap", _domain(), str(path)], check=True)
    return path


def probe_permissions(request: bool, out: Path, timeout: float = 30.0) -> dict:
    """Run ``chartremotely permissions`` as a one-shot launchd job and read its answer."""
    AGENTS_DIR.mkdir(parents=True, exist_ok=True)
    path = AGENTS_DIR / f"{PROBE_LABEL}.plist"
    out.unlink(missing_ok=True)
    args = [executable(), "permissions", "--out", str(out)] + (["--request"] if request else [])
    path.write_text(render(PROBE_LABEL, args, keep_alive=False, log=LOG_DIR / "chartremotely-permissions.log"))
    subprocess.run(["launchctl", "bootout", f"{_domain()}/{PROBE_LABEL}"], capture_output=True, check=False)
    subprocess.run(["launchctl", "bootstrap", _domain(), str(path)], check=True)
    try:
        deadline = time.time() + timeout
        while time.time() < deadline and not out.exists():
            time.sleep(0.5)
        return json.loads(out.read_text()) if out.exists() else {}
    finally:
        subprocess.run(["launchctl", "bootout", f"{_domain()}/{PROBE_LABEL}"], capture_output=True, check=False)
        path.unlink(missing_ok=True)


def permissions(request: bool) -> dict:
    """What this process has been granted; with ``request``, ask macOS to prompt."""
    result = {"python": os.path.realpath(sys.executable), "accessibility": False, "screen_recording": False}
    try:
        from ApplicationServices import AXIsProcessTrustedWithOptions, kAXTrustedCheckOptionPrompt
        result["accessibility"] = bool(AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: request}))
    except ImportError:
        pass
    try:
        import Quartz
        granted = bool(Quartz.CGPreflightScreenCaptureAccess())
        if not granted and request:
            granted = bool(Quartz.CGRequestScreenCaptureAccess())
        result["screen_recording"] = granted
    except ImportError:
        pass
    return result
