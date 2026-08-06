"""Keep editable user prompts aligned with the authoritative UI motion request."""

from __future__ import annotations

import re


_NUMBER = r"[+-]?(?:(?:\d+(?:\.\d*)?)|(?:\.\d+))"


def _match(prompt: str, pattern: str) -> str | None:
    found = re.search(pattern, prompt or "", re.IGNORECASE)
    return found.group(1).strip() if found else None


def prompt_control_values(prompt: str) -> dict:
    """Extract control values only when the editable prompt states them explicitly."""
    return {
        "mode": _match(prompt, r"運行模式\s*[:：]\s*(JOG|Absolute\s+Position)"),
        "requested_velocity": _match(
            prompt, rf"目標速度\s*[:：]\s*({_NUMBER})\s*(?:rpm)?"
        ),
        "requested_position": _match(
            prompt, rf"目標位置\s*[:：]\s*({_NUMBER})\s*(?:mm)?"
        ),
        "requested_direction": _match(
            prompt, r"方向\s*[:：]\s*(forward|reverse)"
        ),
    }


def prompt_control_conflicts(prompt: str, control: dict) -> list[str]:
    """Describe explicit prompt/UI conflicts; omitted fields remain valid free-form text."""
    stated = prompt_control_values(prompt)
    conflicts: list[str] = []
    mode = stated["mode"]
    expected_mode = str(control.get("mode", ""))
    if mode and mode.casefold() != expected_mode.casefold():
        conflicts.append(f"運行模式：Prompt={mode}，UI={expected_mode}")

    for key, label in (
        ("requested_velocity", "目標速度"),
        ("requested_position", "目標位置"),
    ):
        value = stated[key]
        if value is not None and abs(float(value) - float(control.get(key, 0))) > 1e-6:
            conflicts.append(f"{label}：Prompt={float(value):g}，UI={float(control.get(key, 0)):g}")

    direction = stated["requested_direction"]
    expected_direction = str(control.get("requested_direction", ""))
    if direction and direction.casefold() != expected_direction.casefold():
        conflicts.append(f"方向：Prompt={direction}，UI={expected_direction}")
    return conflicts


def authoritative_user_prompt(prompt: str, control: dict) -> str:
    """Append a machine-authored contract after editable text so the model has one authority."""
    mode = control["mode"]
    required_block = "MC_MoveAbsolute" if mode == "Absolute Position" else "MC_MoveVelocity"
    forbidden_block = "MC_MoveVelocity" if mode == "Absolute Position" else "MC_MoveAbsolute"
    return (
        f"{(prompt or '').rstrip()}\n\n"
        "<authoritative_motion_contract>\n"
        "以下值來自本次 UI 快照，優先於上方任何衝突文字，不得自行改變：\n"
        f"- 運行模式: {mode}\n"
        f"- 目標速度: {control['requested_velocity']} rpm\n"
        f"- 目標位置: {control['requested_position']} mm\n"
        f"- 方向: {control['requested_direction']}\n"
        f"- 必須使用 {required_block}，禁止使用 {forbidden_block}\n"
        "- Position 與 Velocity 必須使用具有上述初值的一般變數，供驗證與 Twin 互動寫入。\n"
        "</authoritative_motion_contract>"
    )
