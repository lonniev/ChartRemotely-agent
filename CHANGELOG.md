# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

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
