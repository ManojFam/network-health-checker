"""Low-level network probes: ICMP ping (through the system ping command) and TCP connect.

The system ping command is used instead of raw ICMP sockets because raw sockets need
administrator/root rights, and the ping command works the same for every user.
"""

from __future__ import annotations

import platform
import re
import socket
import subprocess
from dataclasses import dataclass

# Hostnames, IPv4 and IPv6 addresses. Anything else (spaces, a leading "-" that ping
# would read as an option, shell characters) is rejected before it reaches a command.
_VALID_HOST = re.compile(r"^(?!-)[A-Za-z0-9.:_-]{1,253}$")
_LATENCY = re.compile(r"time[=<]\s*([\d.]+)\s*ms", re.IGNORECASE)


@dataclass(frozen=True)
class PingResult:
    reachable: bool
    latency_ms: float | None = None


@dataclass(frozen=True)
class PortResult:
    port: int
    open: bool
    detail: str = ""  # "open", "refused", "timeout" or the OS error text


def is_valid_host(host: str) -> bool:
    return bool(_VALID_HOST.match(host))


def build_ping_command(host: str, timeout: float, system: str | None = None) -> list[str]:
    """One echo request with a timeout. The flags differ per operating system."""
    system = (system or platform.system()).lower()
    if system == "windows":
        return ["ping", "-n", "1", "-w", str(int(timeout * 1000)), host]  # -w is milliseconds
    if system == "darwin":
        return ["ping", "-c", "1", "-W", str(int(timeout * 1000)), host]  # macOS: milliseconds
    return ["ping", "-c", "1", "-W", str(max(1, round(timeout))), host]  # Linux: whole seconds


def parse_ping_output(output: str, returncode: int) -> PingResult:
    """Decides whether a reply came back.

    Windows ping exits with 0 even when a router answers "Destination host unreachable",
    so a reply only counts when the output also contains a TTL (only real echo replies
    have one).
    """
    if returncode != 0 or "ttl=" not in output.lower():
        return PingResult(reachable=False)
    match = _LATENCY.search(output)
    return PingResult(reachable=True, latency_ms=float(match.group(1)) if match else None)


def ping_host(host: str, timeout: float = 1.0) -> PingResult:
    if not is_valid_host(host):
        return PingResult(reachable=False)
    command = build_ping_command(host, timeout)
    try:
        completed = subprocess.run(
            command, capture_output=True, text=True, errors="replace", timeout=timeout + 3
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return PingResult(reachable=False)
    return parse_ping_output(completed.stdout, completed.returncode)


def check_port(host: str, port: int, timeout: float = 1.0) -> PortResult:
    """Tries a full TCP connection, which is what a user's app would do."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return PortResult(port, True, "open")
    except ConnectionRefusedError:
        return PortResult(port, False, "refused")  # host is up, nothing listening
    except TimeoutError:
        return PortResult(port, False, "timeout")  # host down, or a firewall drops it
    except OSError as exc:  # includes DNS failures (socket.gaierror)
        return PortResult(port, False, exc.strerror or str(exc))
