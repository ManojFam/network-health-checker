import subprocess

import pytest

from netcheck import probes
from netcheck.probes import (
    build_ping_command,
    check_port,
    is_valid_host,
    parse_ping_output,
    ping_host,
)

WINDOWS_REPLY = """
Pinging 192.168.1.1 with 32 bytes of data:
Reply from 192.168.1.1: bytes=32 time=4ms TTL=64

Ping statistics for 192.168.1.1:
    Packets: Sent = 1, Received = 1, Lost = 0 (0% loss),
"""

# Windows exits with 0 here, even though the target never answered.
WINDOWS_UNREACHABLE = """
Pinging 192.168.1.99 with 32 bytes of data:
Reply from 192.168.1.5: Destination host unreachable.

Ping statistics for 192.168.1.99:
    Packets: Sent = 1, Received = 1, Lost = 0 (0% loss),
"""

LINUX_REPLY = """
PING 10.0.0.1 (10.0.0.1) 56(84) bytes of data.
64 bytes from 10.0.0.1: icmp_seq=1 ttl=63 time=0.412 ms
"""


class TestPingCommand:
    def test_windows_uses_count_and_milliseconds(self):
        assert build_ping_command("10.0.0.1", 1.5, "Windows") == [
            "ping",
            "-n",
            "1",
            "-w",
            "1500",
            "10.0.0.1",
        ]

    def test_linux_uses_whole_seconds(self):
        assert build_ping_command("10.0.0.1", 1.5, "Linux") == [
            "ping",
            "-c",
            "1",
            "-W",
            "2",
            "10.0.0.1",
        ]

    def test_linux_waits_at_least_one_second(self):
        assert build_ping_command("10.0.0.1", 0.2, "Linux")[4] == "1"


class TestPingOutput:
    def test_windows_reply(self):
        assert parse_ping_output(WINDOWS_REPLY, 0) == probes.PingResult(True, 4.0)

    def test_windows_sub_millisecond_reply(self):
        result = parse_ping_output(WINDOWS_REPLY.replace("time=4ms", "time<1ms"), 0)
        assert result.reachable and result.latency_ms == 1.0

    def test_windows_unreachable_with_exit_code_0_is_not_a_reply(self):
        assert parse_ping_output(WINDOWS_UNREACHABLE, 0).reachable is False

    def test_linux_reply(self):
        assert parse_ping_output(LINUX_REPLY, 0) == probes.PingResult(True, 0.412)

    def test_non_zero_exit_code_is_not_a_reply(self):
        assert parse_ping_output(LINUX_REPLY, 1).reachable is False


class TestPingHost:
    def test_runs_ping_and_parses_the_output(self, monkeypatch):
        calls = []

        def fake_run(command, **kwargs):
            calls.append(command)
            return subprocess.CompletedProcess(command, 0, stdout=LINUX_REPLY, stderr="")

        monkeypatch.setattr(probes.subprocess, "run", fake_run)
        assert ping_host("10.0.0.1").reachable is True
        assert calls[0][0] == "ping" and calls[0][-1] == "10.0.0.1"

    def test_missing_ping_command_counts_as_no_reply(self, monkeypatch):
        def fake_run(command, **kwargs):
            raise FileNotFoundError("ping")

        monkeypatch.setattr(probes.subprocess, "run", fake_run)
        assert ping_host("10.0.0.1").reachable is False

    def test_never_passes_an_option_looking_host_to_ping(self, monkeypatch):
        def fail_run(command, **kwargs):
            raise AssertionError("ping should not run")

        monkeypatch.setattr(probes.subprocess, "run", fail_run)
        assert ping_host("-f 10.0.0.1").reachable is False


@pytest.mark.parametrize(
    "host", ["192.168.1.1", "fileserver.contoso.local", "fe80::1", "PRINTER-01"]
)
def test_valid_hosts(host):
    assert is_valid_host(host)


@pytest.mark.parametrize("host", ["", "-t", "10.0.0.1; rm -rf /", "two words", "a" * 300])
def test_invalid_hosts(host):
    assert not is_valid_host(host)


class TestCheckPort:
    def test_open_port(self, listening_port):
        result = check_port("127.0.0.1", listening_port, timeout=2)
        assert result.open is True and result.detail == "open"

    def test_closed_port(self, closed_port):
        result = check_port("127.0.0.1", closed_port, timeout=3)
        assert result.open is False

    def test_unknown_hostname(self):
        result = check_port("no-such-host.invalid", 80, timeout=2)
        assert result.open is False and result.detail
