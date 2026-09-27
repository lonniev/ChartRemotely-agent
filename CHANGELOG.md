# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Changed
- Replies are spoken at rate 0.55: 0.6 was a touch too fast.

## [0.3.0] - 2026-09-27

Voice, heard on your own Mac. Everything from 0.2.12 to 0.2.17 in one minor release: one-sentence requests heard by Whisper, one Shortcut that falls back to typing, and a setup that says what it installs.

### Why Whisper
Why Whisper, not Siri: Siri's recognizer can't be taught a vocabulary, so it kept mishearing trader talk ("half" became "have"). ChartRemotely now hears you with Whisper on your own Mac, primed with company names, chart scales and your display names. Private, and about a second.

## [0.2.17] - 2026-09-27

### Changed
- `chartremotely setup` opens by saying what is installing: description, version, where it came from (PyPI and its GitHub release, or a source checkout), and the Python it runs on. It then lists its six steps and asks before changing anything.
- Setup's output is tidier: numbered step headings, ✓ and ! marks, aligned facts, and colour only on a terminal (`NO_COLOR` is honoured). The permission check's launchctl chatter and the speech model's cached-download progress bars no longer leak through.

## [0.2.16] - 2026-09-27

### Changed
- The Shortcut speaks its replies brisker (Speak Text rate 0.6; Siri's default is 0.5).

## [0.2.15] - 2026-09-27

### Changed
- Speech gets three tries at a request, as Siri gives: the third spoken miss asks its question in the text box, with what was already heard kept.

## [0.2.14] - 2026-09-27

### Changed
- One Shortcut: talk, or type when it asks. "ChartRemotely" records a sentence as before; when the Mac finds nothing usable in it - an empty or header-only file (a Mac mini, which has no microphone, sends 28 bytes), audio `afconvert` cannot read, under 0.3 s or quieter than a room, only what Whisper makes of silence ("Thank you.", "you"), a crash in hearing, or a Mac that cannot hear yet - the listener answers `TYPE:` and a prompt instead of a sentence to speak. The Shortcut shows that prompt in one single-line text box and posts the typed sentence (`{"said": ...}`) to the same `/chart` path, where it is understood by the same `understand()` and makes the same priced `chart_show_chart` call. A typed request that is missing something comes back as another `TYPE:` question, never "I'm listening.". Too long a recording is still spoken as an ERR.
- On a Mac, the Shortcut goes straight to the text box (Get Device Details: the model contains "Mac"). Record Audio on a Mac mini with no microphone neither ends nor fails: it sits at 00:01 until stopped by hand.

### Removed
- The "ChartRemotely Ask" Shortcut (three questions), its template, setup step and tests. `chartremotely setup` deletes any "ChartRemotely Ask" (or "ChartRemotely Ask 2", ...) from the Shortcuts library through "Shortcuts Events" - the `shortcuts` command cannot delete - and names any it could not remove for deleting by hand.

## [0.2.12] - 2026-09-27

### Added
- One-sentence voice requests, heard by Whisper on the Mac. The "ChartRemotely" Shortcut now records a sentence ("Palantir, half, on mac mini") and posts it to the listener (`POST /chart?hear=1`, the recording as the body, at most 2 MB / 15 s). The Mac decodes it with macOS's `afconvert` (no ffmpeg; temporary files in a private folder, deleted before the reply), transcribes it with `mlx-whisper` (`whisper-large-v3-turbo`, on the GPU) primed with the scale words, recent companies and display names, and understands it with `understand()`. A complete request makes the same priced `chart_show_chart` call as before; a missing company or scale, or two companies too close to call, is asked for ("... I'm listening.") and the Shortcut records again, up to three times, keeping what was already understood for 45 seconds. Only the text heard is logged (`heard=`), never the audio.
- New dependency: `mlx-whisper` in the `macos` extra (Apple silicon only). `chartremotely setup` fetches the speech model (about 1.6 GB, once); the listener warms it in the background at start, so a sentence takes about a second.
- The owner's display names, from the operator's free `chart_agent_status` (asked as the owner, at most every four hours and after setup), cached in `~/.local/share/chartremotely/displays.json` - labels only.
- Setup installs a second Shortcut, "ChartRemotely Ask": the three questions (Which company? What scale? Where?), for typing or when a recording will not do.
- `understand.understand(text, *, recent, displays)`: one utterance ("Palantir half on mac mini", "shop thirty minutes", "apple as is on desk") becomes an `Understanding` - ticker, company, scale (a mnemonic or "as is"), where (as said; the operator re-matches it), the ticker options when the company is too close to call, what was heard, and what is still missing ("company", "scale"). Pure and deterministic, no LLM. The entry point for whole-utterance transcriptions (stage 2).
- A personal prior: the symbols this Mac charted successfully, most recent first (at most 50, tickers only), in `~/.config/chartremotely/recent.json`. A near-tie between companies goes to the one you chart.

### Changed
- "What scale?" understands bar sizes for every preset ("thirty minutes" and "half an hour" are half, "an hour" hourly, "four hours" swing, "a day" daily, "a week" weekly) and one mis-heard word that sounds like exactly one mnemonic ("have", "halve", "haff", "alf" are half). A word near two mnemonics is still refused.
- "Which company?" asks instead of guessing when two different companies are too close to call: "ERR Did you mean PS (Pershing Square) or MSGS (Madison Square Garden)?". Share classes of one company count once, and a far less prominent namesake is no contender ("robinhood" is HOOD). Words run together are tried too ("shop if y" is Shopify, "pal and tear" Palantir); "google" and "facebook" resolve.
- The request log shows what was heard for the free `resolve` and `scale` lookups (`heard=`, 60 characters), so a mis-heard word can be seen. Every other verb still logs no arguments.

## [0.2.11] - 2026-09-26

### Fixed
- thinkorswim's symbol autocomplete list and time-frame menu no longer stay open over the chart, or in its picture. After a symbol is shown, a scale is set or read, and before every capture, `popups.dismiss()` closes the menu by pressing its toggle again, closes the list with Escape once the symbol field has focus (Escape only hides the list; typed text stays), and then moves focus to the chart's title strip - but only once that title names what the field holds, since the field commits its text when it loses focus. The Escape previously sent after reading the scale went to nothing with focus, which is why the menu stayed up.

## [0.2.10] - 2026-09-25

### Changed
- Before any command drives the chart (set, read, snapshot - by voice or relayed), thinkorswim is brought in front first: unhidden, activated, its chart window un-minimised and raised, and - once it is actually on screen - the ordinary apps covering it are hidden. Only then is it navigated. A chart that was hidden or minimised is no longer driven blind, and a covered one is uncovered before, not after, the change. What it took is logged ("unhid; raised; hid Safari"), never spoken. When thinkorswim is not running the reply is "ERR thinkorswim is not open on this Mac".
- thinkorswim and the apps covering it are found through the window server's live list, not NSWorkspace's, which a listener or relay (no run loop) never refreshes - so an app opened after they started is seen.

## [0.2.9] - 2026-09-25

### Changed
- Voice commands are ordinary patron tool calls. The listener calls the operator's existing priced `chart_show_chart` (and `chart_read_chart` for "read") with the display owner's `npub` and `dpop_token`, and `display` as dictated - blank "Where?" is this Mac's agent_id. The operator relays the change and this (or the named) Mac's relay changes the chart and takes its picture; the listener never drives the chart. Only the Shortcut's free `resolve` and `scale` lookups are answered locally. "snapshot" is not bought by voice (a picture cannot be spoken).
- Siri answers within about 3 seconds: an early refusal (sign-in expired, balance too low, unknown or silent display) is spoken; otherwise the hand-off, "Chart PLTR at half scale sent to Mac-mini. Good luck." ("this Mac" when "Where?" was blank; no scale for "as is"). The call finishes in the background and its outcome is logged - tool, "Where?" and any refusal, never the token.
- An expired sign-in is spoken ("Your ChartRemotely sign-in expired. Answer the DM on your phone to renew.") and renewed in the background: one `chart_request_npub_proof` DM at a time, then `chart_receive_npub_proof` on a slowing schedule for about half an hour; the new token goes back into the Keychain.
- `chartremotely setup` keeps the DM proof's `dpop_token` as the voice sign-in, in the login Keychain (generic password "ChartRemotely voice sign-in", one per npub), and the owner's npub in the config as `owner_npub`. Its DM prompt suggests replying with a longer `cache_duration` (e.g. 30 days, or unlimited; default 2 hours). A Mac paired with a saved or made key, or already paired, is offered the DM sign-in too. The nsec is never asked for or stored.
- The voice Shortcut no longer says "On it, requesting your chart now…" before sending; it speaks only the listener's reply. Re-run `chartremotely setup` for the sign-in and the new Shortcut.

### Removed
- `forward.py`: the listener no longer uses the operator's `/agent/forward`, and no longer runs a chart change on this Mac itself.

## [0.2.8] - 2026-09-25

### Added
- The picture pushed after a chart change now carries the scale the reply stated ("half", "30 minutes") beside its symbol, so the operator can say which time frame a kept picture shows. A change that states no scale keeps the previous one; the timeframe popup is never opened just to learn it. Needs ChartRemotely-mcp with picture text summaries; an older operator ignores the field.

## [0.2.7] - 2026-09-24

### Changed
- Right after "Where?", the voice Shortcut says "On it, requesting your chart now. Look at your screen or visit the website for the screen capture." without waiting to finish, so the request goes out while it speaks and the pause no longer sounds like a failure. Rebuild the Shortcut (`chartremotely setup`) to get it.

## [0.2.6] - 2026-09-24

### Fixed
- A command sent to another display ("Where?") no longer fails with "at most 64 and 200 printable characters": the Shortcut splices this Mac's own replies, which end in a newline, into the command, so the Mac now collapses whitespace before forwarding it.

### Changed
- Every question in the voice Shortcut takes a single line, so Return answers it instead of starting a new line. Run `chartremotely setup` (or rebuild the Shortcut) to get it.
- After an automatic release, the factory App opens a CHANGELOG-only PR, with auto-merge on, that files the released `[Unreleased]` lines under a dated `## [x.y.z]` section; the release notes are that same section. 0.2.2 to 0.2.5 are filed here from their tags.

## [0.2.5] - 2026-09-24

### Changed
- "Where?" names are matched only by the operator, which now matches loosely ("mini mac", "mini" and "mack meeny" find "Mac mini"; needs ChartRemotely-mcp with loose display names). This Mac runs a command without asking only when "Where?" is blank or exactly its agent_id; any name, its own included, goes to the operator, which answers `self` when the name is this Mac's. The local name check and its copy of the operator's `display_key` are gone, as is `display_label` in the config - no pairing ever wrote it on a Mac set up before it, so every name was being forwarded anyway.

### Added
- The listener and the relay log one line per command to stderr (launchd's `~/Library/Logs/chartremotely-serve.log` / `-relay.log`): time, verb (first word only), "Where?" as said (64 chars), and the reply when it is an ERR (200 chars). A spoken ERR can now be diagnosed. Never the X-Token, a secret or a picture; the stock access log stays off, as its request line can carry the token.

### Fixed
- Re-running `chartremotely setup` on a Mac whose services are running no longer stops with "Bootstrap failed: 5: Input/output error" and the listener left down: it waits for launchd to let go of the old service, retries while launchd settles, and otherwise stops with launchd's own reason.

## [0.2.4] - 2026-09-24

### Added
- The voice Shortcut asks a third question, "Where?", after the scale, and sends the dictated answer verbatim as a separate JSON field `where` beside `cmd` (the vocab grammar is unchanged). Empty, this Mac's own display name or its agent_id runs here as before; any other name is forwarded through the operator's `/agent/forward` to that display of the same owner, and its reply is spoken. An unknown name answers `ERR No display named "<where>". Yours: A, B.` A forwarded command pushes no picture from this Mac; the target pushes its own. Names match ignoring case, spaces, hyphens, underscores and dots, exactly as the operator matches them. Needs ChartRemotely-mcp with `/agent/forward`; re-run `chartremotely setup` to get the new Shortcut.
- `setup` remembers this display's name (`display_label`), so "Where? <this Mac>" never leaves the Mac. A Mac paired before this learns it the first time the operator answers that a name is its own.

## [0.2.3] - 2026-09-24

### Changed
- Requires Python 3.12, which the Tollbooth SDK it depends on already requires; `uv` could not resolve the project for 3.11.

## [0.2.2] - 2026-09-24

### Changed
- A merge to `main` that changes the package publishes the next patch release to PyPI by itself, after ruff and the tests pass, and tags it with a GitHub Release. Raising `version` in `pyproject.toml` asks for a minor or major release instead.
- The pushed picture names the symbol the last chart-changing command of the burst put on screen, carried as data from the command (`vocab.answer` → `Answer.symbol`) to the push; the symbol field is read only when no command named one (it can be stale), so the operator can keep one picture per symbol. Left off when the symbol cannot be read or is not symbol-shaped. Needs ChartRemotely-mcp with per-symbol pictures; an older operator ignores the field.

## [0.2.1] - 2026-09-24

### Changed
- The picture of a changed chart is taken only after the reply ("… Good luck.") has been sent, once the chart has been quiet for 1.5 s, and one picture covers a burst of changes. Every command that drives thinkorswim, and the picture, now holds one lock shared by the Siri listener and the relay, so they never overlap.

## [0.2.0] - 2026-09-24

### Added
- `chartremotely setup`: from a fresh Mac to a paired, voice-driven display.
  Proves the patron's identity (an existing npub by Nostr DM, a key saved on
  this Mac, or a new key), pairs without a code to copy, forwards `/chart`
  on the tailnet, installs the listener and relay as launchd agents, has the
  services' own Python ask for Accessibility and Screen Recording, and makes
  this Mac's voice Shortcut from the template. Each step skips itself when
  already done.
- A key made by setup is the patron's: it goes into the login Keychain and,
  through Safari's Save password prompt, into iCloud Passwords. It is used
  once, in memory, to sign the pairing, and never written to the agent's
  config, a log, a URL or a command line.
- `chartremotely permissions [--request]`: what this process has been granted.
- The `setup` extra, which uses the tollbooth-dpyc SDK for keys and proofs.
- Published to PyPI as `chartremotely` from `v*` tags.

### Changed
- `pair` and `setup` share one pairing path (`relay.open_code` + `relay.collect`).
