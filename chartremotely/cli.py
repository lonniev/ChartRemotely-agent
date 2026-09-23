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
