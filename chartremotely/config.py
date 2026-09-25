"""One configuration file, in one place.

Replaces the scattered ``~/.config/tos-symbol.json`` and
``~/.config/tos-chart-token`` of the prototype.
"""

from __future__ import annotations

import json
import os
import secrets
from pathlib import Path

CONFIG_DIR = Path(os.path.expanduser("~/.config/chartremotely"))
CONFIG_PATH = CONFIG_DIR / "config.json"
DATA_DIR = Path(os.path.expanduser("~/.local/share/chartremotely"))

DEFAULTS: dict = {
    # Window whose title starts with this holds the chart. The build number
    # is deliberately excluded so a thinkorswim update does not break it.
    "window_prefix": "Main@thinkorswim",
    # Offsets are relative to the WINDOW, not the screen, so moving or
    # resizing the window does not invalidate them.
    "symbol_dx": None,
    "symbol_dy": None,
    "aggregation_dx": None,
    "aggregation_dy": None,
    # Row height should match the underlying's strike increment so volume
    # profile buckets land on tradable strikes.
    "row_height": "1.0",
    # The SEC wants a contactable address on registry requests.
    "contact": None,
    # Set once the agent is adopted by an operator.
    "operator_url": None,
    "agent_id": None,
    "agent_secret": None,
    # Whose display this is: the npub voice commands are billed to. Its
    # sign-in (the dpop_token) lives in the login Keychain, never here.
    "owner_npub": None,
    "token": None,
    "port": 8899,
}


def load() -> dict:
    cfg = dict(DEFAULTS)
    if CONFIG_PATH.exists():
        cfg.update(json.loads(CONFIG_PATH.read_text()))
    return cfg


def save(cfg: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, indent=2))
    tmp.chmod(0o600)
    tmp.replace(CONFIG_PATH)


def update(**changes) -> dict:
    cfg = load()
    cfg.update(changes)
    save(cfg)
    return cfg


def ensure_token() -> str:
    cfg = load()
    if not cfg.get("token"):
        cfg = update(token=secrets.token_urlsafe(32))
    return cfg["token"]
