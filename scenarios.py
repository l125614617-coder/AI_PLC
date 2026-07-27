"""Declarative scenario data for simulator.py's Modbus-driven runtime
validation stage. No execution logic here -- just the drive/assert steps to
run against whatever program compiler.py produced (the LLM's own code, plus
the auto-injected axis adapter -- see compiler.py's AXIS_ADAPTER_IO_MAP).

Universal scenarios apply to every generated program. Motion-specific scenarios
are selected from the generated source so a JOG program is not incorrectly
expected to latch Done, and an absolute-position program is not expected to
stay continuously in velocity.

Each scenario's `steps` is a list of {set: {signal: bool}, wait_s: float,
assert: {signal: bool}} executed in order against compiler.AXIS_ADAPTER_IO_MAP's
fixed coil addresses; `set` may be omitted on the first (pure-assert) step.
"""

SCENARIO_ENABLE_RESPONDS = {
    "name": "enable_responds",
    "description": "Setting the mandated bEnable/start signal makes Enabled go True via MC_Power -- "
                    "universal regardless of which motion FB the generated code calls.",
    "steps": [
        {"assert": {"enabled": False, "error": False}},
        {"set": {"start": True}, "wait_s": 0.3, "assert": {"enabled": True}},
    ],
}

SCENARIO_ESTOP_CUTS_POWER = {
    "name": "estop_cuts_power",
    "description": "E-Stop asserted while running cuts power and flags an error -- this check is "
                    "built into every MC_* motion FB in motion_stubs, so it holds regardless of "
                    "which one the generated code calls.",
    "steps": [
        {"set": {"start": True}, "wait_s": 0.3, "assert": {"enabled": True}},
        {"set": {"estop": True}, "wait_s": 0.3, "assert": {"enabled": False, "error": True}},
    ],
}

SCENARIO_LIMIT_ABORTS_MOTION = {
    "name": "limit_aborts_motion",
    "description": "A limit in the commanded direction aborts motion, zeros velocity, and reports an error.",
    "steps": [
        {"set": {"start": True}, "wait_s": 0.3, "assert": {"enabled": True, "active": True}},
        {
            "set": {"limitpos": True, "limitneg": True},
            "wait_s": 0.3,
            "assert": {"error": True, "aborted": True, "moving": False},
        },
    ],
}

SCENARIO_JOG_RELEASE_STOPS = {
    "name": "jog_release_stops",
    "description": "Releasing the JOG command stops the simulated axis and clears Active.",
    "steps": [
        {"set": {"start": True}, "wait_s": 0.3, "assert": {"active": True, "moving": True}},
        {"set": {"start": False}, "wait_s": 0.3, "assert": {"active": False, "moving": False}},
    ],
}

SCENARIO_ABSOLUTE_REACHES_TARGET = {
    "name": "absolute_reaches_target",
    "description": "An absolute-position command completes and stops at its target.",
    "steps": [
        {"set": {"start": True}, "wait_s": 1.5, "assert": {"done": True, "moving": False}},
    ],
}

SCENARIO_RESET_CLEARS_ERROR = {
    "name": "reset_clears_error",
    "description": "After E-Stop is released, a bResetReq pulse clears the latched axis error.",
    "steps": [
        {"set": {"start": True, "estop": True}, "wait_s": 0.3, "assert": {"error": True}},
        {"set": {"start": False, "estop": False, "reset": False}, "wait_s": 0.1},
        {"set": {"reset": True}, "wait_s": 0.3, "assert": {"error": False}},
        {"set": {"reset": False}},
    ],
}

ALL_SCENARIOS = [
    SCENARIO_ENABLE_RESPONDS,
    SCENARIO_ESTOP_CUTS_POWER,
]


def scenarios_for_code(code: str) -> list:
    """Return only scenarios whose behavioral contract is present in `code`."""
    selected = list(ALL_SCENARIOS)
    upper = (code or "").upper()
    if "MC_MOVEVELOCITY" in upper:
        selected.extend([SCENARIO_LIMIT_ABORTS_MOTION, SCENARIO_JOG_RELEASE_STOPS])
    if "MC_MOVEABSOLUTE" in upper:
        selected.extend([SCENARIO_LIMIT_ABORTS_MOTION, SCENARIO_ABSOLUTE_REACHES_TARGET])
    if "MC_RESET" in upper and "BRESETREQ" in upper:
        selected.append(SCENARIO_RESET_CLEARS_ERROR)
    return selected
