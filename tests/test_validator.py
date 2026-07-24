from validator import validate_st_code


BASE_PROGRAM = """PROGRAM Main
VAR
    Axis1 : AXIS_REF;
    Pwr : MC_Power;
    bEnable : BOOL;
END_VAR
Pwr(Enable := bEnable, Axis := Axis1);
bEnable := {expression};
END_PROGRAM
"""


def test_members_and_named_parameters_are_not_reported_as_variables():
    result = validate_st_code(
        BASE_PROGRAM.format(expression="Axis1.Busy"),
        category="motor_control",
    )

    assert not any(issue["code"] == "E030" for issue in result["issues"])


def test_external_safety_fields_are_rejected():
    result = validate_st_code(
        BASE_PROGRAM.format(expression="Axis1.LimitPos"),
        category="motor_control",
    )

    assert any(
        issue["code"] == "E063" and issue["severity"] == "error"
        for issue in result["issues"]
    )
    assert result["status"] == "needs_review"


def test_multiline_fb_parameters_are_not_variables_or_missing_semicolons():
    code = """PROGRAM MAIN
VAR
    Axis1 : AXIS_REF;
    Jogger : MC_MoveVelocity;
    bEnable : BOOL;
    rVelocity : REAL;
    rAcceleration : REAL;
END_VAR
Jogger(
    Execute := bEnable,
    Velocity := rVelocity,
    Acceleration := rAcceleration,
    Axis := Axis1
);
END_PROGRAM
"""
    result = validate_st_code(code, category="motor_control")

    assert not any(issue["code"] in {"W030", "W050"} for issue in result["issues"])


def test_axis_error_id_requires_dint_receiver():
    code = """PROGRAM MAIN
VAR
    Axis1 : AXIS_REF;
    dwErrorID : DWORD;
END_VAR
dwErrorID := Axis1.ErrorID;
END_PROGRAM
"""
    result = validate_st_code(code, category="motor_control")

    assert any(issue["code"] == "E064" for issue in result["issues"])
    assert result["status"] == "needs_review"
