"""Validated OpenPLC/Modbus connection settings.

Simulation defaults are loopback-only. Connecting the automated scenario
runner to a non-loopback Modbus host requires an explicit opt-in so a generated
program cannot accidentally drive real equipment.
"""

from __future__ import annotations

import ipaddress
import os
from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass(frozen=True)
class PlcConnection:
    web_base: str
    modbus_host: str
    modbus_port: int
    web_username: str
    web_password: str
    allow_real_hardware: bool

    def validate(self) -> "PlcConnection":
        parsed = urlparse(self.web_base)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("OPENPLC_WEB_BASE must be an http(s) URL")
        if not 1 <= self.modbus_port <= 65535:
            raise ValueError("OPENPLC_MODBUS_PORT must be between 1 and 65535")

        hosts = {parsed.hostname.lower(), self.modbus_host.lower()}
        non_loopback = any(not _is_loopback(host) for host in hosts)
        if non_loopback and not self.allow_real_hardware:
            raise ValueError(
                "Non-loopback PLC target refused. Set "
                "PLC_ASSIST_ALLOW_REAL_HARDWARE=1 only after completing the "
                "site-specific I/O and safety review."
            )
        return self


def _is_loopback(host: str) -> bool:
    if host in {"localhost", "::1"}:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def load_plc_connection() -> PlcConnection:
    return PlcConnection(
        web_base=os.environ.get(
            "OPENPLC_WEB_BASE",
            "http://127.0.0.1:8080",
        ).rstrip("/"),
        modbus_host=os.environ.get("OPENPLC_MODBUS_HOST", "127.0.0.1"),
        modbus_port=int(os.environ.get("OPENPLC_MODBUS_PORT", "502")),
        web_username=os.environ.get("OPENPLC_WEB_USERNAME", "openplc"),
        web_password=os.environ.get("OPENPLC_WEB_PASSWORD", "openplc"),
        allow_real_hardware=os.environ.get(
            "PLC_ASSIST_ALLOW_REAL_HARDWARE",
            "",
        ).lower() in {"1", "true", "yes"},
    ).validate()
