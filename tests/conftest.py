import socket

import pytest

from netcheck.probes import PingResult, PortResult


@pytest.fixture
def listening_port():
    """A real TCP port on localhost that accepts connections, for the duration of a test."""
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen()
    yield server.getsockname()[1]
    server.close()


@pytest.fixture
def closed_port():
    """A localhost port with nothing listening on it."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    return port


class FakeNetwork:
    """Stands in for ping_host / check_port: answers from a dictionary instead of the network.

    reachable: hosts that answer ping
    open_ports: {host: {ports that are open}}
    """

    def __init__(self, reachable=(), open_ports=None):
        self.reachable = set(reachable)
        self.open_ports = open_ports or {}
        self.pinged = []

    def ping(self, host, timeout):
        self.pinged.append(host)
        if host in self.reachable:
            return PingResult(True, 1.5)
        return PingResult(False)

    def port_check(self, host, port, timeout):
        is_open = port in self.open_ports.get(host, set())
        return PortResult(port, is_open, "open" if is_open else "refused")


@pytest.fixture
def fake_network():
    return FakeNetwork
