import csv

import pytest

from netcheck.config import Device
from netcheck.probes import PingResult, PortResult
from netcheck.report import CSV_FIELDS, format_table, render_html, summary_line, write_csv
from netcheck.scanner import DeviceResult, Status


@pytest.fixture
def results():
    return [
        DeviceResult(
            Device("Core switch", "10.0.0.2", "switch", (22, 443), True),
            PingResult(True, 2.0),
            [PortResult(22, True), PortResult(443, True)],
            Status.UP,
        ),
        DeviceResult(
            Device("Printer <lobby>", "10.0.0.50", "printer", (9100, 80)),
            PingResult(True, 5.5),
            [PortResult(9100, True), PortResult(80, False)],
            Status.DEGRADED,
        ),
        DeviceResult(
            Device("NAS", "10.0.0.60", "storage", (445,), True),
            PingResult(False),
            [PortResult(445, False)],
            Status.DOWN,
        ),
    ]


def test_csv_has_one_row_per_device(results, tmp_path):
    path = write_csv(results, tmp_path / "out" / "report.csv")
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))

    assert list(rows[0].keys()) == CSV_FIELDS
    assert [r["status"] for r in rows] == ["UP", "DEGRADED", "DOWN"]
    assert rows[1]["open_ports"] == "9100" and rows[1]["closed_ports"] == "80"
    assert rows[2]["ping"] == "no reply" and rows[2]["latency_ms"] == ""
    assert rows[0]["critical"] == "yes"


def test_summary_counts_each_status(results):
    assert summary_line(results) == "3 device(s): 1 UP, 1 DEGRADED, 1 DOWN"


def test_console_table_marks_critical_devices(results):
    table = format_table(results).splitlines()
    assert table[0].split() == ["STATUS", "NAME", "HOST", "PING", "PORTS"]
    assert "Core switch *" in table[2]
    assert "open 9100; closed 80" in table[3]


def test_html_escapes_device_names(results):
    page = render_html(results, "Office <network>")
    assert "Printer &lt;lobby&gt;" in page
    assert "<lobby>" not in page
    assert "<title>Office &lt;network&gt;</title>" in page


def test_html_shows_status_badges_and_counts(results):
    page = render_html(results, "Office")
    assert '<span class="badge degraded">DEGRADED</span>' in page
    assert "<strong>1</strong>DOWN" in page
