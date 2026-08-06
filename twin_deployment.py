"""Persistent OpenPLC deployment lifecycle shared by PLC-Assist and Twin UI."""

from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path

import simulator


STATE_FILE = Path(__file__).resolve().parent / ".runlogs" / "twin-deployment.json"


def _ensure_twin_ui() -> dict:
    """Start the separately managed Streamlit Twin UI when it is not online."""
    from service_manager import ServiceManager

    return ServiceManager().start("ui_twin")


def source_hash(source_code: str) -> str:
    return hashlib.sha256((source_code or "").encode("utf-8")).hexdigest()


def _save(info: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary = STATE_FILE.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary.replace(STATE_FILE)


def load_deployment() -> dict | None:
    try:
        value = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except (OSError, ValueError):
        return None


def deploy_to_twin(
    full_source: str,
    source_code: str,
    mode: str,
    timeout_s: int = 30,
    contract: dict | None = None,
    command_map: dict | None = None,
) -> dict:
    """Deploy and leave the OpenPLC runtime running for interactive Twin use."""
    digest = source_hash(source_code)
    safe_mode = re.sub(r"[^a-z0-9]+", "_", (mode or "axis").lower()).strip("_")
    program_name = f"twin_{safe_mode or 'axis'}_{digest[:8]}_{int(time.time())}"
    pending = {
        "status": "deploying",
        "program_name": program_name,
        "mode": mode or "Unknown",
        "source_hash": digest,
        "deployed_at": int(time.time()),
        "web_base": simulator.WEB_BASE,
        "modbus_host": simulator.MODBUS_HOST,
        "modbus_port": simulator.MODBUS_PORT,
        "interactive_target": bool(command_map),
        "adapter_version": 2,
    }
    if contract:
        if contract.get("observed_position") is not None:
            pending["target_position"] = contract["observed_position"]
        if contract.get("observed_velocity") is not None:
            pending["target_velocity"] = contract["observed_velocity"]
    _save(pending)
    # A previous interactive runtime may still own Modbus port 502. Stop it
    # before compiling/starting the new identity so deploy cannot attach to a
    # stale openplc.exe process.
    simulator.stop_openplc()
    result = simulator.deploy_program(full_source, program_name, timeout_s=timeout_s)
    if result.get("status") != "started":
        failed = {
            "status": result.get("status", "deploy_failed"),
            "message": result.get("log", "Unknown OpenPLC deployment error"),
            **{key: value for key, value in pending.items() if key != "status"},
        }
        _save(failed)
        return failed

    try:
        twin_ui = _ensure_twin_ui()
    except Exception as exc:
        failed = {
            "status": "ui_start_failed",
            "message": f"OpenPLC 已部署，但 2D Twin UI 啟動失敗：{exc}",
            **{key: value for key, value in pending.items() if key != "status"},
        }
        _save(failed)
        return failed

    info = {
        **pending,
        "status": "running",
        "twin_url": twin_ui.get("url", "http://127.0.0.1:8504"),
    }
    _save(info)
    return info


def stop_twin() -> dict:
    simulator.stop_openplc()
    info = load_deployment() or {}
    info.update({"status": "stopped", "stopped_at": int(time.time())})
    _save(info)
    return info
