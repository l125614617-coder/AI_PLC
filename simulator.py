"""Stages 3-5 of the validation pipeline: deploy the LLM's actual compiled
program (from compiler.compile_st_code()'s full_source) to a real OpenPLC_v3
runtime (installed under MSYS2, see the M2 smoke test) via its actual HTTP
endpoints, then drive/observe it over Modbus TCP to run scripted scenarios
(scenarios.py) against the axis-adapter's fixed io_map (see compiler.py's
AXIS_ADAPTER_IO_MAP). This is the "simulated automated deployment" step --
everything stays local (localhost web UI + localhost Modbus), no real hardware.

Each scenario redeploys the same compiled program fresh (simpler and avoids
state leaking between scenarios, at the cost of a few extra seconds per
scenario for OpenPLC's non-incremental rebuild)."""

import os
import re
import subprocess
import time
from pathlib import Path

import requests
from pymodbus.client.sync import ModbusTcpClient
from plc_config import load_plc_connection

_PROG_FILE_PATTERN = re.compile(r"value='([^']+)'\s+id='prog_file'")

OPENPLC_DIR = Path(f"C:/msys64/home/{os.environ.get('USERNAME', '')}/OpenPLC_v3")
_CONNECTION = load_plc_connection()
WEB_BASE = _CONNECTION.web_base
MODBUS_HOST = _CONNECTION.modbus_host
MODBUS_PORT = _CONNECTION.modbus_port
WEB_USERNAME = _CONNECTION.web_username
WEB_PASSWORD = _CONNECTION.web_password


def openplc_available() -> bool:
    return (OPENPLC_DIR / "webserver" / "webserver.py").is_file()


def _kill_lingering_openplc() -> None:
    """Best-effort: a prior run's openplc.exe holding port 502 would make this
    run's /start_plc silently attach to the wrong process state."""
    subprocess.run(["taskkill", "/F", "/IM", "openplc.exe"], capture_output=True)


def deploy_program(full_source: str, name: str, timeout_s: int = 30) -> dict:
    """Upload + compile + start `full_source` (as produced by
    compiler.compile_st_code -- stub library + adapted LLM code + CONFIGURATION)
    via OpenPLC's real HTTP endpoints.
    Returns {status: 'started'|'upload_failed'|'compile_failed'|'start_failed', log}.

    OpenPLC's upload flow is two steps, discovered empirically against this
    exact webserver.py: POST /upload-program just saves the file under a
    server-generated random filename and returns an HTML form; THAT form's
    submission to /upload-program-action is what inserts the DB row
    /compile-program looks up by filename. Compilation itself is async
    (spawned via subprocess.Popen inside the request handler), so we poll
    /compilation-logs until it prints its own completion line."""
    filename = f"{name}.st"

    session = requests.Session()
    login = session.post(f"{WEB_BASE}/login", data={"username": WEB_USERNAME, "password": WEB_PASSWORD}, timeout=10)
    if login.status_code != 200:
        return {"status": "upload_failed", "log": f"Login failed: HTTP {login.status_code}"}

    upload = session.post(
        f"{WEB_BASE}/upload-program",
        files={"file": (filename, full_source, "text/plain")},
        timeout=timeout_s,
    )
    match = _PROG_FILE_PATTERN.search(upload.text)
    if upload.status_code != 200 or not match:
        return {"status": "upload_failed", "log": f"Upload failed: HTTP {upload.status_code}\n{upload.text[:500]}"}
    server_filename = match.group(1)

    action = session.post(
        f"{WEB_BASE}/upload-program-action",
        data={
            "prog_name": name,
            "prog_descr": "PLC-Assist generated program",
            "prog_file": server_filename,
            "epoch_time": str(int(time.time())),
        },
        timeout=timeout_s,
    )
    if action.status_code != 200:
        return {"status": "upload_failed", "log": f"upload-program-action failed: HTTP {action.status_code}\n{action.text[:500]}"}

    compile_start = session.get(f"{WEB_BASE}/compile-program", params={"file": server_filename}, timeout=timeout_s)
    if compile_start.status_code != 200:
        return {"status": "compile_failed", "log": f"compile-program failed: HTTP {compile_start.status_code}"}

    deadline = time.time() + timeout_s
    log_text = ""
    while time.time() < deadline:
        time.sleep(0.5)
        logs = session.get(f"{WEB_BASE}/compilation-logs", timeout=timeout_s)
        log_text = logs.text
        if "compilation finished successfully" in log_text.lower():
            break
        if "compilation finished with errors" in log_text.lower():
            return {"status": "compile_failed", "log": log_text}
    else:
        return {"status": "compile_failed", "log": f"Compilation timed out after {timeout_s}s.\n{log_text}"}

    start_resp = session.get(f"{WEB_BASE}/start_plc", timeout=timeout_s)
    if start_resp.status_code != 200:
        return {"status": "start_failed", "log": f"start_plc failed: HTTP {start_resp.status_code}"}

    time.sleep(1.0)  # give the runtime a moment to bind the Modbus port
    return {"status": "started", "log": log_text, "session": session}


def stop_openplc(session: requests.Session = None) -> None:
    try:
        (session or requests).get(f"{WEB_BASE}/stop_plc", timeout=10)
    except requests.RequestException:
        pass
    _kill_lingering_openplc()


def _signed_register(value: int) -> int:
    return value - 0x10000 if value & 0x8000 else value


def _register_matches(actual: int, expected, registers: dict | None = None) -> bool:
    if not isinstance(expected, dict):
        return actual == expected
    return (
        ("eq" not in expected or actual == expected["eq"])
        and ("gt" not in expected or actual > expected["gt"])
        and ("gte" not in expected or actual >= expected["gte"])
        and ("lt" not in expected or actual < expected["lt"])
        and ("lte" not in expected or actual <= expected["lte"])
        and (
            "between" not in expected
            or expected["between"][0] <= actual <= expected["between"][1]
        )
        and (
            "equals_register" not in expected
            or registers is not None
            and actual == registers[expected["equals_register"]]
        )
    )


def run_scenario(
    scenario: dict,
    io_map: dict,
    full_source: str,
    timeout_s: int = 30,
    register_map: dict | None = None,
) -> dict:
    """Deploy `full_source` fresh, drive/assert `scenario`'s steps over Modbus
    against `io_map` (compiler.AXIS_ADAPTER_IO_MAP), then tear down.
    Returns {name, passed, deploy_status, steps: [{ok, expected, actual}], error}."""
    result = {"name": scenario["name"], "passed": False, "deploy_status": None, "steps": [], "error": None}

    deploy = deploy_program(full_source, scenario["name"], timeout_s=timeout_s)
    result["deploy_status"] = deploy["status"]
    if deploy["status"] != "started":
        result["error"] = deploy["log"]
        return result

    session = deploy["session"]
    client = None
    try:
        client = ModbusTcpClient(MODBUS_HOST, port=MODBUS_PORT, timeout=5)
        if not client.connect():
            result["error"] = f"Could not connect to Modbus server at {MODBUS_HOST}:{MODBUS_PORT}"
            return result

        n_coils = max(io_map.values()) + 1
        all_ok = True

        for step in scenario["steps"]:
            for signal, value in step.get("set", {}).items():
                client.write_coil(io_map[signal], bool(value))

            if "wait_s" in step:
                time.sleep(step["wait_s"])

            expected = step.get("assert", {})
            expected_registers = step.get("assert_register", {})
            if expected or expected_registers:
                ok = True
                actual = {}
                rr = client.read_coils(0, n_coils)
                if rr.isError():
                    ok = False
                    actual["coils_error"] = f"Modbus read error: {rr}"
                else:
                    actual["coils"] = {
                        sig: rr.bits[idx]
                        for sig, idx in io_map.items()
                        if sig in expected
                    }
                    ok = ok and all(
                        actual["coils"][sig] == value
                        for sig, value in expected.items()
                    )

                if expected_registers:
                    if not register_map:
                        ok = False
                        actual["registers_error"] = "No register map available"
                    else:
                        n_registers = max(register_map.values()) + 1
                        registers = client.read_holding_registers(0, n_registers)
                        if registers.isError():
                            ok = False
                            actual["registers_error"] = f"Modbus read error: {registers}"
                        else:
                            all_registers = {
                                sig: _signed_register(registers.registers[idx])
                                for sig, idx in register_map.items()
                            }
                            actual["registers"] = {
                                sig: all_registers[sig] for sig in expected_registers
                            }
                            ok = ok and all(
                                _register_matches(
                                    actual["registers"][sig],
                                    expectation,
                                    all_registers,
                                )
                                for sig, expectation in expected_registers.items()
                            )

                all_ok = all_ok and ok
                result["steps"].append({
                    "ok": ok,
                    "expected": expected,
                    "expected_registers": expected_registers,
                    "actual": actual,
                })

        result["passed"] = all_ok
    except Exception as e:
        result["error"] = str(e)
    finally:
        if client is not None:
            client.close()
        stop_openplc(session)

    return result


def run_all_scenarios(
    scenarios: list,
    io_map: dict,
    full_source: str,
    timeout_s: int = 30,
    register_map: dict | None = None,
) -> list:
    return [
        run_scenario(
            scenario,
            io_map,
            full_source,
            timeout_s=timeout_s,
            register_map=register_map,
        )
        for scenario in scenarios
    ]
