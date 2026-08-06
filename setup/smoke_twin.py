"""Run a real local OpenPLC/Modbus smoke test for the 2D Twin."""

from __future__ import annotations

import sys
import time
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# The Service Manager intentionally runs OpenPLC Web on 8081 because 8080 is
# commonly occupied by llama.cpp or another local service.
os.environ.setdefault("OPENPLC_WEB_BASE", "http://127.0.0.1:8081")

from compiler import compile_st_code
from motion_contract import validate_motion_contract
from twin_client import TwinClient
from twin_deployment import deploy_to_twin, load_deployment, stop_twin


def _compile(fixture: Path):
    source_code = fixture.read_text(encoding="utf-8")
    compiled = compile_st_code(source_code)
    if compiled["status"] != "compiled":
        raise RuntimeError(f"Twin fixture did not compile: {compiled}")
    return source_code, compiled


def _jog_smoke() -> None:
    fixture = ROOT / "tests" / "fixtures" / "direction_switch_runtime.st"
    source_code, compiled = _compile(fixture)

    deploy = None
    try:
        deploy = deploy_to_twin(
            compiled["full_source"],
            source_code,
            "JOG",
            timeout_s=30,
            command_map=compiled.get("axis_command_map"),
        )
        if deploy["status"] != "running":
            raise RuntimeError(f"OpenPLC deployment failed: {deploy}")
        assert load_deployment()["source_hash"] == deploy["source_hash"]

        client = TwinClient()
        before = client.read_state()
        client.start()
        time.sleep(0.4)
        moving = client.read_state()
        client.stop()
        time.sleep(0.2)
        stopped = client.read_state()

        assert moving.enabled and moving.moving and moving.velocity > 0, moving
        assert not stopped.moving and stopped.velocity == 0, stopped
        print(
            "Twin smoke passed: "
            f"position {before.position:.1f} -> {moving.position:.1f} mm, "
            f"moving velocity {moving.velocity:.1f} mm/s, "
            f"stopped velocity {stopped.velocity:.1f} mm/s"
        )
    finally:
        if deploy and deploy.get("status") == "running":
            stop_twin()


def _absolute_smoke() -> None:
    fixture = ROOT / "tests" / "fixtures" / "absolute_runtime.st"
    source_code = fixture.read_text(encoding="utf-8").replace(
        "250.0", "1000.0"
    ).replace("800.0", "200.0")
    compiled = compile_st_code(source_code)
    if compiled["status"] != "compiled":
        raise RuntimeError(f"Twin fixture did not compile: {compiled}")
    request = {
        "mode": "Absolute Position",
        "requested_position": 1000,
        "requested_velocity": 200,
        "requested_direction": "forward",
    }
    contract = validate_motion_contract(source_code, request)
    assert contract["status"] == "passed", contract

    deploy = None
    try:
        deploy = deploy_to_twin(
            compiled["full_source"],
            source_code,
            contract["actual_mode"],
            timeout_s=30,
            contract=contract,
            command_map=compiled.get("axis_command_map"),
        )
        if deploy["status"] != "running":
            raise RuntimeError(f"OpenPLC deployment failed: {deploy}")

        client = TwinClient()
        client.start()
        reached = _wait_for_target(client, 1000.0, 15.0)
        assert reached.done and not reached.moving, reached
        assert reached.position == 1000.0, reached
        assert reached.target_position == 1000.0, reached
        assert reached.velocity == 0.0, reached

        client.move_absolute(500.0, 400.0)
        second = _wait_for_target(client, 500.0, 8.0)
        assert second.done and second.position == 500.0, second

        client.move_absolute(-300.0, 400.0)
        third = _wait_for_target(client, -300.0, 10.0)
        assert third.done and third.position == -300.0, third
        assert third.velocity == 0.0, third
        print(
            "Absolute Twin smoke passed: "
            "1000.0 -> 500.0 -> -300.0 mm, final velocity 0.0 mm/s"
        )
    finally:
        if deploy and deploy.get("status") == "running":
            stop_twin()


def _wait_for_target(client: TwinClient, target: float, timeout_s: float):
    deadline = time.monotonic() + timeout_s
    while True:
        reached = client.read_state()
        if (
            reached.done
            and reached.position == target
            and reached.target_position == target
        ) or time.monotonic() >= deadline:
            return reached
        time.sleep(0.1)


def main() -> int:
    _jog_smoke()
    _absolute_smoke()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
