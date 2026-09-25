"""``chartremotely setup``: from a fresh Mac to a paired, voice-driven display.

Each step checks first and skips what is already done, so running setup
again is always safe:

1. **Identity.** Either the patron's existing npub, proven by the Nostr DM
   challenge (setup never sees their nsec), or a key made here for them.
   A made key is kept for the human - their Keychain, then Safari's saved
   passwords - and used once, in memory, to sign the pairing. It is never
   written to this agent's config.
2. **Pairing**, without a code to copy: setup adopts this machine's code itself.
   **Voice sign-in**: the ``dpop_token`` from the owner's DM proof, kept in
   the login Keychain (their npub goes in the config), so the listener can
   call the operator's priced tools as that patron.
3. **Tailscale**: the Mac's tailnet address, with ``/chart`` forwarded to the agent.
4. **Services**: the listener and the relay, under launchd.
5. **Permissions**: Accessibility and Screen Recording, asked for by the
   services' own Python, since that is the process macOS grants them to.
6. **The voice Shortcut**: this Mac's copy, opened for import.
"""

from __future__ import annotations

import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path

from . import config, mcpclient, relay

OPERATOR_URL = "https://chartremotely-mcp.fastmcp.app"
SITE = "https://chartremotely.tollbooth-dpyc.com"
SAVE_KEY_PAGE = f"{SITE}/#/save-key"

Ask = Callable[[str], str]
Say = Callable[[str], None]


class SetupError(RuntimeError):
    """A step that cannot continue, with the reason a person can act on."""


# -- identity -----------------------------------------------------------------

def prove_by_dm(client: mcpclient.Client, npub: str, ask: Ask, say: Say) -> str:
    """Prove an existing npub by the Secure Courier DM. Returns the dpop_token.

    The human answers from their own Nostr client, so no key passes through here.
    """
    sent = client.call("chart_request_npub_proof", {
        "patron_npub": npub, "verify_at": SITE,
        "reason": "You asked to pair a Mac with ChartRemotely."})
    phrase = sent.get("dpop_token")
    if not phrase:
        raise SetupError(sent.get("error") or "the operator did not send a proof request")
    say(f"A Nostr DM is on its way to {npub[:12]}…")
    say(f"Its confirmation code is: {phrase}")
    say("Reply to the DM from your Nostr client only if the codes match.")
    say("In your reply you may set cache_duration - e.g. 30 days, or unlimited - so voice")
    say("keeps working that long; left alone, the sign-in lasts 2 hours.")
    ask("Press Return once you have replied… ")
    got = client.call("chart_receive_npub_proof", {"patron_npub": npub, "dpop_token": phrase})
    if got.get("error"):
        raise SetupError(got["error"])
    return got.get("dpop_token") or phrase


def new_key() -> tuple[str, str]:
    """A fresh Nostr keypair, made by the SDK's own key code. Returns (npub, nsec)."""
    from pynostr.key import PrivateKey  # the tollbooth-dpyc SDK's key library

    key = PrivateKey()
    return key.public_key.bech32(), key.bech32()


def sign_once(nsec: str, tool: str) -> str:
    """One kind-27235 proof for one tool call, signed by the SDK."""
    from tollbooth.identity_proof import create_proof

    return create_proof(nsec, tool)


def keep_for_human(npub: str, nsec: str, ask: Ask, say: Say) -> None:
    """Store a made key in the Keychain and let Safari save it to iCloud Passwords."""
    from . import keystore

    keystore.save(npub, nsec)
    say("Your key is saved in this Mac's Keychain, under “ChartRemotely — Nostr key”.")
    say("Next, Safari saves it to your iCloud Passwords so your other devices have it.")
    timer = keystore.copy_briefly(nsec)
    try:
        subprocess.run(["open", f"{SAVE_KEY_PAGE}?npub={npub}"], check=False)
        say("Paste the key (⌘V) into the page, press Save, and accept Safari's offer to save it.")
        ask("Press Return when Safari has saved it… ")
    finally:
        timer.cancel()
        keystore.clear_if_unchanged(nsec)


def identity(client: mcpclient.Client, ask: Ask, say: Say) -> tuple[str, str, bool]:
    """Who owns this display, proven.

    Returns (npub, proof for chart_pair_agent, whether that proof is a DM
    sign-in the listener can keep using).
    """
    say("Your Nostr identity owns this display.")
    say("  1  I have an npub (I'll answer a Nostr DM to prove it)")
    say("  2  Use a key saved on this Mac")
    say("  3  Make me a new key")
    choice = ask("Choose 1, 2 or 3: ").strip()
    if choice == "1":
        npub = ask("Your npub: ").strip()
        if not npub.startswith("npub1"):
            raise SetupError("that is not an npub")
        return npub, prove_by_dm(client, npub, ask, say), True
    if choice == "2":
        from . import keystore

        saved = keystore.saved_npubs()
        if not saved:
            raise SetupError("no ChartRemotely key is saved on this Mac yet; choose 1 or 3")
        for i, npub in enumerate(saved, 1):
            say(f"  {i}  {npub}")
        picked = saved[int(ask("Which key? ").strip() or "1") - 1]
        nsec = keystore.load(picked)  # macOS asks the human first
        try:
            return picked, sign_once(nsec, "chart_pair_agent"), False
        finally:
            del nsec
    if choice == "3":
        npub, nsec = new_key()
        try:
            say(f"Your new npub is {npub}")
            keep_for_human(npub, nsec, ask, say)
            return npub, sign_once(nsec, "chart_pair_agent"), False
        finally:
            del nsec
    raise SetupError("choose 1, 2 or 3")


# -- the voice sign-in --------------------------------------------------------

def keep_sign_in(npub: str, token: str) -> None:
    """The owner's npub into the config; their sign-in into the Keychain, only."""
    from . import keystore

    keystore.save_token(npub, token)
    config.update(owner_npub=npub)


def has_sign_in(npub: str) -> bool:
    from . import keystore

    try:
        return bool(keystore.load_token(npub))
    except keystore.KeystoreError:
        return False


def voice_sign_in(client: mcpclient.Client, npub: str, ask: Ask, say: Say) -> None:
    """Voice commands are priced tool calls made as the owner: prove the npub by DM for them."""
    config.update(owner_npub=npub)
    say(f"Voice commands are paid for by {npub[:12]}…, signed in by a Nostr DM.")
    if ask("Sign in for voice now? [Y/n] ").strip().lower().startswith("n"):
        say("Then your first voice command sends the DM.")
        return
    keep_sign_in(npub, prove_by_dm(client, npub, ask, say))
    say("Voice is signed in.")


# -- pairing ------------------------------------------------------------------

def pair(client: mcpclient.Client, base: str, npub: str, proof: str, label: str) -> dict:
    """Adopt this machine's pairing code with the patron's proof, then collect."""
    code, expires_in = relay.open_code(base)
    answer = client.call("chart_pair_agent", {"code": code, "label": label, "npub": npub, "dpop_token": proof})
    if not answer.get("ok"):
        raise SetupError(answer.get("error") or "the operator refused the pairing")
    return relay.collect(base, code, expires_in)


# -- the whole run ------------------------------------------------------------

def run(ask: Ask = input, say: Say = print, operator_url: str = OPERATOR_URL) -> int:
    cfg = config.load()
    base = (cfg.get("operator_url") or operator_url).rstrip("/")
    token = config.ensure_token()

    # 1-2. Identity and pairing, unless this Mac is already paired.
    client = mcpclient.Client(base)
    if cfg.get("agent_id") and cfg.get("agent_secret"):
        say(f"This Mac is already paired ({cfg['agent_id']}).")
        npub = cfg.get("owner_npub") or ask("Your npub (whose display this is): ").strip()
        if not npub.startswith("npub1"):
            raise SetupError("that is not an npub")
        if has_sign_in(npub):
            config.update(owner_npub=npub)
            say("Voice is already signed in.")
        else:
            voice_sign_in(client, npub, ask, say)
    else:
        npub, proof, by_dm = identity(client, ask, say)
        label = ask("Name this display (e.g. Desk, Office wall): ").strip() or "display"
        pair(client, base, npub, proof, label)
        say(f"Paired as “{label}”.")
        if by_dm:
            keep_sign_in(npub, proof)
            say("Voice is signed in with the same DM.")
        else:
            voice_sign_in(client, npub, ask, say)
        del proof

    # 3. Tailscale.
    from . import tailnet

    url = tailnet.chart_url(tailnet.status())
    tailnet.serve(int(cfg.get("port") or 8899))
    say(f"Your Shortcut will reach this Mac at {url}")

    # 4. Services.
    from . import services

    for command in ("serve", "relay"):
        services.install(command)
    say("The listener and the relay are running, and start with this Mac.")

    # 5. Permissions, as the services' own Python sees them.
    probe = Path(tempfile.gettempdir()) / "chartremotely-permissions.json"
    granted = services.probe_permissions(request=True, out=probe)
    while not (granted.get("accessibility") and granted.get("screen_recording")):
        python = granted.get("python", "the Python that runs ChartRemotely")
        missing = [name for name, key in (("Accessibility", "accessibility"),
                                          ("Screen Recording", "screen_recording")) if not granted.get(key)]
        say(f"macOS needs you to allow {' and '.join(missing)} for: {python}")
        pane = "Privacy_Accessibility" if not granted.get("accessibility") else "Privacy_ScreenCapture"
        subprocess.run(["open", f"x-apple.systempreferences:com.apple.preference.security?{pane}"], check=False)
        ask("Turn it on in System Settings, then press Return… ")
        granted = services.probe_permissions(request=False, out=probe)
    say("Accessibility and Screen Recording are allowed.")

    # 6. The voice Shortcut.
    from . import shortcut

    made = shortcut.build(url, token)
    subprocess.run(["open", str(made)], check=False)
    say("Add the ChartRemotely Shortcut when it opens; iCloud brings it to your iPhone, iPad and Watch.")

    say("")
    say("Done. Say “Hey Siri, ChartRemotely” from any of your devices.")
    if npub:
        say(f"Your npub: {npub}")
    say(f"Sign in at {SITE} to see your screens.")
    return 0
