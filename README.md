# ChartRemotely — agent

Remote control of desktop charting applications on macOS. Say a company name
into any Apple device and the chart on a wall monitor changes — including a
monitor in another building.

This repository is the **agent**: the piece that runs on the Mac driving the
display. It is deliberately small and readable, because installing it means
granting Accessibility permission to software that types into a trading
application. You should be able to audit that decision in a few minutes.

## What it does, precisely

thinkorswim has no API, no URL scheme, and no automation surface. The agent
drives it the way a screen reader would — through the macOS Accessibility
API and synthetic input events. It is the same category of software as
AutoHotkey or Keyboard Maestro, and it never touches a broker API.

## What it cannot do

The command vocabulary is closed, and it is one short file: [`vocab.py`](chartremotely/vocab.py).

| Command | Effect |
|---|---|
| `show <name or ticker>` | Change the chart's symbol |
| `scale <mnemonic>` | Change the chart's aggregation |
| `read` | Report POC / value area |

There is no command that opens an order ticket, submits a trade, moves money,
or reads account balances. Adding one would mean editing that file, in public,
in this repository.

## Why the resolver exists

Dictation matches speech against the whole English language, so a security
name arrives mangled: *Palantir* becomes "Volunteer", *Qualcomm* becomes
"Callalon", *Coin* becomes "Kuehn". The resolver repairs what it can against
the SEC company registry — exact ticker, exact name, prefix, word-subset,
name-coverage, consonant skeleton, then fuzzy — and **refuses** anything that
does not convince, rather than charting a plausible wrong answer.

Every case in [`tests/test_resolve.py`](tests/test_resolve.py) is a real
transcript or a real failure. The suite asserts what must resolve *and* what
must be refused; loosening a threshold to fix a miss usually breaks a refusal.

## Install

```bash
pip install "chartremotely[macos] @ git+https://github.com/lonniev/ChartRemotely-agent"
chartremotely doctor
```

`doctor` reports what is missing: Accessibility permission, a running
thinkorswim, a resolvable symbol field, a listening agent.

**One step cannot be automated.** macOS requires a human to grant
Accessibility permission in System Settings → Privacy & Security →
Accessibility. That is the point of the protection, and no installer can or
should bypass it.

## Status

Early. The thinkorswim adapter works; the interfaces are still moving.

## License

Apache-2.0
