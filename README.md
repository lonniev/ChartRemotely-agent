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
| `snapshot` | Return a small JPEG of the chart's own pane, so you can see it from afar |

There is no command that opens an order ticket, submits a trade, moves money,
or reads account balances. Adding one would mean editing that file, in public,
in this repository.

### What a snapshot shows

Only the pane that holds the chart. The top bar with the account number, and
the left-hand account, watchlist and news gadgets, never leave the machine.
When the agent cannot tell the chart's pane apart from the whole window, it
refuses rather than send the window.

The chart pane still shows whatever thinkorswim draws inside it. On a Mac that
drives a display, set the chart up for being looked at from elsewhere:

- collapse the **Active Trader** ladder on the right (it shows P/L Open,
  P/L Day and Net Pos);
- turn off the position, open-order and trade-history markers in the chart's
  own settings.

Snapshots need macOS **Screen Recording** for the Python that runs the relay,
as well as Accessibility.

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
chartremotely setup                         pair this Mac and make its voice Shortcut
chartremotely permissions                   report Accessibility and Screen Recording
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

`chartremotely setup` installs both transports as launchd agents
(`com.chartremotely.serve` and `com.chartremotely.relay`), logging to
`~/Library/Logs/chartremotely-<command>.log`. Two services rather than one, so
a relay that loses the network cannot take the local listener down with it.

Time frames are spoken as mnemonics chosen for phonetic distance, because
digits are the worst thing to say to a recogniser - "fifteen" and "fifty"
collide, and so do "one" and "won":

| | | | | |
|---|---|---|---|---|
| minute | scalp | quarter | half | hourly |
| swing | daily | weekly | ticks | micro |

## Install

```bash
curl -fsSL https://chartremotely.tollbooth-dpyc.com/install.sh | sh
```

That installs [uv](https://docs.astral.sh/uv/) if it is missing, installs this
agent from PyPI (`uv tool install --python 3.12 'chartremotely[macos,setup]'`),
and runs `chartremotely setup`, which:

1. proves who owns the display — your existing npub by answering a Nostr DM,
   a key already saved on this Mac, or a new key it makes and saves for you
   in the Keychain and, through Safari, in iCloud Passwords;
2. pairs this Mac with that identity, with no code to copy;
3. gives the Mac its tailnet address with `tailscale serve`;
4. installs the listener and the relay as launchd agents;
5. asks macOS for Accessibility and Screen Recording for the Python that runs them;
6. makes this Mac's ChartRemotely voice Shortcut and opens it for import.

Run it again at any time: finished steps are skipped. `chartremotely doctor`
reports anything still missing.

To pair by hand instead, run `chartremotely pair` and give the code it prints
to your MCP client (`chart_pair_agent`), or type it on the site's Profile page.

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
