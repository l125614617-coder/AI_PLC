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

_PROG_FILE_PATTERN = re.compile(r"value='([^']+)'\s+id='prog_file'")

OPENPLC_DIR = Path(f"C:/msys64/home/{os.environ.get('USERNAME', '')}/OpenPLC_v3")
WEB_BASE = "http://localhost:8080"
MODBUS_HOST = "127.0.0.1"
MODBUS_PORT = 502
WEB_USERNAME = "openplc"
WEB_PASSWORD = "openplc"


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


def run_scenario(scenario: dict, io_map: dict, full_source: str, timeout_s: int = 30) -> dict:
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
            if expected:
                rr = client.read_coils(0, n_coils)
                if rr.isError():
                    all_ok = False
                    result["steps"].append({"ok": False, "expected": expected, "actual": f"Modbus read error: {rr}"})
                    continue
                actual = {sig: rr.bits[idx] for sig, idx in io_map.items() if sig in expected}
                ok = all(actual[sig] == val for sig, val in expected.items())
                all_ok = all_ok and ok
                result["steps"].append({"ok": ok, "expected": expected, "actual": actual})

        result["passed"] = all_ok
    except Exception as e:
        result["error"] = str(e)
    finally:
        if client is not None:
            client.close()
        stop_openplc(session)

    return result


def run_all_scenarios(scenarios: list, io_map: dict, full_source: str, timeout_s: int = 30) -> list:
    return [run_scenario(s, io_map, full_source, timeout_s=timeout_s) for s in scenarios]
