"""``chartremotely setup``: from a fresh Mac to a paired, voice-driven display.

It first shows what is installing - version, where it came from (PyPI and
its release, or a local checkout), the Python it runs on - and the steps
ahead, and asks before changing anything. Each step checks first and skips
what is already done, so running setup again is always safe:

1. **Identity.** Either the patron's existing npub, proven by the Nostr DM
   challenge (setup never sees their nsec), or a key made here for them.
   A made key is kept for the human - their Keychain, then Safari's saved
   passwords - and used once, in memory, to sign the pairing. It is never
   written to this agent's config. Then **pairing**, without a code to copy: setup adopts this machine's code itself.
   and **voice sign-in**: the ``dpop_token`` from the owner's DM proof, kept in
   the login Keychain (their npub goes in the config), so the listener can
   call the operator's priced tools as that patron.
2. **Tailscale**: the Mac's tailnet address, with ``/chart`` forwarded to the agent.
3. **Services**: the listener and the relay, under launchd.
4. **Permissions**: Accessibility and Screen Recording, asked for by the
   services' own Python, since that is the process macOS grants them to.
5. **Hearing**: the Whisper speech model, fetched once (about 1.6 GB), and
   the owner's display names, so a sentence can say where.
6. **The Shortcut**: this Mac's "ChartRemotely" - talk, or type when it
   asks - opened for import. A "ChartRemotely Ask" left by an older setup is
   removed from the library (by "Shortcuts Events"; named for deleting by
   hand if that fails).
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

from . import config, mcpclient, relay
from .terminal import Terminal, wants_color

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
    say("Reply to it from your Nostr client only if the codes match. In the reply you")
    say("may set cache_duration (30 days, or unlimited) so voice keeps working that")
    say("long; left alone, the sign-in lasts 2 hours.")
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
    say("Your Nostr identity owns this display:")
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


# -- what is being installed -------------------------------------------------

PLAN = [
    ("Identity", "prove who owns this display, by Nostr DM or a key made here"),
    ("Tailscale", "reach this Mac's listener at its tailnet address, /chart"),
    ("Services", "run the listener and the relay under launchd, from login"),
    ("Permissions", "allow Accessibility and Screen Recording"),
    ("Hearing", "fetch the Whisper speech model (about 1.6 GB, once)"),
    ("Shortcut", "make “ChartRemotely” and open it for you to add"),
]


def provenance() -> list[tuple[str, str]]:
    """What is running setup, and where it came from: version, source, release, runtime."""
    from importlib import metadata

    dist = metadata.distribution("chartremotely")
    version = dist.version
    urls = dict(u.split(", ", 1) for u in dist.metadata.get_all("Project-URL") or [] if ", " in u)
    direct = json.loads(dist.read_text("direct_url.json") or "null")
    running = Path(__file__).resolve().parent
    rows = [("Version", version)]
    if "site-packages" not in running.parts:
        # Imported straight from a source tree: its metadata may be a stale
        # egg-info beside it, so claim nothing about PyPI.
        rows = [("Version", f"{version} (source; releases stamp their own)"),
                ("From", f"source checkout {running.parent}")]
    elif direct is None:
        rows.append(("From", f"PyPI  https://pypi.org/project/{dist.metadata['Name']}/{version}/"))
        if urls.get("Repository"):
            rows.append(("Release", f"{urls['Repository']}/releases/tag/v{version}"))
    else:
        where = direct.get("url", "").removeprefix("file://")
        commit = (direct.get("vcs_info") or {}).get("commit_id")
        editable = (direct.get("dir_info") or {}).get("editable")
        rows.append(("From", f"{where}{'@' + commit[:12] if commit else ''}{' (editable)' if editable else ''}"))
    rows.append(("Python", f"{sys.executable} ({sys.version.split()[0]})"))
    home = str(Path.home())
    return [(label, value.replace(home, "~")) for label, value in rows]


# -- the whole run ------------------------------------------------------------

def run(ask: Ask = input, say: Say = print, operator_url: str = OPERATOR_URL) -> int:
    out = Terminal(write=say, read=ask, color=say is print and wants_color())
    from importlib import metadata

    out.title("ChartRemotely setup", metadata.distribution("chartremotely").metadata["Summary"])
    out.facts(provenance())
    out.plan("Setup will, skipping anything already done:", PLAN)
    out.write("")
    if not out.confirm("Continue?"):
        out.say("Nothing was changed.")
        return 0
    total = len(PLAN)

    cfg = config.load()
    base = (cfg.get("operator_url") or operator_url).rstrip("/")
    token = config.ensure_token()

    # 1. Identity and pairing, unless this Mac is already paired.
    out.step(1, total, "Identity")
    client = mcpclient.Client(base)
    if cfg.get("agent_id") and cfg.get("agent_secret"):
        out.ok(f"This Mac is already paired ({cfg['agent_id']}).")
        npub = cfg.get("owner_npub") or out.ask("Your npub (whose display this is): ").strip()
        if not npub.startswith("npub1"):
            raise SetupError("that is not an npub")
        if has_sign_in(npub):
            config.update(owner_npub=npub)
            out.ok("Voice is already signed in.")
        else:
            voice_sign_in(client, npub, out.ask, out.say)
    else:
        npub, proof, by_dm = identity(client, out.ask, out.say)
        label = out.ask("Name this display (e.g. Desk, Office wall): ").strip() or "display"
        pair(client, base, npub, proof, label)
        out.ok(f"Paired as “{label}”.")
        if by_dm:
            keep_sign_in(npub, proof)
            out.ok("Voice is signed in with the same DM.")
        else:
            voice_sign_in(client, npub, out.ask, out.say)
        del proof

    # 2. Tailscale.
    from . import tailnet

    out.step(2, total, "Tailscale")
    url = tailnet.chart_url(tailnet.status())
    tailnet.serve(int(cfg.get("port") or 8899))
    out.ok(f"The Shortcut reaches this Mac at {url}")

    # 3. Services.
    from . import services

    out.step(3, total, "Services")
    for command in ("serve", "relay"):
        services.install(command)
    out.ok("The listener and the relay are running, and start with this Mac.")

    # 4. Permissions, as the services' own Python sees them.
    out.step(4, total, "Permissions")
    probe = Path(tempfile.gettempdir()) / "chartremotely-permissions.json"
    granted = services.probe_permissions(request=True, out=probe)
    while not (granted.get("accessibility") and granted.get("screen_recording")):
        python = granted.get("python", "the Python that runs ChartRemotely")
        missing = [name for name, key in (("Accessibility", "accessibility"),
                                          ("Screen Recording", "screen_recording")) if not granted.get(key)]
        out.warn(f"macOS needs you to allow {' and '.join(missing)} for:")
        out.say(python)
        pane = "Privacy_Accessibility" if not granted.get("accessibility") else "Privacy_ScreenCapture"
        subprocess.run(["open", f"x-apple.systempreferences:com.apple.preference.security?{pane}"], check=False)
        out.ask("Turn it on in System Settings, then press Return… ")
        granted = services.probe_permissions(request=False, out=probe)
    out.ok("Accessibility and Screen Recording are allowed.")

    # 5. Hearing: the speech model, and the display names a sentence may say.
    from . import displays, hearing

    out.step(5, total, "Hearing")
    try:
        if hearing.fetch_model(out.say):
            out.ok("The speech model is on this Mac.")
    except Exception as exc:  # noqa: BLE001 - the typing box works without it
        out.warn(f"The speech model could not be fetched ({type(exc).__name__}); run setup again later.")
    if displays.refresh() is not None:
        out.ok(f"Displays you can name: {', '.join(displays.load()) or 'none yet'}.")

    # 6. The Shortcut.
    from . import shortcut

    out.step(6, total, "Shortcut")
    subprocess.run(["open", str(shortcut.build(url, token))], check=False)
    out.ok("“ChartRemotely” is open: add it (or Replace). iCloud brings it to your iPhone, iPad and Watch.")
    removed, left = shortcut.remove_retired()
    if removed:
        out.ok(f"Removed {', '.join(f'“{n}”' for n in removed)}; “ChartRemotely” does it all now.")
    if left:
        out.warn(f"Delete {', '.join(f'“{n}”' for n in left)} in the Shortcuts app; “ChartRemotely” does it all now.")

    out.write("")
    out.write(out.bold("Ready."))
    out.say("Say “Hey Siri, ChartRemotely”, then one sentence: “Palantir, half, on mac mini”.")
    out.say("No microphone, or it didn't hear you? It shows a box: type the same sentence.")
    out.facts([("Your npub", npub), ("Your screens", SITE)])
    out.write("")
    return 0
