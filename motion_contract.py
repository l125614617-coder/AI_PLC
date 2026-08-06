"""Semantic contract checks between requested motion and generated ST code."""

from __future__ import annotations

import re

from st_common import strip_comments


_NUMBER = r"[+-]?(?:(?:\d+(?:\.\d*)?)|(?:\.\d+))(?:[eE][+-]?\d+)?"


def _constants(code: str) -> dict[str, float]:
    values: dict[str, float] = {}
    # IEC typed literals such as REAL#1000.0 are accepted as numeric values.
    literal = rf"(?:REAL|LREAL|INT|DINT)?#?({_NUMBER})"
    for name, value in re.findall(
        rf"\b([A-Za-z_]\w*)\s*:\s*(?:REAL|LREAL|INT|DINT)\s*:=\s*{literal}\s*;",
        code,
        re.IGNORECASE,
    ):
        values[name.lower()] = float(value)
    for name, value in re.findall(
        rf"\b([A-Za-z_]\w*)\s*:=\s*{literal}\s*;",
        code,
        re.IGNORECASE,
    ):
        values[name.lower()] = float(value)
    return values


def _resolve(expression: str | None, constants: dict[str, float]) -> float | None:
    if not expression:
        return None
    value = expression.strip()
    typed = re.fullmatch(rf"(?:REAL|LREAL|INT|DINT)?#?({_NUMBER})", value, re.IGNORECASE)
    if typed:
        return float(typed.group(1))
    identifier = re.fullmatch(r"([A-Za-z_]\w*)", value)
    return constants.get(identifier.group(1).lower()) if identifier else None


def _calls(code: str, block_type: str) -> list[dict]:
    instances = re.findall(
        rf"\b([A-Za-z_]\w*)\s*:\s*{re.escape(block_type)}\s*;",
        code,
        re.IGNORECASE,
    )
    calls = []
    for instance in instances:
        for match in re.finditer(
            rf"\b{re.escape(instance)}\s*\((.*?)\)\s*;",
            code,
            re.IGNORECASE | re.DOTALL,
        ):
            arguments = {
                name.lower(): value.strip()
                for name, value in re.findall(
                    r"\b([A-Za-z_]\w*)\s*:=\s*([^,\)]+)", match.group(1)
                )
            }
            calls.append({"instance": instance, "arguments": arguments})
    return calls


def motion_command_bindings(code: str) -> dict | None:
    """Return writable variable bindings for one MC_MoveAbsolute call.

    Interactive retargeting is offered only when Position and Velocity are
    plain variables. Literal or calculated expressions remain valid for normal
    deployment but cannot be safely overwritten by the injected adapter.
    """
    cleaned = strip_comments(code or "")
    calls = _calls(cleaned, "MC_MoveAbsolute")
    if len(calls) != 1:
        return None
    arguments = calls[0]["arguments"]
    position = arguments.get("position", "")
    velocity = arguments.get("velocity", "")
    if not re.fullmatch(r"[A-Za-z_]\w*", position) or not re.fullmatch(
        r"[A-Za-z_]\w*", velocity
    ):
        return None
    return {
        "mode": "Absolute Position",
        "instance": calls[0]["instance"],
        "position_variable": position,
        "velocity_variable": velocity,
    }


def validate_motion_contract(code: str, expected: dict | None) -> dict:
    """Validate FB selection and numeric targets against the UI request."""
    if not expected:
        return {
            "status": "not_requested",
            "actual_mode": "Unknown",
            "issues": [],
        }

    cleaned = strip_comments(code or "")
    constants = _constants(cleaned)
    absolute_calls = _calls(cleaned, "MC_MoveAbsolute")
    velocity_calls = _calls(cleaned, "MC_MoveVelocity")
    if absolute_calls and velocity_calls:
        actual_mode = "Mixed"
    elif absolute_calls:
        actual_mode = "Absolute Position"
    elif velocity_calls:
        actual_mode = "JOG"
    else:
        actual_mode = "None"

    expected_mode = expected.get("mode") or "Unknown"
    issues = []
    observed_position = None
    observed_velocity = None

    if actual_mode != expected_mode:
        issues.append(
            {
                "code": "MOTION_MODE_MISMATCH",
                "message": f"需求為 {expected_mode}，但生成程式實際為 {actual_mode}。",
            }
        )
    elif expected_mode == "Absolute Position":
        call = absolute_calls[0]
        observed_position = _resolve(call["arguments"].get("position"), constants)
        observed_velocity = _resolve(call["arguments"].get("velocity"), constants)
        target = float(expected.get("requested_position", 0))
        speed = abs(float(expected.get("requested_velocity", 0)))
        if observed_position is None:
            issues.append(
                {
                    "code": "TARGET_POSITION_UNRESOLVED",
                    "message": "無法解析 MC_MoveAbsolute 的 Position 常數。",
                }
            )
        elif abs(observed_position - target) > 1e-6:
            issues.append(
                {
                    "code": "TARGET_POSITION_MISMATCH",
                    "message": f"需求位置為 {target:g}，生成程式使用 {observed_position:g}。",
                }
            )
        if observed_velocity is None:
            issues.append(
                {
                    "code": "TARGET_VELOCITY_UNRESOLVED",
                    "message": "無法解析 MC_MoveAbsolute 的 Velocity 常數。",
                }
            )
        elif abs(abs(observed_velocity) - speed) > 1e-6:
            issues.append(
                {
                    "code": "TARGET_VELOCITY_MISMATCH",
                    "message": f"需求速度為 {speed:g}，生成程式使用 {observed_velocity:g}。",
                }
            )
    elif expected_mode == "JOG":
        call = velocity_calls[0]
        observed_velocity = _resolve(call["arguments"].get("velocity"), constants)
        speed = abs(float(expected.get("requested_velocity", 0)))
        direction = expected.get("requested_direction", "forward")
        signed_speed = -speed if direction == "reverse" else speed
        if observed_velocity is None:
            # A runtime-selectable bReverseReq expression is valid even though
            # its final sign cannot be statically reduced to a constant.
            expression = call["arguments"].get("velocity", "")
            if "reverse" not in expression.lower() and "reverse" not in cleaned.lower():
                issues.append(
                    {
                        "code": "TARGET_VELOCITY_UNRESOLVED",
                        "message": "無法解析 MC_MoveVelocity 的 Velocity 常數或反轉邏輯。",
                    }
                )
        elif abs(observed_velocity - signed_speed) > 1e-6:
            issues.append(
                {
                    "code": "TARGET_VELOCITY_MISMATCH",
                    "message": f"需求速度為 {signed_speed:g}，生成程式使用 {observed_velocity:g}。",
                }
            )

    return {
        "status": "failed" if issues else "passed",
        "expected_mode": expected_mode,
        "actual_mode": actual_mode,
        "observed_position": observed_position,
        "observed_velocity": observed_velocity,
        "issues": issues,
    }
