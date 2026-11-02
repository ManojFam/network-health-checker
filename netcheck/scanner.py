"""Runs the probes against many devices in parallel and decides each device's status."""

from __future__ import annotations

import dataclasses
import ipaddress
import socket
from collections.abc import Callable, Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from netcheck import probes
from netcheck.config import Device
from netcheck.probes import PingResult, PortResult

PingFunc = Callable[[str, float], PingResult]
PortFunc = Callable[[str, int, float], PortResult]

# A /22 has 1022 usable addresses. Anything bigger is probably a typo (a /16 is 65k hosts).
MAX_SWEEP_HOSTS = 1024


class Status(str, Enum):
    UP = "UP"
    DEGRADED = "DEGRADED"
    DOWN = "DOWN"


@dataclass
class DeviceResult:
    device: Device
    ping: PingResult
    ports: list[PortResult]
    status: Status
    checked_at: datetime = field(default_factory=lambda: datetime.now().astimezone())

    @property
    def open_ports(self) -> list[int]:
        return [p.port for p in self.ports if p.open]

    @property
    def closed_ports(self) -> list[int]:
        return [p.port for p in self.ports if not p.open]


def evaluate_status(ping: PingResult, ports: Sequence[PortResult]) -> Status:
    """UP: every expected port is open (or, with no ports listed, it answers ping).
    DEGRADED: the device answers but something expected is missing, e.g. a printer that
    pings but whose web page is closed. DOWN: nothing answered.

    Ping alone is not trusted to mean "down": Windows Firewall blocks ping by default, so a
    server with all its ports open counts as UP even without a ping reply.
    """
    if not ports:
        return Status.UP if ping.reachable else Status.DOWN
    open_count = sum(1 for p in ports if p.open)
    if open_count == len(ports):
        return Status.UP
    if open_count or ping.reachable:
        return Status.DEGRADED
    return Status.DOWN


def check_device(
    device: Device,
    *,
    timeout: float = 1.0,
    ping: PingFunc | None = None,
    port_check: PortFunc | None = None,
) -> DeviceResult:
    # Probes are looked up when called (not as default arguments) so tests can replace them.
    ping = ping or probes.ping_host
    port_check = port_check or probes.check_port

    ping_result = ping(device.host, timeout)
    port_results = [port_check(device.host, port, timeout) for port in device.ports]
    return DeviceResult(
        device, ping_result, port_results, evaluate_status(ping_result, port_results)
    )


def check_devices(
    devices: Sequence[Device],
    *,
    timeout: float = 1.0,
    workers: int = 32,
    ping: PingFunc | None = None,
    port_check: PortFunc | None = None,
) -> list[DeviceResult]:
    """Checks devices in parallel. The work is mostly waiting on the network, so threads
    are enough. Results come back in the same order as the input."""
    if not devices:
        return []

    def run(device: Device) -> DeviceResult:
        return check_device(device, timeout=timeout, ping=ping, port_check=port_check)

    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(devices)))) as pool:
        return list(pool.map(run, devices))


def sweep_hosts(network: str, max_hosts: int = MAX_SWEEP_HOSTS) -> list[str]:
    """Usable host addresses in a subnet, e.g. 192.168.1.0/24 -> .1 to .254."""
    try:
        net = ipaddress.ip_network(network, strict=False)
    except ValueError as exc:
        raise ValueError(f"'{network}' is not a valid subnet (example: 192.168.1.0/24)") from exc
    if net.num_addresses > max_hosts + 2:
        raise ValueError(
            f"{net} has {net.num_addresses} addresses; the limit is {max_hosts}. "
            "Sweep a smaller range, e.g. one /24 at a time."
        )
    hosts = list(net.hosts()) or [net.network_address]
    return [str(host) for host in hosts]


def reverse_dns(address: str) -> str | None:
    try:
        return socket.gethostbyaddr(address)[0]
    except OSError:
        return None


def sweep(
    network: str,
    ports: Iterable[int] = (),
    *,
    timeout: float = 1.0,
    workers: int = 64,
    resolve_names: bool = False,
    ping: PingFunc | None = None,
    port_check: PortFunc | None = None,
) -> list[DeviceResult]:
    """Finds the hosts in a subnet that answer ping or have one of `ports` open.
    Only live hosts are returned."""
    ports = tuple(ports)
    devices = [Device(name=h, host=h, type="discovered", ports=ports) for h in sweep_hosts(network)]
    results = check_devices(
        devices, timeout=timeout, workers=workers, ping=ping, port_check=port_check
    )
    alive = [r for r in results if r.status is not Status.DOWN]

    if resolve_names:
        for index, result in enumerate(alive):
            name = reverse_dns(result.device.host)
            if name:
                alive[index] = dataclasses.replace(
                    result, device=dataclasses.replace(result.device, name=name)
                )
    return alive
