from pathlib import Path

import pytest

from netcheck.config import ConfigError, Device, load_devices, parse_ports

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def write(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


class TestParsePorts:
    @pytest.mark.parametrize("value", [[22, 443], "22,443", "22;443", "22 443", "22, 443, 22"])
    def test_accepts_lists_and_separated_text(self, value):
        assert parse_ports(value) == (22, 443)

    def test_empty_means_ping_only(self):
        assert parse_ports(None) == () and parse_ports("") == ()

    @pytest.mark.parametrize("value", ["http", [0], "70000"])
    def test_rejects_bad_ports(self, value):
        with pytest.raises(ConfigError):
            parse_ports(value)


class TestLoadDevices:
    def test_yaml_with_devices_key(self, tmp_path):
        path = write(
            tmp_path,
            "d.yaml",
            """
devices:
  - name: Core switch
    host: 10.0.0.2
    type: switch
    ports: [22, 443]
    critical: true
""",
        )
        assert load_devices(path) == [Device("Core switch", "10.0.0.2", "switch", (22, 443), True)]

    def test_yaml_plain_list_and_defaults(self, tmp_path):
        path = write(tmp_path, "d.yml", "- host: printer01.contoso.local\n")
        device = load_devices(path)[0]
        assert device.name == "printer01.contoso.local"
        assert device.ports == () and device.critical is False and device.type == "device"

    def test_csv(self, tmp_path):
        path = write(
            tmp_path, "d.csv", "name,host,type,ports,critical\nNAS,10.0.0.5,storage,445;5000,yes\n"
        )
        assert load_devices(path) == [Device("NAS", "10.0.0.5", "storage", (445, 5000), True)]

    @pytest.mark.parametrize("name", ["devices.yaml", "devices.csv", "demo-public.yaml"])
    def test_example_files_load(self, name):
        assert load_devices(EXAMPLES / name)

    def test_missing_host_names_the_entry(self, tmp_path):
        path = write(tmp_path, "d.yaml", "- host: 10.0.0.1\n- name: No host here\n")
        with pytest.raises(ConfigError, match="device #2"):
            load_devices(path)

    def test_rejects_a_host_that_looks_like_a_command_option(self, tmp_path):
        path = write(tmp_path, "d.yaml", "- host: '-t 10.0.0.1'\n")
        with pytest.raises(ConfigError, match="not a valid hostname"):
            load_devices(path)

    def test_bad_port_names_the_device(self, tmp_path):
        path = write(tmp_path, "d.yaml", "- host: 10.0.0.1\n  ports: [80, web]\n")
        with pytest.raises(ConfigError, match=r"10\.0\.0\.1.*'web'"):
            load_devices(path)

    def test_missing_file(self, tmp_path):
        with pytest.raises(ConfigError, match="not found"):
            load_devices(tmp_path / "nope.yaml")

    def test_unsupported_extension(self, tmp_path):
        with pytest.raises(ConfigError, match="yaml"):
            load_devices(write(tmp_path, "d.txt", "10.0.0.1"))

    def test_empty_file(self, tmp_path):
        with pytest.raises(ConfigError, match="no devices"):
            load_devices(write(tmp_path, "d.yaml", ""))

    def test_invalid_yaml(self, tmp_path):
        with pytest.raises(ConfigError, match="invalid YAML"):
            load_devices(write(tmp_path, "d.yaml", "devices: [unclosed"))
