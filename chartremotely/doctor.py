"""Check everything the agent needs, and say what to do about each failure.

Written for someone who cannot see the screen. When a wall display in
another building goes quiet, this is the first thing to run - so every
check names the fix, not just the symptom.
"""

from __future__ import annotations

import os
import urllib.error
import urllib.request

from . import config

OK, BAD, WARN = "  ok  ", " FAIL ", " warn "


def _check_pyobjc() -> tuple[str, str]:
    try:
        import Quartz  # noqa: F401
        from ApplicationServices import AXUIElementCreateApplication  # noqa: F401
    except ImportError:
        return BAD, 'PyObjC missing - pip install "chartremotely[macos]"'
    return OK, "PyObjC present"


def _check_app() -> tuple[str, str]:
    from . import ax
    try:
        app = ax.running_app()
    except ax.NotRunning:
        return BAD, "thinkorswim is not running - start it"
    return OK, f"thinkorswim running (pid {app.processIdentifier()})"


def permission_verdict(granted: dict) -> tuple[str, str]:
    """What the services' own Python holds; see :func:`services.probe_permissions`."""
    if not granted:
        return BAD, "the permission check did not answer - run: chartremotely setup"
    missing = [name for name, key in (("Accessibility", "accessibility"),
                                      ("Screen Recording", "screen_recording")) if not granted.get(key)]
    if missing:
        python = granted.get("python", "the services' Python")
        return BAD, (f"{' and '.join(missing)} off for {python} - "
                     "run: chartremotely setup (a Python upgrade revokes both)")
    return OK, "Accessibility and Screen Recording allowed for the services' Python"


def _check_permissions() -> tuple[str, str]:
    """Asked as a launchd job, as the services run: the Terminal's own grants say nothing about theirs."""
    import tempfile
    from pathlib import Path

    from . import services
    return permission_verdict(services.probe_permissions(
        request=False, out=Path(tempfile.gettempdir()) / "chartremotely-permissions.json"))


def service_verdict(running: dict[str, str | None], exists=os.path.exists) -> tuple[str, str]:
    """Each service, and whether the Python it runs is still on disk."""
    stopped = [name for name, python in running.items() if python is None]
    orphaned = [name for name, python in running.items() if python and not exists(python)]
    if orphaned:
        kick = "; ".join(f"launchctl kickstart -k gui/$UID/com.chartremotely.{name}" for name in orphaned)
        return BAD, (f"{', '.join(orphaned)} still on a Python that was upgraded away - "
                     f"restart: {kick}, then run: chartremotely doctor")
    if stopped:
        return BAD, f"{', '.join(stopped)} not running - run: chartremotely setup"
    return OK, "serve and relay running"


def _check_services() -> tuple[str, str]:
    from . import services
    return service_verdict({name: services.running_python(name) for name in services.LABELS})


def _check_controls() -> tuple[str, str]:
    from . import ax, symbol, timeframe
    cfg = config.load()
    try:
        ax_app = ax.handle()
        ax.activate()
    except ax.NotRunning:
        return WARN, "skipped - thinkorswim is not running"
    found_symbol = symbol.discover(ax_app, cfg["window_prefix"])
    found_scale = timeframe.discover(ax_app, cfg["window_prefix"])
    if not found_symbol:
        return BAD, "no symbol field found - is a chart visible in the window?"
    if not found_scale:
        return WARN, "symbol field found, but no aggregation control - scale changes unavailable"
    return OK, f"symbol field at {found_symbol}, aggregation at {found_scale}"


def _check_registry() -> tuple[str, str]:
    from . import registry
    if not registry.CACHE.exists():
        return WARN, "security registry not cached yet - it downloads on first use"
    try:
        rows = registry.load()
    except (OSError, ValueError) as exc:
        return BAD, f"registry unreadable: {exc}"
    if not config.load().get("contact"):
        return WARN, (f"{len(rows)} securities cached, but no contact address set - "
                      "the SEC answers 403 without one. Set it in config.json.")
    return OK, f"{len(rows)} securities cached"


def _check_listener() -> tuple[str, str]:
    cfg = config.load()
    port = cfg["port"]
    token = cfg.get("token")
    if not token:
        return WARN, "no token yet - it is generated when the listener first starts"
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/chart", data=b"read",
        headers={"X-Token": token}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return OK, f"listener answering on :{port} - {response.read().decode().strip()}"
    except urllib.error.URLError:
        return WARN, f"nothing listening on :{port} - run: chartremotely serve"


CHECKS = (
    ("PyObjC", _check_pyobjc),
    ("thinkorswim", _check_app),
    ("Services", _check_services),
    ("Permissions", _check_permissions),
    ("Chart controls", _check_controls),
    ("Registry", _check_registry),
    ("Listener", _check_listener),
)


def report() -> int:
    """Print every check. Returns non-zero if any hard check failed."""
    failed = False
    for name, check in CHECKS:
        try:
            status, detail = check()
        except Exception as exc:  # noqa: BLE001 - a doctor must never crash
            status, detail = BAD, f"check raised: {exc}"
        if status == BAD:
            failed = True
        print(f"[{status}] {name:<16} {detail}")
    return 1 if failed else 0
