# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

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
