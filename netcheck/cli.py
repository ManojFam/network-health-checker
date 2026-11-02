"""Command line entry point: `netcheck check <devices file>` and `netcheck sweep <subnet>`."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from netcheck import __version__
from netcheck.config import ConfigError, load_devices, parse_ports
from netcheck.report import format_table, summary_line, write_csv, write_html
from netcheck.scanner import DeviceResult, Status, check_devices, sweep

# Exit codes follow the Nagios plugin convention, so `netcheck check` can be used as a
# custom check in Nagios, Icinga, PRTG or a scheduled task that alerts on failure.
EXIT_OK = 0  # every device is UP
EXIT_WARNING = 1  # something is DEGRADED, or a non-critical device is DOWN
EXIT_CRITICAL = 2  # a device marked critical is DOWN
EXIT_UNKNOWN = 3  # bad arguments or device file; nothing was checked

DEFAULT_SWEEP_PORTS = "22,80,443,445,3389"


class _Parser(argparse.ArgumentParser):
    """argparse exits with 2 on bad arguments, which a monitoring tool would read as
    CRITICAL. Exit with 3 (UNKNOWN) instead."""

    def error(self, message: str):  # type: ignore[override]
        self.print_usage(sys.stderr)
        self.exit(EXIT_UNKNOWN, f"{self.prog}: error: {message}\n")


def _port_list(text: str) -> tuple[int, ...]:
    try:
        return parse_ports(text)
    except ConfigError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from None


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--timeout",
        type=float,
        default=1.0,
        help="seconds to wait for each ping or port (default 1)",
    )
    common.add_argument(
        "--workers", type=int, default=32, help="devices checked at the same time (default 32)"
    )
    common.add_argument("--csv", type=Path, metavar="FILE", help="also write a CSV report")
    common.add_argument("--html", type=Path, metavar="FILE", help="also write an HTML report")

    parser = _Parser(prog="netcheck", description="Network device inventory and health checker.")
    parser.add_argument("--version", action="version", version=f"netcheck {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    check = commands.add_parser(
        "check", parents=[common], help="check the devices listed in a YAML or CSV file"
    )
    check.add_argument("devices", type=Path, help="device file (.yaml, .yml or .csv)")

    sweep_cmd = commands.add_parser(
        "sweep", parents=[common], help="find the live hosts in a subnet"
    )
    sweep_cmd.add_argument("network", help="subnet in CIDR form, e.g. 192.168.1.0/24")
    sweep_cmd.add_argument(
        "--ports",
        type=_port_list,
        default=_port_list(DEFAULT_SWEEP_PORTS),
        help=f"TCP ports to try on each host (default {DEFAULT_SWEEP_PORTS})",
    )
    sweep_cmd.add_argument(
        "--resolve", action="store_true", help="look up each live host's name with reverse DNS"
    )
    return parser


def exit_code(results: Sequence[DeviceResult]) -> int:
    if any(r.status is Status.DOWN and r.device.critical for r in results):
        return EXIT_CRITICAL
    if any(r.status is not Status.UP for r in results):
        return EXIT_WARNING
    return EXIT_OK


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        if args.command == "check":
            devices = load_devices(args.devices)
            results = check_devices(devices, timeout=args.timeout, workers=args.workers)
            title = f"Device health - {args.devices.name}"
            code = exit_code(results)
        else:
            results = sweep(
                args.network,
                args.ports,
                timeout=args.timeout,
                workers=args.workers,
                resolve_names=args.resolve,
            )
            title = f"Network sweep - {args.network}"
            code = EXIT_OK  # a sweep is discovery: finding few hosts is not a failure
    except ValueError as exc:  # ConfigError is a ValueError too
        print(f"netcheck: error: {exc}", file=sys.stderr)
        return EXIT_UNKNOWN

    print(format_table(results) if results else "No hosts answered.")
    print()
    print(summary_line(results))

    try:
        if args.csv:
            print(f"CSV report:  {write_csv(results, args.csv)}")
        if args.html:
            print(f"HTML report: {write_html(results, args.html, title)}")
    except OSError as exc:
        print(f"netcheck: could not write report: {exc}", file=sys.stderr)
        return EXIT_UNKNOWN

    return code
