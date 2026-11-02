"""Loads the device list from YAML or CSV and validates every entry."""

from __future__ import annotations

import csv
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from netcheck.probes import is_valid_host


class ConfigError(ValueError):
    """The device file is missing, unreadable or has an invalid entry."""


@dataclass(frozen=True)
class Device:
    name: str
    host: str
    type: str = "device"
    ports: tuple[int, ...] = ()
    critical: bool = False


def parse_ports(value: Any) -> tuple[int, ...]:
    """Accepts [22, 443], "22,443", "22;443" or "22 443". Duplicates are dropped."""
    if value is None or value == "":
        return ()
    if isinstance(value, int):
        items: Iterable[Any] = [value]
    elif isinstance(value, str):
        items = value.replace(";", " ").replace(",", " ").split()
    else:
        items = value

    ports: list[int] = []
    for item in items:
        try:
            port = int(item)
        except (TypeError, ValueError):
            raise ConfigError(f"'{item}' is not a port number") from None
        if not 1 <= port <= 65535:
            raise ConfigError(f"port {port} is outside 1-65535")
        if port not in ports:
            ports.append(port)
    return tuple(ports)


def _parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def make_device(entry: dict[str, Any], position: int) -> Device:
    where = f"device #{position}"
    host = str(entry.get("host") or "").strip()
    if not host:
        raise ConfigError(f"{where}: 'host' is required")
    if not is_valid_host(host):
        raise ConfigError(f"{where}: '{host}' is not a valid hostname or IP address")
    try:
        ports = parse_ports(entry.get("ports"))
    except ConfigError as exc:
        raise ConfigError(f"{where} ({host}): {exc}") from None
    return Device(
        name=str(entry.get("name") or host).strip(),
        host=host,
        type=str(entry.get("type") or "device").strip(),
        ports=ports,
        critical=_parse_bool(entry.get("critical", False)),
    )


def load_devices(path: str | Path) -> list[Device]:
    """Reads a .yaml/.yml or .csv device file.

    YAML can be a plain list of devices or a mapping with a "devices" key.
    CSV needs a header row: name,host,type,ports,critical (ports separated by ; or spaces).
    """
    path = Path(path)
    if not path.is_file():
        raise ConfigError(f"device file not found: {path}")

    suffix = path.suffix.lower()
    if suffix in {".yaml", ".yml"}:
        with path.open(encoding="utf-8") as handle:
            try:
                data = yaml.safe_load(handle)
            except yaml.YAMLError as exc:
                raise ConfigError(f"{path}: invalid YAML: {exc}") from None
        entries = data.get("devices") if isinstance(data, dict) else data
    elif suffix == ".csv":
        with path.open(encoding="utf-8-sig", newline="") as handle:
            entries = list(csv.DictReader(handle))
    else:
        raise ConfigError(f"{path}: use a .yaml, .yml or .csv file")

    if not isinstance(entries, list) or not entries:
        raise ConfigError(f"{path}: no devices found")
    for position, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            raise ConfigError(f"device #{position}: expected name/host/ports fields")
    return [make_device(entry, position) for position, entry in enumerate(entries, start=1)]
