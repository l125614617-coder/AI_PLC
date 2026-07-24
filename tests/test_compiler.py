"""Tests for compiler.py's compile-check stage. Requires the OpenPLC_v3 install
under MSYS2 (see the M2 smoke test) to be present, since compiler.py uses its
bundled native iec2c.exe; skipped automatically otherwise so the suite still
runs on machines without that setup.
"""

from pathlib import Path

import pytest

from compiler import compile_st_code, iec2c_available, _detect_axis_variable, AXIS_ADAPTER_IO_MAP

FIXTURES = Path(__file__).parent / "fixtures"

pytestmark = pytest.mark.skipif(not iec2c_available(), reason="iec2c.exe is not available in this environment")


def test_compliant_program_main_compiles_clean():
    code = """
PROGRAM MAIN
VAR
    Axis1 : AXIS_REF;
    Pwr   : MC_Power;
    Mover : MC_MoveAbsolute;
END_VAR
Pwr(Enable := TRUE, Axis := Axis1);
Mover(Execute := TRUE, Position := 100.0, Velocity := 50.0, Axis := Axis1);
END_PROGRAM
"""
    result = compile_st_code(code)
    assert result["status"] == "compiled"
    assert result["issues"] == []
    assert result["wrapper_source"] == ""
    # this code declares 'Axis1 : AXIS_REF;', so the adapter should auto-inject
    assert result["axis_io_map"] == AXIS_ADAPTER_IO_MAP


def test_axis_variable_detected_regardless_of_name():
    """The whole point of putting status on the axis (not the FB instance) is
    that the harness never needs to know what the LLM called its variables --
    verify detection works for an arbitrary, non-'Axis1' name."""
    code = """
PROGRAM MAIN
VAR
    MyRobotArmAxis : AXIS_REF;
    Pwr            : MC_Power;
    Mover          : MC_MoveAbsolute;
END_VAR
Pwr(Enable := TRUE, Axis := MyRobotArmAxis);
Mover(Execute := TRUE, Position := 10.0, Velocity := 5.0, Axis := MyRobotArmAxis);
END_PROGRAM
"""
    assert _detect_axis_variable(code) == "MyRobotArmAxis"
    result = compile_st_code(code)
    assert result["status"] == "compiled"
    assert result["axis_io_map"] == AXIS_ADAPTER_IO_MAP
    assert "MyRobotArmAxis.EStopActive" in result["full_source"]


def test_program_without_axis_ref_compiles_but_has_no_io_map():
    """Code that doesn't use the shared AXIS_REF convention at all should still
    compile-check fine (Stage 2 doesn't require it), but there's nothing for
    simulator.py to observe over Modbus -- axis_io_map must be None so callers
    know to skip the runtime-simulation stage rather than silently no-op it."""
    code = """
PROGRAM MAIN
VAR
    counter : DINT;
END_VAR
counter := counter + 1;
END_PROGRAM
"""
    result = compile_st_code(code)
    assert result["status"] == "compiled"
    assert result["axis_io_map"] is None


def test_benable_bridged_after_llms_own_declarations():
    """bEnable is the mandated generic start signal (DEFAULT_SYSTEM_PROMPT
    requires this exact name). The bridge statement must land after the LLM's
    OWN END_VAR (which now follows our injected VAR block in the adapted
    source) -- inserting it any earlier would place an executable statement
    before a later VAR block, which is invalid ST and would fail to compile."""
    code = """
PROGRAM MAIN
VAR
    AxisRef : AXIS_REF;
    Pwr     : MC_Power;
    Mover   : MC_MoveAbsolute;
    bEnable : BOOL;
    rTargetPos : REAL;
END_VAR
Pwr(Enable := bEnable, Axis := AxisRef);
Mover(Execute := bEnable, Position := rTargetPos, Velocity := 50.0, Axis := AxisRef);
END_PROGRAM
"""
    result = compile_st_code(code)
    assert result["status"] == "compiled"
    assert result["axis_io_map"]["start"] == AXIS_ADAPTER_IO_MAP["start"]
    assert "bEnable := AdpStart;" in result["full_source"]


def test_initialized_benable_is_still_bridged_to_modbus_start():
    """LLMs commonly initialize BOOL inputs explicitly. The adapter must still
    recognize bEnable and override its initial value from the Modbus start coil
    every scan."""
    code = """
PROGRAM MAIN
VAR
    Axis1  : AXIS_REF;
    Pwr    : MC_Power;
    bEnable: BOOL := FALSE;
END_VAR
Pwr(Enable := bEnable, Axis := Axis1);
END_PROGRAM
"""
    result = compile_st_code(code)

    assert result["status"] == "compiled"
    assert result["axis_io_map"]["start"] == AXIS_ADAPTER_IO_MAP["start"]
    assert "bEnable := AdpStart;" in result["full_source"]


def test_chinese_comments_dont_cause_cascading_bogus_errors():
    """Discovered live: this matiec build's error recovery gets badly confused
    by non-ASCII (Chinese) text inside comments -- a genuinely broken program
    (empty ELSE branch, no statement) was reported as a dozen unrelated
    'invalid variable(s) declaration' errors purely because of Chinese
    comments elsewhere in the file. compiler.py now blanks comments before
    compiling (iec2c doesn't need them), so the real error should surface
    cleanly even with Chinese comments present."""
    code = """
PROGRAM MAIN
VAR
    Axis1 : AXIS_REF; // 軸參考物件
    Pwr   : MC_Power; // 電源控制
    Rst   : MC_Reset; // 復歸控制
    bEnable : BOOL; // 總啟動訊號
END_VAR
// 電源管理
Pwr(Enable := bEnable, Axis := Axis1);
IF bEnable THEN
    Rst(Execute := TRUE, Axis := Axis1);
ELSE
    // 若無復歸請求，則不強制觸發
END_IF;
END_PROGRAM
"""
    result = compile_st_code(code)
    assert result["status"] == "compile_failed"
    assert len(result["issues"]) == 1
    assert "ELSE" in result["issues"][0]["message"]


def test_noncompliant_function_block_gets_synthesized_wrapper():
    code = """
FUNCTION_BLOCK MyMotionLogic
VAR
    Axis1 : AXIS_REF;
    Pwr   : MC_Power;
    Mover : MC_MoveAbsolute;
END_VAR
Pwr(Enable := TRUE, Axis := Axis1);
Mover(Execute := TRUE, Position := 100.0, Velocity := 50.0, Axis := Axis1);
END_FUNCTION_BLOCK
"""
    result = compile_st_code(code)
    assert result["status"] == "compiled"
    assert "PROGRAM MAIN" in result["wrapper_source"]
    assert "MyMotionLogic" in result["wrapper_source"]


def test_broken_syntax_reports_errors_at_remapped_lines():
    code = """
PROGRAM MAIN
VAR
    Axis1 : AXIS_REF
    Pwr   : MC_Power;
END_VAR
Pwr(Enable := TRUE, Axis := Axis1)
END_PROGRAM
"""
    result = compile_st_code(code)
    assert result["status"] == "compile_failed"
    assert len(result["issues"]) >= 2
    assert all(i["severity"] == "error" for i in result["issues"])
    # both errors should map back into the 8-line snippet we handed in, not
    # into the concatenated motion-stub library that precedes it
    assert all(i["in_generated_code"] for i in result["issues"])
    assert all(1 <= i["line"] <= code.count("\n") + 1 for i in result["issues"])


def test_real_captured_llm_output_surfaces_real_compile_errors():
    """This sample was captured from a live qwen3.5:9b generation against
    app.py's actual DEFAULT_SYSTEM_PROMPT. It uses FUNCTION_BLOCK (not PROGRAM
    MAIN, exercising wrapper synthesis) and contains a real bug the model
    introduced: a stray C-style '*/' comment-closer inside an IEC '(* *)'
    block, which validator.py's regex heuristics do not reliably catch but a
    real compiler does -- this is the pipeline's core value proposition."""
    code = (FIXTURES / "captured_llm_output.st").read_text(encoding="utf-8")
    result = compile_st_code(code)
    assert result["status"] == "compile_failed"
    assert len(result["issues"]) > 0
    assert any(i["in_generated_code"] for i in result["issues"])


def test_empty_code_returns_wrapper_synthesis_failed():
    result = compile_st_code("")
    assert result["status"] == "wrapper_synthesis_failed"


def test_no_pou_found_returns_wrapper_synthesis_failed():
    result = compile_st_code("// just a comment, no POU here")
    assert result["status"] == "wrapper_synthesis_failed"
