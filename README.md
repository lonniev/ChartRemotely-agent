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

## Commands

```
chartremotely show palantir --scale scalp   put a security on the chart
chartremotely show "john deere"             spoken names resolve to tickers
chartremotely scale half                    change the aggregation
chartremotely read                          report symbol and scale
chartremotely scales                        list the time frames on offer
chartremotely studies --row-height 2.5      rebuild the study set
chartremotely learn                         rediscover the chart's controls
chartremotely serve                         run the local listener
chartremotely pair                          adopt this display to an operator
chartremotely relay                         hold a connection open for the operator
chartremotely doctor                        check everything the agent needs
```

`serve` and `relay` are two different transports and most setups want both.
`serve` listens on the local network, which is what an Apple Shortcut on the
same tailnet talks to. `relay` dials *out* to the operator and holds the
connection open, which is the only way a command from the other side of the
world reaches this machine - no inbound port, no router to open, no
certificate to keep alive. Pairing alone does not start it: a display that is
paired but has no `relay` running reports `connected: false` and silently
ignores everything sent to it.

## Running it as a service

Both transports are long-lived, so run them under `launchd` rather than a
terminal. Two services rather than one, so a relay that loses the network
cannot take the local listener down with it:

```bash
for cmd in serve relay; do
  cat > ~/Library/LaunchAgents/com.chartremotely.$cmd.plist <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.chartremotely.$cmd</string>
  <key>ProgramArguments</key>
  <array>
    <string>$(command -v chartremotely)</string>
    <string>$cmd</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>10</integer>
  <key>StandardOutPath</key><string>/tmp/chartremotely-$cmd.log</string>
  <key>StandardErrorPath</key><string>/tmp/chartremotely-$cmd.err</string>
</dict>
</plist>
PLIST
  launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.chartremotely.$cmd.plist
done
```

Pair first - `relay` needs the credentials `pair` stores before it has
anything to dial with.

Time frames are spoken as mnemonics chosen for phonetic distance, because
digits are the worst thing to say to a recogniser - "fifteen" and "fifty"
collide, and so do "one" and "won":

| | | | | |
|---|---|---|---|---|
| minute | scalp | quarter | half | hourly |
| swing | daily | weekly | ticks | micro |

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

## How it finds anything

Nothing is anchored to screen coordinates. thinkorswim layouts differ per
user and change through the day, so a fixed region works on one machine and
nowhere else.

Structural discovery is not available either: the chart's controls cannot be
reached through `AXChildren`. The combo box holding the symbol reports the
window as its parent, yet the window does not list it as a child - the link
exists upward but not downward. A full walk of 2,500 elements finds the news
panel's symbol box and never the chart's.

What the tree *does* expose reliably is the container layout. So the agent
asks the tree where the panes are and hit-tests relative to each pane's own
bounds, validating a candidate before acting on it. The aggregation control
anchors on the labelled "Style" button beside it. Move the chart, resize it,
switch to a grid - discovery follows, and takes about a second.

## Status

Early. The thinkorswim adapter works; the interfaces are still moving.

## License

Apache-2.0
