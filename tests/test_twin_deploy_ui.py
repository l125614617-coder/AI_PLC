import hashlib
from unittest.mock import patch

from streamlit.testing.v1 import AppTest


CODE = "PROGRAM MAIN\nEND_PROGRAM"
DIGEST = hashlib.sha256(CODE.encode("utf-8")).hexdigest()


def test_validated_current_source_can_be_deployed_to_twin(monkeypatch):
    monkeypatch.setenv("OPENPLC_WEB_BASE", "http://localhost:8081")
    deployment = {
        "status": "running",
        "program_name": "twin_jog_test",
        "mode": "JOG",
        "source_hash": DIGEST,
    }

    app = AppTest.from_file("app_llamacpp.py", default_timeout=30)
    app.session_state["generated"] = True
    app.session_state["plc_data"] = {
        "code": CODE,
        "variables": "",
        "explanation": "",
        "warnings": "",
        "requested_mode": "JOG",
        "requested_control": {
            "mode": "JOG",
            "requested_velocity": 1500,
            "requested_position": 0,
            "requested_direction": "forward",
        },
        "validation": {
            "score": 100,
            "status": "passed",
            "stats": {},
            "issues": [],
        },
    }
    app.session_state["sim_result"] = {
        "source_hash": DIGEST,
        "contract": {"status": "passed", "actual_mode": "JOG"},
        "compile": {
            "status": "compiled",
            "issues": [],
            "axis_io_map": {"start": 8},
            "axis_register_map": {"position_x10": 0},
            "axis_command_map": {
                "apply_target": 15,
                "command_position_x10": 6,
                "command_velocity_x10": 7,
            },
            "full_source": "COMPILED SOURCE",
        },
        "scenarios": {
            "status": "ran",
            "results": [{"name": "enable_responds", "passed": True, "steps": []}],
        },
    }

    with patch("twin_deployment.load_deployment", return_value=deployment), patch(
        "twin_deployment.deploy_to_twin", return_value=deployment
    ) as deploy:
        app.run()
        button = next(b for b in app.button if "部署至 2D Twin" in b.label)
        assert not button.disabled
        app = button.click().run(timeout=30)

    assert not app.exception
    deploy.assert_called_once_with(
        "COMPILED SOURCE",
        CODE,
        "JOG",
        contract={"status": "passed", "actual_mode": "JOG"},
        command_map={
            "apply_target": 15,
            "command_position_x10": 6,
            "command_velocity_x10": 7,
        },
    )
    assert any("Twin Runtime 已部署" in message.value for message in app.success)


def test_stale_validation_cannot_be_deployed(monkeypatch):
    monkeypatch.setenv("OPENPLC_WEB_BASE", "http://localhost:8081")
    app = AppTest.from_file("app_llamacpp.py", default_timeout=30)
    app.session_state["generated"] = True
    app.session_state["plc_data"] = {
        "code": CODE,
        "validation": {"score": 100, "status": "passed", "stats": {}, "issues": []},
    }
    app.session_state["sim_result"] = {
        "source_hash": "old-source",
        "contract": {"status": "passed", "actual_mode": "JOG"},
        "compile": {"status": "compiled", "issues": [], "axis_io_map": {"start": 8}},
        "scenarios": {"status": "ran", "results": [{"name": "ok", "passed": True}]},
    }

    app.run()

    button = next(b for b in app.button if "部署至 2D Twin" in b.label)
    assert button.disabled
    assert any("上一份 ST" in warning.value for warning in app.warning)


def test_absolute_request_with_jog_code_is_blocked_before_runtime(monkeypatch):
    monkeypatch.setenv("OPENPLC_WEB_BASE", "http://localhost:8081")
    jog_code = """
PROGRAM MAIN
VAR
    Axis1 : AXIS_REF;
    Jogger : MC_MoveVelocity;
    bEnable : BOOL;
    rSpeed : REAL := 1500.0;
END_VAR
Jogger(Execute := bEnable, Velocity := rSpeed, Acceleration := 500.0, Axis := Axis1);
END_PROGRAM
"""
    app = AppTest.from_file("app_llamacpp.py", default_timeout=30)
    app.session_state["generated"] = True
    app.session_state["plc_data"] = {
        "code": jog_code,
        "validation": {"score": 100, "status": "passed", "stats": {}, "issues": []},
        "requested_control": {
            "mode": "Absolute Position",
            "requested_velocity": 1500,
            "requested_position": 1000,
            "requested_direction": "forward",
        },
    }
    compiled = {
        "status": "compiled",
        "issues": [],
        "axis_io_map": {"start": 8},
        "axis_register_map": {"position_x10": 0},
        "full_source": "COMPILED JOG",
    }

    with patch("compiler.compile_st_code", return_value=compiled), patch(
        "simulator.run_all_scenarios"
    ) as runtime:
        app.run()
        simulate = next(b for b in app.button if "Run Compile + Simulate" in b.label)
        app = simulate.click().run(timeout=30)

    assert not app.exception
    runtime.assert_not_called()
    assert any("實際生成為 JOG" in error.value for error in app.error)
    deploy = next(b for b in app.button if "部署至 2D Twin" in b.label)
    assert deploy.disabled
