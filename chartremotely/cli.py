"""Command line entry point."""

from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="chartremotely",
        description="Remote control of desktop charting applications on macOS.")
    sub = parser.add_subparsers(dest="command", required=True)

    show = sub.add_parser("show", help="put a security on the chart")
    show.add_argument("name", nargs="+", help="ticker or spoken company name")
    show.add_argument("--scale", default="", help="time frame mnemonic")

    scale = sub.add_parser("scale", help="change the chart's time frame")
    scale.add_argument("phrase", nargs="+")

    sub.add_parser("read", help="report the chart's symbol and scale")
    sub.add_parser("scales", help="list the time frames this chart offers")
    sub.add_parser("learn", help="rediscover the chart's controls")
    sub.add_parser("doctor", help="check everything this agent needs")
    sub.add_parser("token", help="print the agent's access token")

    setup = sub.add_parser("studies", help="rebuild the chart's study set")
    setup.add_argument("--row-height", default=None,
                       help="profile row height; match the strike increment (1.0, 2.5)")

    serve = sub.add_parser("serve", help="run the local listener")
    serve.add_argument("--port", type=int, default=None)

    pair = sub.add_parser("pair", help="adopt this display to an operator")
    pair.add_argument("--operator", default=None, help="operator base URL")

    relay = sub.add_parser("relay", help="hold a connection open for the operator")
    relay.add_argument("--operator", default=None)

    sub.add_parser("setup", help="pair this Mac and make its voice Shortcut, step by step")

    perms = sub.add_parser("permissions", help="report (or request) Accessibility and Screen Recording")
    perms.add_argument("--request", action="store_true", help="ask macOS to prompt for them")
    perms.add_argument("--out", default=None, help="write the answer as JSON to this file")

    args = parser.parse_args(argv)

    # Imported lazily so `doctor` can explain a missing dependency rather
    # than dying on an ImportError.
    if args.command == "doctor":
        from .doctor import report
        return report()
    if args.command == "token":
        from .config import ensure_token
        print(ensure_token())
        return 0
    if args.command == "pair":
        from .relay import pair as do_pair
        print("Give this code to your MCP client: ", end="", flush=True)
        try:
            do_pair(args.operator, on_code=lambda c: print(c, flush=True))
        except Exception as exc:  # noqa: BLE001 - surface the reason plainly
            print(f"pairing failed: {exc}")
            return 2
        print("paired")
        return 0
    if args.command == "setup":
        from .setup import SetupError
        from .setup import run as run_setup
        try:
            return run_setup()
        except (SetupError, RuntimeError, OSError) as exc:
            print(f"setup stopped: {exc}")
            print("Fix that, then run `chartremotely setup` again; finished steps are skipped.")
            return 2
    if args.command == "permissions":
        import json
        from pathlib import Path

        from .services import permissions
        answer = json.dumps(permissions(args.request))
        if args.out:
            Path(args.out).write_text(answer)
        print(answer)
        return 0
    if args.command == "relay":
        from .relay import run
        run(args.operator)
        return 0
    if args.command == "serve":
        from .server import serve as run
        run(args.port)
        return 0

    from . import symbol, timeframe
    from .vocab import ERR, cmd_resolve, cmd_set, dispatch

    if args.command == "show":
        spoken = " ".join(args.name)
        ticker = spoken if _looks_like_ticker(spoken) else cmd_resolve(spoken)
        if ticker.startswith(ERR):
            print(ticker)
            return 2
        print(cmd_set(ticker, args.scale))
        return 0
    if args.command == "scale":
        print(dispatch("scale " + " ".join(args.phrase)))
        return 0
    if args.command == "read":
        print(dispatch("read"))
        return 0
    if args.command == "scales":
        for label in timeframe.presets():
            print(" ", label)
        return 0
    if args.command == "studies":
        from . import studies
        for line in studies.setup(args.row_height):
            print(" ", line)
        return 0
    if args.command == "learn":
        symbol.learn()
        timeframe.learn()
        print("controls rediscovered")
        return 0
    return 1


def _looks_like_ticker(text: str) -> bool:
    from .symbol import TICKER
    return bool(TICKER.match(text.strip().upper()))


if __name__ == "__main__":
    sys.exit(main())
