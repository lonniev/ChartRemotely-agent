"""Keep a patron's Nostr key for the patron, never for this agent.

A key made by ``setup`` belongs to the human. It goes into their login
Keychain as an internet password for the ChartRemotely site, and it is
handed to Safari once, through the clipboard, so Safari can save it to
iCloud Passwords where their other devices and apps find it. A command-line
tool cannot write a synchronizable Keychain item itself (that needs an
entitled app: ``errSecMissingEntitlement``), which is why Safari does the
syncing.

Nothing here writes the key to the agent's config, a log, a URL or a
command line. It travels as ``kSecValueData`` or on a pipe, and nowhere else.
"""

from __future__ import annotations

import subprocess
import threading

SERVER = "chartremotely.tollbooth-dpyc.com"
LABEL = "ChartRemotely — Nostr key"
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


def save(npub: str, nsec: str) -> None:
    """Store (or replace) the patron's key in their login Keychain."""
    S = _security()
    secret = nsec.encode()
    status = S.SecItemAdd({**item_query(npub), S.kSecAttrLabel: LABEL, S.kSecValueData: secret}, None)[0]
    if status == ERR_DUPLICATE:
        status = S.SecItemUpdate(item_query(npub), {S.kSecValueData: secret})
    if status != 0:
        raise KeystoreError(f"the Keychain refused to save the key (status {status})")


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
