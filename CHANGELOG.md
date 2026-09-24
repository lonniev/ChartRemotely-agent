# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- The voice Shortcut asks a third question, "Where?", after the scale, and sends the dictated answer verbatim as a separate JSON field `where` beside `cmd` (the vocab grammar is unchanged). Empty, this Mac's own display name or its agent_id runs here as before; any other name is forwarded through the operator's `/agent/forward` to that display of the same owner, and its reply is spoken. An unknown name answers `ERR No display named "<where>". Yours: A, B.` A forwarded command pushes no picture from this Mac; the target pushes its own. Names match ignoring case, spaces, hyphens, underscores and dots, exactly as the operator matches them. Needs ChartRemotely-mcp with `/agent/forward`; re-run `chartremotely setup` to get the new Shortcut.
- `setup` remembers this display's name (`display_label`), so "Where? <this Mac>" never leaves the Mac. A Mac paired before this learns it the first time the operator answers that a name is its own.

### Changed
- Requires Python 3.12, which the Tollbooth SDK it depends on already requires; `uv` could not resolve the project for 3.11.

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
