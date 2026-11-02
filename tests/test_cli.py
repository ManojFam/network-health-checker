import pytest

from netcheck import cli, probes


@pytest.fixture
def network(monkeypatch, fake_network):
    """Replaces the real probes for the whole CLI run."""
    net = fake_network(
        reachable={"10.0.0.1", "10.0.0.2"},
        open_ports={"10.0.0.1": {22, 443}, "10.0.0.2": {9100}},
    )
    monkeypatch.setattr(probes, "ping_host", net.ping)
    monkeypatch.setattr(probes, "check_port", net.port_check)
    return net


def devices_file(tmp_path, extra=""):
    path = tmp_path / "devices.yaml"
    path.write_text(
        "devices:\n"
        "  - {name: Switch, host: 10.0.0.1, ports: [22, 443], critical: true}\n"
        "  - {name: Printer, host: 10.0.0.2, ports: [9100]}\n" + extra,
        encoding="utf-8",
    )
    return path


def test_all_up_exits_0_and_writes_reports(network, tmp_path, capsys):
    csv_path, html_path = tmp_path / "r.csv", tmp_path / "r.html"
    code = cli.main(
        ["check", str(devices_file(tmp_path)), "--csv", str(csv_path), "--html", str(html_path)]
    )

    out = capsys.readouterr().out
    assert code == cli.EXIT_OK
    assert "2 device(s): 2 UP, 0 DEGRADED, 0 DOWN" in out
    assert csv_path.read_text(encoding="utf-8").startswith("name,host,type")
    assert "Device health - devices.yaml" in html_path.read_text(encoding="utf-8")


def test_degraded_device_exits_1(network, tmp_path):
    extra = "  - {name: Web, host: 10.0.0.2, ports: [9100, 80]}\n"
    assert cli.main(["check", str(devices_file(tmp_path, extra))]) == cli.EXIT_WARNING


def test_non_critical_device_down_exits_1(network, tmp_path):
    extra = "  - {name: Spare, host: 10.0.0.9, ports: [22]}\n"
    assert cli.main(["check", str(devices_file(tmp_path, extra))]) == cli.EXIT_WARNING


def test_critical_device_down_exits_2(network, tmp_path):
    extra = "  - {name: Server, host: 10.0.0.9, ports: [3389], critical: true}\n"
    assert cli.main(["check", str(devices_file(tmp_path, extra))]) == cli.EXIT_CRITICAL


def test_bad_device_file_exits_3(tmp_path, capsys):
    assert cli.main(["check", str(tmp_path / "missing.yaml")]) == cli.EXIT_UNKNOWN
    assert "not found" in capsys.readouterr().err


def test_bad_arguments_exit_3_not_argparse_default_2(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["sweep", "10.0.0.0/24", "--ports", "abc"])
    assert exc.value.code == cli.EXIT_UNKNOWN


def test_sweep_lists_live_hosts(network, capsys):
    code = cli.main(["sweep", "10.0.0.0/29", "--ports", "22,9100"])
    out = capsys.readouterr().out
    assert code == cli.EXIT_OK
    assert "10.0.0.1" in out and "10.0.0.2" in out and "10.0.0.3" not in out


def test_sweep_refuses_a_huge_subnet(capsys):
    assert cli.main(["sweep", "10.0.0.0/8"]) == cli.EXIT_UNKNOWN
    assert "limit" in capsys.readouterr().err
