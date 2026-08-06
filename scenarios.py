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

import re
from copy import deepcopy

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

SCENARIO_JOG_COMMAND_CYCLES = {
    "name": "jog_command_cycles",
    "description": "The same runtime accepts a stop followed by a new JOG command.",
    "steps": [
        {
            "set": {"start": True},
            "wait_s": 0.3,
            "assert": {"moving": True},
            "assert_register": {"velocity_x10": {"gt": 0}},
        },
        {"set": {"start": False}, "wait_s": 0.2, "assert": {"moving": False}},
        {
            "set": {"start": True},
            "wait_s": 0.3,
            "assert": {"moving": True},
            "assert_register": {"velocity_x10": {"gt": 0}},
        },
    ],
}

SCENARIO_NEGATIVE_JOG_LIMIT = {
    "name": "negative_jog_limit",
    "description": "Negative JOG produces negative velocity/position and the negative limit aborts it.",
    "steps": [
        {
            "set": {"start": True},
            "wait_s": 0.3,
            "assert": {"moving": True},
            "assert_register": {
                "velocity_x10": {"lt": 0},
                "position_x10": {"lt": 0},
            },
        },
        {
            "set": {"limitneg": True},
            "wait_s": 0.2,
            "assert": {"error": True, "aborted": True, "moving": False},
            "assert_register": {"error_id": 2, "velocity_x10": 0},
        },
    ],
}

SCENARIO_DIRECTION_SWITCH = {
    "name": "direction_switch",
    "description": "A running velocity command can change from positive to negative without redeployment.",
    "steps": [
        {
            "set": {"start": True, "reverse": False},
            "wait_s": 0.3,
            "assert_register": {"velocity_x10": {"gt": 0}},
        },
        {
            "set": {"reverse": True},
            "wait_s": 0.5,
            "assert": {"moving": True},
            "assert_register": {"velocity_x10": {"lt": 0}},
        },
    ],
}

SCENARIO_ABSOLUTE_REACHES_TARGET = {
    "name": "absolute_reaches_target",
    "description": "An absolute-position command completes and stops at its target.",
    "steps": [
        {
            "set": {"start": True},
            "poll_until_s": 15.0,
            "poll_interval_s": 0.1,
            "assert": {"done": True, "moving": False},
            "assert_register": {
                "position_x10": {"equals_register": "target_position_x10"},
                "velocity_x10": 0,
            },
        },
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


def _absolute_scenario(contract: dict | None) -> dict:
    scenario = deepcopy(SCENARIO_ABSOLUTE_REACHES_TARGET)
    if not contract:
        return scenario
    position = contract.get("observed_position")
    velocity = contract.get("observed_velocity")
    if position is None or velocity is None or abs(float(velocity)) < 1e-9:
        return scenario
    # The virtual FB integrates with a 0.01 s model step while OpenPLC runs a
    # 20 ms task, so wall time is about 2 * distance / velocity. Add margin for
    # startup/HTTP scheduling and cap pathological requests at 30 seconds.
    estimated = 2.5 * abs(float(position)) / abs(float(velocity)) + 2.0
    scenario["steps"][0]["poll_until_s"] = min(30.0, max(2.0, estimated))
    return scenario


def scenarios_for_code(code: str, contract: dict | None = None) -> list:
    """Return only scenarios whose behavioral contract is present in `code`."""
    selected = list(ALL_SCENARIOS)
    upper = (code or "").upper()
    if "MC_MOVEVELOCITY" in upper:
        negative_velocity = bool(
            re.search(r":\s*REAL\s*:=\s*-", code, re.IGNORECASE)
        )
        if negative_velocity:
            selected.extend([SCENARIO_NEGATIVE_JOG_LIMIT, SCENARIO_JOG_RELEASE_STOPS])
        else:
            selected.extend([
                SCENARIO_LIMIT_ABORTS_MOTION,
                SCENARIO_JOG_RELEASE_STOPS,
                SCENARIO_JOG_COMMAND_CYCLES,
            ])
        if "BREVERSEREQ" in upper:
            selected.append(SCENARIO_DIRECTION_SWITCH)
    if "MC_MOVEABSOLUTE" in upper:
        selected.extend([SCENARIO_LIMIT_ABORTS_MOTION, _absolute_scenario(contract)])
    if "MC_RESET" in upper and "BRESETREQ" in upper:
        selected.append(SCENARIO_RESET_CLEARS_ERROR)
    return selected
