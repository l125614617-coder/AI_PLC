from unittest.mock import patch

from streamlit.testing.v1 import AppTest


BROKEN = """### CODE
```st
PROGRAM MAIN
VAR
    Axis1 : AXIS_REF;
    bEnable : BOOL;
    dwErrorID : DWORD;
END_VAR
dwErrorID := Axis1.ErrorID;
END_PROGRAM
```
### VARIABLES
Name | Type | Direction | Description
---|---|---|---
dwErrorID | DWORD | output | broken
### EXPLANATION
- test
### WARNINGS
- test
"""

REPAIRED = BROKEN.replace("dwErrorID : DWORD", "dwErrorID : DINT").replace(
    "dwErrorID | DWORD",
    "dwErrorID | DINT",
)


def _response(text, reasoning_tokens):
    return {
        "raw_text": text,
        "thinking": "Codex 推理完成。",
        "model": "gpt-5.6-sol",
        "usage": {
            "input_tokens": 10,
            "output_tokens": 20,
            "reasoning_output_tokens": reasoning_tokens,
        },
    }


def test_codex_ui_repairs_real_compile_failure_before_returning(monkeypatch):
    monkeypatch.setenv("OPENPLC_WEB_BASE", "http://localhost:8081")

    with patch(
        "codex_provider.generate_with_codex",
        side_effect=[_response(BROKEN, 3), _response(REPAIRED, 4)],
    ) as generate:
        app = AppTest.from_file("app_codex.py", default_timeout=30).run()
        generate_button = next(
            button for button in app.button if "Generate ST Code" in button.label
        )
        app = generate_button.click().run(timeout=30)

    assert not app.exception
    assert generate.call_count == 2
    assert any("共 2 次生成嘗試" in message.value for message in app.success)
    assert app.code[-1].value.find("dwErrorID : DINT") >= 0
