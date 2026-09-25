"""Keep a patron's secrets in their login Keychain, never in this agent's files.

Two kinds, never mixed: the Nostr key ``setup`` may make for the human, and
the voice sign-in - the ``dpop_token`` the operator returns once the owner
has proven their npub by DM - which the listener passes on each priced call.

A key made by ``setup`` belongs to the human. It goes into their login
Keychain as an internet password for the ChartRemotely site, and it is
handed to Safari once, through the clipboard, so Safari can save it to
iCloud Passwords where their other devices and apps find it. A command-line
tool cannot write a synchronizable Keychain item itself (that needs an
entitled app: ``errSecMissingEntitlement``), which is why Safari does the
syncing.

Nothing here writes a key or a token to the agent's config, a log, a URL or
a command line. Each travels as ``kSecValueData`` or on a pipe, and nowhere else.
"""

from __future__ import annotations

import subprocess
import threading

SERVER = "chartremotely.tollbooth-dpyc.com"
LABEL = "ChartRemotely — Nostr key"
#: The voice sign-in is a generic password under this service, one per npub.
TOKEN_SERVICE = "ChartRemotely voice sign-in"
CLIPBOARD_SECONDS = 60

ERR_DUPLICATE = -25299
ERR_NOT_FOUND = -25300


class KeystoreError(RuntimeError):
    """The Keychain refused, and says why by its status code."""


def _security():
    import Security  # lazy: macOS only

    return Security


def item_query(npub: str) -> dict:
    """The attributes that name one saved key. The secret is never among them."""
    S = _security()
    return {S.kSecClass: S.kSecClassInternetPassword,
            S.kSecAttrServer: SERVER,
            S.kSecAttrAccount: npub}


def _upsert(query: dict, label: str, secret: bytes, what: str) -> None:
    """Add one item, or replace the secret of the one already there."""
    S = _security()
    status = S.SecItemAdd({**query, S.kSecAttrLabel: label, S.kSecValueData: secret}, None)[0]
    if status == ERR_DUPLICATE:
        status = S.SecItemUpdate(query, {S.kSecValueData: secret})
    if status != 0:
        raise KeystoreError(f"the Keychain refused to save the {what} (status {status})")


def save(npub: str, nsec: str) -> None:
    """Store (or replace) the patron's key in their login Keychain."""
    _upsert(item_query(npub), LABEL, nsec.encode(), "key")


def token_query(npub: str) -> dict:
    """The attributes that name one npub's voice sign-in. The token is never among them."""
    S = _security()
    return {S.kSecClass: S.kSecClassGenericPassword,
            S.kSecAttrService: TOKEN_SERVICE,
            S.kSecAttrAccount: npub}


def save_token(npub: str, token: str) -> None:
    """Store (or replace) the voice sign-in for ``npub``."""
    _upsert(token_query(npub), TOKEN_SERVICE, token.encode(), "sign-in")


def load_token(npub: str) -> str | None:
    """The voice sign-in for ``npub``; None when there is none yet."""
    S = _security()
    status, data = S.SecItemCopyMatching({**token_query(npub), S.kSecReturnData: True}, None)
    if status == ERR_NOT_FOUND or (status == 0 and data is None):
        return None
    if status != 0:
        raise KeystoreError(f"the Keychain would not give the sign-in (status {status})")
    return bytes(data).decode()


def saved_npubs() -> list[str]:
    """npubs with a key saved for this site. Reads names only, never secrets."""
    S = _security()
    query = {S.kSecClass: S.kSecClassInternetPassword, S.kSecAttrServer: SERVER,
             S.kSecReturnAttributes: True, S.kSecMatchLimit: S.kSecMatchLimitAll}
    status, found = S.SecItemCopyMatching(query, None)
    if status == ERR_NOT_FOUND or not found:
        return []
    if status != 0:
        raise KeystoreError(f"the Keychain could not be read (status {status})")
    return sorted(str(item.get(S.kSecAttrAccount) or "") for item in found if item.get(S.kSecAttrAccount))


def load(npub: str) -> str:
    """The saved key for one npub. macOS asks the human before it answers."""
    S = _security()
    status, data = S.SecItemCopyMatching({**item_query(npub), S.kSecReturnData: True}, None)
    if status != 0 or data is None:
        raise KeystoreError(f"no key saved for {npub} (status {status})")
    return bytes(data).decode()


# -- the clipboard, for Safari's Save password prompt --------------------------

def copy(secret: str) -> None:
    """Put a secret on the clipboard over a pipe, never on a command line."""
    subprocess.run(["pbcopy"], input=secret.encode(), check=True)


def clear_if_unchanged(secret: str) -> bool:
    """Empty the clipboard, but only if it still holds this secret."""
    current = subprocess.run(["pbpaste"], capture_output=True, check=False).stdout.decode()
    if current != secret:
        return False
    subprocess.run(["pbcopy"], input=b"", check=True)
    return True


def copy_briefly(secret: str, seconds: float = CLIPBOARD_SECONDS) -> threading.Timer:
    """Copy a secret and clear it again after ``seconds``, unless something replaced it."""
    copy(secret)
    timer = threading.Timer(seconds, clear_if_unchanged, args=(secret,))
    timer.daemon = True
    timer.start()
    return timer
