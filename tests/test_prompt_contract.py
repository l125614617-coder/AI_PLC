from prompt_contract import (
    authoritative_user_prompt,
    prompt_control_conflicts,
    prompt_control_values,
)


ABSOLUTE_CONTROL = {
    "mode": "Absolute Position",
    "requested_velocity": 300,
    "requested_position": 1000,
    "requested_direction": "forward",
}


def test_explicit_prompt_conflicts_are_reported():
    prompt = """- 運行模式: JOG
- 目標速度: 1500 rpm
- 目標位置: 0 mm
- 方向: reverse"""

    conflicts = prompt_control_conflicts(prompt, ABSOLUTE_CONTROL)

    assert conflicts == [
        "運行模式：Prompt=JOG，UI=Absolute Position",
        "目標速度：Prompt=1500，UI=300",
        "目標位置：Prompt=0，UI=1000",
        "方向：Prompt=reverse，UI=forward",
    ]


def test_free_form_prompt_without_control_fields_is_allowed():
    assert prompt_control_conflicts("請提供人工復歸與完成訊號。", ABSOLUTE_CONTROL) == []


def test_authoritative_absolute_contract_is_appended_last():
    result = authoritative_user_prompt("使用者補充需求", ABSOLUTE_CONTROL)

    assert result.startswith("使用者補充需求")
    assert "運行模式: Absolute Position" in result
    assert "目標速度: 300 rpm" in result
    assert "目標位置: 1000 mm" in result
    assert "必須使用 MC_MoveAbsolute，禁止使用 MC_MoveVelocity" in result
    assert result.endswith("</authoritative_motion_contract>")


def test_parser_accepts_full_width_colons_and_decimal_values():
    values = prompt_control_values(
        "運行模式：Absolute Position\n目標速度：300.5 rpm\n目標位置：-20 mm"
    )

    assert values["mode"] == "Absolute Position"
    assert values["requested_velocity"] == "300.5"
    assert values["requested_position"] == "-20"


def test_matching_absolute_prompt_has_no_conflicts():
    prompt = """- 運行模式: Absolute Position
- 目標速度: 300 rpm
- 目標位置: 1000 mm
- 方向: forward"""

    assert prompt_control_conflicts(prompt, ABSOLUTE_CONTROL) == []
