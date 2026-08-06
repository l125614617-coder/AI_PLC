from motion_contract import motion_command_bindings, validate_motion_contract


ABSOLUTE = """
PROGRAM MAIN
VAR
    Axis1 : AXIS_REF;
    Move : MC_MoveAbsolute;
    bEnable : BOOL;
    rTarget : REAL := 1000.0;
    rSpeed : REAL := 1500.0;
END_VAR
Move(Execute := bEnable, Position := rTarget, Velocity := rSpeed, Axis := Axis1);
END_PROGRAM
"""

JOG = """
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


def _request(**overrides):
    result = {
        "mode": "Absolute Position",
        "requested_position": 1000,
        "requested_velocity": 1500,
        "requested_direction": "forward",
    }
    result.update(overrides)
    return result


def test_absolute_contract_resolves_constant_variables():
    result = validate_motion_contract(ABSOLUTE, _request())

    assert result["status"] == "passed"
    assert result["actual_mode"] == "Absolute Position"
    assert result["observed_position"] == 1000.0
    assert result["observed_velocity"] == 1500.0


def test_jog_generated_for_absolute_request_is_rejected():
    result = validate_motion_contract(JOG, _request())

    assert result["status"] == "failed"
    assert result["actual_mode"] == "JOG"
    assert result["issues"][0]["code"] == "MOTION_MODE_MISMATCH"


def test_wrong_absolute_target_is_rejected():
    result = validate_motion_contract(ABSOLUTE, _request(requested_position=2500))

    assert result["status"] == "failed"
    assert any(i["code"] == "TARGET_POSITION_MISMATCH" for i in result["issues"])


def test_jog_direction_and_speed_are_checked():
    assert validate_motion_contract(
        JOG.replace("1500.0", "-1500.0"),
        _request(mode="JOG", requested_direction="reverse"),
    )["status"] == "passed"
    assert validate_motion_contract(
        JOG,
        _request(mode="JOG", requested_velocity=1000),
    )["status"] == "failed"


def test_comments_do_not_fake_motion_mode():
    code = ABSOLUTE.replace(
        "PROGRAM MAIN", "PROGRAM MAIN\n(* Jogger : MC_MoveVelocity; *)"
    )

    assert validate_motion_contract(code, _request())["actual_mode"] == "Absolute Position"


def test_interactive_bindings_require_plain_target_variables():
    assert motion_command_bindings(ABSOLUTE) == {
        "mode": "Absolute Position",
        "instance": "Move",
        "position_variable": "rTarget",
        "velocity_variable": "rSpeed",
    }
    assert motion_command_bindings(
        ABSOLUTE.replace("Position := rTarget", "Position := 1000.0")
    ) is None
