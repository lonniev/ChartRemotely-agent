"""This Mac as a *holder*: a connection the operator knows, into whose wallet
the owner's npub is proven by Nostr DM.

The agent holds no key and keeps no grant. It keeps only this connection's
OAuth tokens, in the login Keychain (as the owner's voice sign-in), and names
the npub on each priced call; the operator checks the grant it holds.

Becoming a holder is the OAuth Authorization Code flow, run headless: the
operator's ``/authorize`` approves at once (a holder holds nothing until a DM
proves an npub into it), so the agent reads the code from the redirect
instead of opening a browser. A refresh token is single-use, so each refresh
stores the pair it returns.

Stdlib only, like the rest of the listener.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request

from . import keystore

REDIRECT_URI = "http://127.0.0.1/holder"
#: Refresh this long before the access token lapses.
REFRESH_EARLY_SECONDS = 60


class HolderError(RuntimeError):
    """The operator would not connect this Mac."""


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _post(url: str, body: bytes, content_type: str) -> dict:
    request = urllib.request.Request(url, data=body, method="POST", headers={"Content-Type": content_type})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        raise HolderError(f"the operator refused ({exc.code})") from None
    except OSError as exc:
        raise HolderError(f"could not reach the operator: {exc}") from None


class _KeepRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _token(base: str, form: dict, client_id: str) -> dict:
    t = _post(f"{base}/token",
              urllib.parse.urlencode({**form, "client_id": client_id, "resource": f"{base}/mcp"}).encode(),
              "application/x-www-form-urlencoded")
    return {"client_id": client_id, "access_token": t["access_token"], "refresh_token": t["refresh_token"],
            "expires_at": time.time() + float(t.get("expires_in") or 3600)}


def _login(base: str) -> dict:
    client_id = _post(f"{base}/register", json.dumps({
        "client_name": "ChartRemotely agent",
        "redirect_uris": [REDIRECT_URI],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
    }).encode(), "application/json")["client_id"]
    verifier = _b64url(secrets.token_bytes(48))
    state = _b64url(secrets.token_bytes(16))
    query = urllib.parse.urlencode({
        "response_type": "code", "client_id": client_id, "redirect_uri": REDIRECT_URI, "state": state,
        "code_challenge": _b64url(hashlib.sha256(verifier.encode()).digest()),
        "code_challenge_method": "S256", "resource": f"{base}/mcp",
    })
    try:
        urllib.request.build_opener(_KeepRedirect).open(f"{base}/authorize?{query}", timeout=30)
        raise HolderError("the operator did not redirect back")
    except urllib.error.HTTPError as exc:
        location = exc.headers.get("Location", "")
    back = urllib.parse.parse_qs(urllib.parse.urlparse(location).query)
    if back.get("state") != [state] or not back.get("code"):
        raise HolderError("the operator's reply did not match this connection")
    return _token(base, {"grant_type": "authorization_code", "code": back["code"][0],
                         "redirect_uri": REDIRECT_URI, "code_verifier": verifier}, client_id)


def _stored(npub: str) -> dict | None:
    raw = keystore.load_token(npub)
    try:
        t = json.loads(raw) if raw else None
    except ValueError:
        return None  # a sign-in saved before this Mac connected as a holder
    return t if isinstance(t, dict) and t.get("refresh_token") else None


def bearer(base: str, npub: str) -> str:
    """The bearer for the next call: refreshed when it is about to lapse, or a
    fresh connection when there is none. Raises HolderError or KeystoreError."""
    t = _stored(npub)
    if t and t["expires_at"] - REFRESH_EARLY_SECONDS <= time.time():
        try:
            t = _token(base, {"grant_type": "refresh_token", "refresh_token": t["refresh_token"]}, t["client_id"])
        except HolderError:
            t = None
    if not t:
        t = _login(base)
    keystore.save_token(npub, json.dumps(t))
    return t["access_token"]


def connected(npub: str) -> bool:
    """True when this Mac has a connection to the operator for ``npub``."""
    try:
        return _stored(npub) is not None
    except keystore.KeystoreError:
        return False
