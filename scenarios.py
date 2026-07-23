"""Declarative scenario data for simulator.py's Modbus-driven runtime
validation stage. No execution logic here -- just the drive/assert steps to
run against whatever program compiler.py produced (the LLM's own code, plus
the auto-injected axis adapter -- see compiler.py's AXIS_ADAPTER_IO_MAP).

Scoped down from an earlier 4-scenario design (move-to-position, E-Stop-during-
move, limit-switch-abort, home-sequence) that assumed a specific FB combination
we wrote ourselves. Now that simulator.py deploys the LLM's *actual* generated
code -- which might use MC_MoveAbsolute, MC_MoveVelocity, or skip MC_Home
entirely (it isn't even one of the UI's exposed modes) -- scenarios tied to a
specific motion FB's behavior (Done latching, limit-switch handling) aren't
guaranteed applicable to every generation. The two scenarios below only assert
on MC_Power's behavior, which every generated program must go through
regardless of which motion FB it calls, and on the EStopActive check that's
built into every MC_* stub in motion_stubs -- so they hold universally.

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

ALL_SCENARIOS = [
    SCENARIO_ENABLE_RESPONDS,
    SCENARIO_ESTOP_CUTS_POWER,
]
