from scenarios import scenarios_for_code


def _names(code: str) -> list[str]:
    return [scenario["name"] for scenario in scenarios_for_code(code)]


def test_jog_scenarios_include_limit_release_and_reset():
    names = _names("MC_Power MC_MoveVelocity MC_Reset bResetReq")

    assert names == [
        "enable_responds",
        "estop_cuts_power",
        "limit_aborts_motion",
        "jog_release_stops",
        "reset_clears_error",
    ]


def test_absolute_scenarios_include_completion_but_not_jog_release():
    names = _names("MC_Power MC_MoveAbsolute")

    assert names == [
        "enable_responds",
        "estop_cuts_power",
        "limit_aborts_motion",
        "absolute_reaches_target",
    ]
