import pytest

from netcheck.config import Device
from netcheck.probes import PingResult, PortResult
from netcheck.scanner import Status, check_devices, evaluate_status, sweep, sweep_hosts

OPEN = PortResult(80, True, "open")
CLOSED = PortResult(443, False, "refused")


@pytest.mark.parametrize(
    ("ping_ok", "ports", "expected"),
    [
        (True, [], Status.UP),  # ping-only device that answers
        (False, [], Status.DOWN),  # ping-only device that does not
        (True, [OPEN], Status.UP),
        (False, [OPEN], Status.UP),  # firewall blocks ping, but the service works
        (True, [OPEN, CLOSED], Status.DEGRADED),
        (True, [CLOSED], Status.DEGRADED),  # alive, service not running
        (False, [OPEN, CLOSED], Status.DEGRADED),
        (False, [CLOSED], Status.DOWN),
    ],
)
def test_evaluate_status(ping_ok, ports, expected):
    assert evaluate_status(PingResult(ping_ok), ports) is expected


def test_check_devices_keeps_input_order_and_records_ports(fake_network):
    net = fake_network(reachable={"10.0.0.1", "10.0.0.2"}, open_ports={"10.0.0.1": {22, 443}})
    devices = [
        Device("Switch", "10.0.0.1", ports=(22, 443)),
        Device("Printer", "10.0.0.2", ports=(9100,)),
        Device("Old server", "10.0.0.3", ports=(3389,), critical=True),
    ]
    results = check_devices(devices, ping=net.ping, port_check=net.port_check, workers=3)

    assert [r.device.name for r in results] == ["Switch", "Printer", "Old server"]
    assert [r.status for r in results] == [Status.UP, Status.DEGRADED, Status.DOWN]
    assert results[0].open_ports == [22, 443]
    assert results[1].closed_ports == [9100]
    assert results[0].ping.latency_ms == 1.5


def test_check_devices_with_no_devices():
    assert check_devices([]) == []


class TestSweepHosts:
    def test_slash_24_has_254_hosts(self):
        hosts = sweep_hosts("192.168.1.0/24")
        assert len(hosts) == 254 and hosts[0] == "192.168.1.1" and hosts[-1] == "192.168.1.254"

    def test_host_bits_are_ignored(self):
        assert sweep_hosts("192.168.1.77/30") == ["192.168.1.77", "192.168.1.78"]

    def test_single_address(self):
        assert sweep_hosts("10.0.0.5/32") == ["10.0.0.5"]

    def test_refuses_huge_ranges(self):
        with pytest.raises(ValueError, match="limit"):
            sweep_hosts("10.0.0.0/16")

    def test_explains_a_bad_subnet(self):
        with pytest.raises(ValueError, match="192.168.1.0/24"):
            sweep_hosts("192.168.1")


def test_sweep_returns_only_live_hosts(fake_network):
    # .1 answers ping, .3 blocks ping but has RDP open, everything else is silent.
    net = fake_network(reachable={"192.168.50.1"}, open_ports={"192.168.50.3": {3389}})
    results = sweep("192.168.50.0/29", ports=[22, 3389], ping=net.ping, port_check=net.port_check)

    assert [r.device.host for r in results] == ["192.168.50.1", "192.168.50.3"]
    assert results[1].open_ports == [3389]
    assert len(net.pinged) == 6  # every usable address in the /29 was tried


def test_sweep_can_add_dns_names(fake_network, monkeypatch):
    net = fake_network(reachable={"192.168.50.1"})
    monkeypatch.setattr("netcheck.scanner.reverse_dns", lambda ip: "gateway.contoso.local")
    results = sweep("192.168.50.0/30", resolve_names=True, ping=net.ping, port_check=net.port_check)
    assert results[0].device.name == "gateway.contoso.local"
    assert results[0].device.host == "192.168.50.1"
