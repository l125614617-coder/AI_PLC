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
