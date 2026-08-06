"""Stage 2 of the validation pipeline: real IEC 61131-3 compilation via matiec's
iec2c. Unlike validator.py's regex heuristics, this catches actual syntax/type
errors. Runs the precompiled native Windows iec2c.exe directly (bundled with
the OpenPLC_v3 install used for the simulate/deploy stage in simulator.py) --
no WSL, no separate build step.

The LLM's generated POU name/type isn't constrained today, but iec2c requires
a CONFIGURATION wrapping exactly one PROGRAM on one task. compile_st_code()
handles both cases: a compliant 'PROGRAM MAIN' is used directly; anything else
gets a trivial synthesized wrapper (best-effort, MVP: no argument wiring from
the variable table yet -- see _synthesize_wrapper).
"""

import os
import re
import subprocess
import tempfile
from pathlib import Path

from st_common import extract_pous, strip_comments
from motion_contract import motion_command_bindings

MOTION_STUBS_DIR = Path(__file__).parent / "motion_stubs"
MOTION_STUB_FILES = [
    "AxisTypes.st",
    "MC_Power.st",
    "MC_Reset.st",
    "MC_Stop.st",
    "MC_MoveAbsolute.st",
    "MC_MoveVelocity.st",
    "MC_Home.st",
]

# Fixed location set up during the M0/M2 feasibility work: OpenPLC_v3 installed
# under the MSYS2 home directory, whose bundled iec2c.exe is a self-contained
# native Windows binary (only needs its two sibling DLLs, no MSYS2 shell).
OPENPLC_DIR = Path(f"C:/msys64/home/{os.environ.get('USERNAME', '')}/OpenPLC_v3")
IEC2C_EXE = OPENPLC_DIR / "webserver" / "iec2c.exe"
STD_LIB_DIR = OPENPLC_DIR / "utils" / "matiec_src" / "lib"
IEC2C_FLAGS = ["-f", "-l", "-p", "-r", "-R", "-a"]

_ISSUE_PATTERN = re.compile(
    r"^(?P<file>[^:\n]+):(?P<line1>\d+)-(?P<col1>\d+)\.\.(?P<line2>\d+)-(?P<col2>\d+):\s*"
    r"(?P<severity>error|warning):\s*(?P<message>.*)$",
    re.MULTILINE,
)


def iec2c_available() -> bool:
    return IEC2C_EXE.is_file()


def _load_motion_stubs() -> str:
    return "\n".join((MOTION_STUBS_DIR / name).read_text(encoding="utf-8") for name in MOTION_STUB_FILES)


# Fixed contract between the injected adapter and simulator.py/scenarios.py:
# axis status is exposed on these coils (readable), and these signals can be
# externally driven to inject fake I/O (writable) -- see the M2 smoke test
# finding that %IX/%IW are read-only over Modbus, so everything here is %QX.
# 'start' drives the LLM's own required bEnable signal (see DEFAULT_SYSTEM_PROMPT
# in app.py, which mandates this exact name) -- without it there is no generic
# way to kick off whatever control logic the LLM wrote. Absolute programs with
# plain Position/Velocity variables also receive an apply pulse plus two command
# registers so Twin can safely re-arm and retarget the same deployed program.
AXIS_ADAPTER_IO_MAP = {
    "busy": 0, "done": 1, "error": 2, "enabled": 3,
    "estop": 4, "limitpos": 5, "limitneg": 6, "homeswitch": 7,
    "start": 8, "active": 9, "aborted": 10, "invelocity": 11,
    "reset": 12, "moving": 13, "reverse": 14, "apply_target": 15,
    "soft_limits_enable": 16, "softlimitpos": 17, "softlimitneg": 18,
}
AXIS_ADAPTER_REGISTER_MAP = {
    "position_x10": 0,
    "velocity_x10": 1,
    "target_position_x10": 2,
    "target_velocity_x10": 3,
    "error_id": 4,
    "axis_state": 5,
}
AXIS_ADAPTER_COMMAND_MAP = {
    "apply_target": AXIS_ADAPTER_IO_MAP["apply_target"],
    "command_position_x10": 6,
    "command_velocity_x10": 7,
    "soft_limit_negative_x10": 8,
    "soft_limit_positive_x10": 9,
    "soft_limits_enable": AXIS_ADAPTER_IO_MAP["soft_limits_enable"],
}

_AXIS_VAR_PATTERN = re.compile(r"(\w+)\s*:\s*AXIS_REF\s*;", re.IGNORECASE)
_BENABLE_PATTERN = re.compile(
    r"\bbEnable\s*:\s*BOOL(?:\s*:=\s*[^;]+)?\s*;",
    re.IGNORECASE,
)
_BRESET_PATTERN = re.compile(
    r"\bbResetReq\s*:\s*BOOL(?:\s*:=\s*[^;]+)?\s*;",
    re.IGNORECASE,
)
_BREVERSE_PATTERN = re.compile(
    r"\bbReverseReq\s*:\s*BOOL(?:\s*:=\s*[^;]+)?\s*;",
    re.IGNORECASE,
)
_PROGRAM_MAIN_HEADER = re.compile(r"\bPROGRAM\s+MAIN\b", re.IGNORECASE)
_END_VAR_PATTERN = re.compile(r"\bEND_VAR\b", re.IGNORECASE)
_END_PROGRAM_PATTERN = re.compile(r"\bEND_PROGRAM\b", re.IGNORECASE)


def _detect_axis_variable(code: str) -> str:
    """Find the name of the AXIS_REF-typed variable the LLM declared, if any.
    Axis-name-independent by design (mirrors the AXIS_REF status-on-the-axis
    principle from motion_stubs) -- works regardless of what the LLM called it."""
    m = _AXIS_VAR_PATTERN.search(code or "")
    return m.group(1) if m else None


def _inject_axis_adapter(
    code: str, axis_var: str, command_bindings: dict | None = None
) -> str:
    """Text-surgery: insert a located-I/O VAR block right after 'PROGRAM MAIN'
    and bridging assignments right before 'END_PROGRAM' (plus one right after
    the header, for bEnable -- see below), so the LLM's own (unmodified)
    control logic becomes observable/drivable over Modbus via
    AXIS_ADAPTER_IO_MAP's fixed coil addresses -- regardless of what the LLM
    named its axis variable. This only works because IEC 61131-3 allows
    multiple VAR blocks per POU and because we operate on the actual POU body
    (not a wrapper instantiating it, since PROGRAMs can't be instantiated like
    FUNCTION_BLOCKs).

    bEnable (mandated by DEFAULT_SYSTEM_PROMPT to be exactly this name) is
    bridged at the TOP of the body, before the LLM's own statements run, so
    the harness-driven value takes effect the same scan it's written -- the
    axis status/fault bridging happens at the END, after the LLM's logic has
    had a chance to update the axis for this scan."""
    command_vars = ""
    if command_bindings:
        command_vars = f"""
    AdpApplyTarget        AT %QX0.{AXIS_ADAPTER_IO_MAP['apply_target']} : BOOL;
    AdpCommandPositionX10 AT %QW{AXIS_ADAPTER_COMMAND_MAP['command_position_x10']} : INT;
    AdpCommandVelocityX10 AT %QW{AXIS_ADAPTER_COMMAND_MAP['command_velocity_x10']} : INT;
"""
    var_block = f"""
VAR
    AdpEStop      AT %QX0.{AXIS_ADAPTER_IO_MAP['estop']} : BOOL;
    AdpLimitPos   AT %QX0.{AXIS_ADAPTER_IO_MAP['limitpos']} : BOOL;
    AdpLimitNeg   AT %QX0.{AXIS_ADAPTER_IO_MAP['limitneg']} : BOOL;
    AdpHomeSwitch AT %QX0.{AXIS_ADAPTER_IO_MAP['homeswitch']} : BOOL;
    AdpBusy       AT %QX0.{AXIS_ADAPTER_IO_MAP['busy']} : BOOL;
    AdpDone       AT %QX0.{AXIS_ADAPTER_IO_MAP['done']} : BOOL;
    AdpError      AT %QX0.{AXIS_ADAPTER_IO_MAP['error']} : BOOL;
    AdpEnabled    AT %QX0.{AXIS_ADAPTER_IO_MAP['enabled']} : BOOL;
    AdpStart      AT %QX0.{AXIS_ADAPTER_IO_MAP['start']} : BOOL;
    AdpActive     AT %QX0.{AXIS_ADAPTER_IO_MAP['active']} : BOOL;
    AdpAborted    AT %QX0.{AXIS_ADAPTER_IO_MAP['aborted']} : BOOL;
    AdpInVelocity AT %QX0.{AXIS_ADAPTER_IO_MAP['invelocity']} : BOOL;
    AdpReset      AT %QX0.{AXIS_ADAPTER_IO_MAP['reset']} : BOOL;
    AdpMoving     AT %QX0.{AXIS_ADAPTER_IO_MAP['moving']} : BOOL;
    AdpReverse    AT %QX0.{AXIS_ADAPTER_IO_MAP['reverse']} : BOOL;
    AdpSoftLimitsEnable AT %QX0.{AXIS_ADAPTER_IO_MAP['soft_limits_enable']} : BOOL;
    AdpSoftLimitPos     AT %QX0.{AXIS_ADAPTER_IO_MAP['softlimitpos']} : BOOL;
    AdpSoftLimitNeg     AT %QX0.{AXIS_ADAPTER_IO_MAP['softlimitneg']} : BOOL;
    AdpPositionX10       AT %QW0 : INT;
    AdpVelocityX10       AT %QW1 : INT;
    AdpTargetPositionX10 AT %QW2 : INT;
    AdpTargetVelocityX10 AT %QW3 : INT;
    AdpErrorID           AT %QW4 : INT;
    AdpAxisState         AT %QW5 : INT;
    AdpSoftLimitNegativeX10 AT %QW{AXIS_ADAPTER_COMMAND_MAP['soft_limit_negative_x10']} : INT;
    AdpSoftLimitPositiveX10 AT %QW{AXIS_ADAPTER_COMMAND_MAP['soft_limit_positive_x10']} : INT;
{command_vars.rstrip()}
END_VAR
"""
    input_bridge = f"""
{axis_var}.EStopActive := AdpEStop;
{axis_var}.LimitPos := AdpLimitPos OR (AdpSoftLimitsEnable AND
    ({axis_var}.Position >= INT_TO_REAL(AdpSoftLimitPositiveX10) / 10.0));
{axis_var}.LimitNeg := AdpLimitNeg OR (AdpSoftLimitsEnable AND
    ({axis_var}.Position <= INT_TO_REAL(AdpSoftLimitNegativeX10) / 10.0));
{axis_var}.HomeSwitch := AdpHomeSwitch;
"""
    bridge_stmts = f"""
AdpSoftLimitPos := AdpSoftLimitsEnable AND
    ({axis_var}.Position >= INT_TO_REAL(AdpSoftLimitPositiveX10) / 10.0);
AdpSoftLimitNeg := AdpSoftLimitsEnable AND
    ({axis_var}.Position <= INT_TO_REAL(AdpSoftLimitNegativeX10) / 10.0);
AdpBusy := {axis_var}.Busy;
AdpDone := {axis_var}.Done;
AdpError := {axis_var}.Error;
AdpEnabled := {axis_var}.Enabled;
AdpActive := {axis_var}.Active;
AdpAborted := {axis_var}.CommandAborted;
AdpInVelocity := {axis_var}.InVelocity;
AdpMoving := {axis_var}.Velocity <> 0.0;
AdpPositionX10 := REAL_TO_INT({axis_var}.Position * 10.0);
AdpVelocityX10 := REAL_TO_INT({axis_var}.Velocity * 10.0);
AdpTargetPositionX10 := REAL_TO_INT({axis_var}.TargetPosition * 10.0);
AdpTargetVelocityX10 := REAL_TO_INT({axis_var}.TargetVelocity * 10.0);
AdpErrorID := DINT_TO_INT({axis_var}.ErrorID);
AdpAxisState := {axis_var}.AxisState;
"""
    code = _PROGRAM_MAIN_HEADER.sub(lambda m: m.group(0) + var_block, code, count=1)

    if _BENABLE_PATTERN.search(code):
        # Must land after the LAST END_VAR (i.e. after all declarations,
        # including the LLM's own VAR block which now follows ours) -- an
        # executable statement any earlier would sit before a later VAR
        # block, which is invalid ST.
        matches = list(_END_VAR_PATTERN.finditer(code))
        last_end = matches[-1].end()
        code = code[:last_end] + "\nbEnable := AdpStart;" + code[last_end:]

    if _BRESET_PATTERN.search(code):
        matches = list(_END_VAR_PATTERN.finditer(code))
        last_end = matches[-1].end()
        code = code[:last_end] + "\nbResetReq := AdpReset;" + code[last_end:]

    if _BREVERSE_PATTERN.search(code):
        matches = list(_END_VAR_PATTERN.finditer(code))
        last_end = matches[-1].end()
        code = code[:last_end] + "\nbReverseReq := AdpReverse;" + code[last_end:]

    matches = list(_END_VAR_PATTERN.finditer(code))
    last_end = matches[-1].end()
    code = code[:last_end] + input_bridge + code[last_end:]

    if command_bindings:
        matches = list(_END_VAR_PATTERN.finditer(code))
        last_end = matches[-1].end()
        target_bridge = f"""
IF AdpApplyTarget THEN
    {command_bindings['position_variable']} := INT_TO_REAL(AdpCommandPositionX10) / 10.0;
    {command_bindings['velocity_variable']} := INT_TO_REAL(AdpCommandVelocityX10) / 10.0;
END_IF;"""
        code = code[:last_end] + target_bridge + code[last_end:]

    code = _END_PROGRAM_PATTERN.sub(lambda m: bridge_stmts + m.group(0), code, count=1)
    return code


def _synthesize_wrapper(pou_name: str) -> str:
    """Wrap a non-compliant FUNCTION_BLOCK/FUNCTION in a trivial calling PROGRAM MAIN.
    MVP: calls it with no arguments wired -- iec2c will report unresolved
    VAR_INPUT/VAR_OUTPUT as its own errors, which is an acceptable outcome
    (the LLM should have followed the PROGRAM MAIN convention; this wrapper's
    job is just to make *some* compile attempt possible, not to guess wiring)."""
    return f"""
PROGRAM MAIN
VAR
    Inst : {pou_name};
END_VAR
Inst();
END_PROGRAM
"""


def _build_source(code: str) -> tuple:
    """Returns (full_source, code_start_line, code_end_line, wrapper_source, main_name, axis_io_map)."""
    # Blank comments before anything else -- this matiec build's error recovery
    # gets badly confused by non-ASCII (e.g. Chinese) comment text, producing
    # cascades of unrelated errors instead of the real one. iec2c doesn't need
    # comments, so this sidesteps the whole issue. Preserves line count/newlines,
    # so the code_start_line/code_end_line remapping below stays accurate.
    code = strip_comments(code)
    stubs = _load_motion_stubs()
    pous = extract_pous(code)
    program_pous = [p for p in pous if p["kind"] == "PROGRAM"]

    wrapper_source = ""
    axis_io_map = None
    axis_command_map = None
    if program_pous:
        main_name = program_pous[0]["name"]
        # Only attempt adapter injection against the LLM's own PROGRAM (not the
        # synthesized wrapper case) -- see _inject_axis_adapter's docstring for
        # why this needs to operate on the actual POU body.
        axis_var = _detect_axis_variable(code)
        if axis_var:
            bindings = motion_command_bindings(code)
            code = _inject_axis_adapter(code, axis_var, bindings)
            axis_io_map = dict(AXIS_ADAPTER_IO_MAP)
            if bindings:
                axis_command_map = dict(AXIS_ADAPTER_COMMAND_MAP)
    elif pous:
        main_name = "MAIN"
        wrapper_source = _synthesize_wrapper(pous[0]["name"])
    else:
        main_name = None

    config = f"""
CONFIGURATION Config0
RESOURCE Res0 ON PLC
    TASK task0(INTERVAL := T#20ms, PRIORITY := 0);
    PROGRAM instance0 WITH task0 : {main_name};
END_RESOURCE
END_CONFIGURATION
"""

    stubs_lines = stubs.count("\n") + 1
    code_start_line = stubs_lines + 1  # +1 for the join newline before `code`
    code_end_line = code_start_line + code.count("\n")

    parts = [stubs, code]
    if wrapper_source:
        parts.append(wrapper_source)
    if main_name:
        parts.append(config)
    full_source = "\n".join(parts)

    return (
        full_source,
        code_start_line,
        code_end_line,
        wrapper_source,
        main_name,
        axis_io_map,
        axis_command_map,
    )


def _parse_issues(compiler_output: str, code_start_line: int, code_end_line: int) -> list:
    issues = []
    for m in _ISSUE_PATTERN.finditer(compiler_output or ""):
        line1 = int(m.group("line1"))
        in_generated_code = code_start_line <= line1 <= code_end_line
        issues.append({
            "severity": m.group("severity"),
            "message": m.group("message").strip(),
            "line": (line1 - code_start_line + 1) if in_generated_code else line1,
            "in_generated_code": in_generated_code,
        })
    return issues


def compile_st_code(code: str, timeout_s: int = 30) -> dict:
    """Compile `code` (the LLM's ### CODE section) against the motion-control
    stub library via matiec's iec2c.exe (native Windows binary, no subprocess
    bridge into another OS).

    Returns {status, stdout, stderr, issues, wrapper_source, axis_io_map,
    axis_register_map, axis_command_map, full_source}
    where status is one of:
    'compiled' | 'compile_failed' | 'wrapper_synthesis_failed' | 'iec2c_unavailable'.
    `axis_io_map` and `axis_register_map` are fixed Modbus mappings when an
    AXIS_REF variable was detected and the adapter was injected, else None.
    `full_source` is the exact source that was compiled (stub library + adapted code +
    wrapper/config) -- simulator.py deploys this exact text, never recomputes it, so
    what got compile-checked is guaranteed to be what gets deployed.
    """
    if not (code or "").strip():
        return {
            "status": "wrapper_synthesis_failed",
            "stdout": "", "stderr": "",
            "issues": [{"severity": "error", "message": "No code to compile.", "line": None, "in_generated_code": False}],
            "wrapper_source": "", "axis_io_map": None,
            "axis_register_map": None, "axis_command_map": None,
            "full_source": "",
        }

    if not iec2c_available():
        return {
            "status": "iec2c_unavailable",
            "stdout": "", "stderr": "",
            "issues": [{"severity": "error", "message": f"iec2c.exe not found at {IEC2C_EXE} -- cannot run the compile check.", "line": None, "in_generated_code": False}],
            "wrapper_source": "", "axis_io_map": None,
            "axis_register_map": None, "axis_command_map": None,
            "full_source": "",
        }

    (
        full_source,
        code_start_line,
        code_end_line,
        wrapper_source,
        main_name,
        axis_io_map,
        axis_command_map,
    ) = _build_source(code)

    if main_name is None:
        return {
            "status": "wrapper_synthesis_failed",
            "stdout": "", "stderr": "",
            "issues": [{"severity": "error",
                        "message": "Could not find any PROGRAM/FUNCTION_BLOCK/FUNCTION declaration in the generated ST code.",
                        "line": None, "in_generated_code": False}],
            "wrapper_source": "", "axis_io_map": None,
            "axis_register_map": None, "axis_command_map": None,
            "full_source": "",
        }

    tmp_dir = Path(tempfile.mkdtemp(prefix="plcassist_compile_"))
    try:
        st_path = tmp_dir / "program.st"
        st_path.write_text(full_source, encoding="utf-8", newline="\n")

        cmd = [str(IEC2C_EXE), *IEC2C_FLAGS, "-I", str(STD_LIB_DIR), "program.st"]

        try:
            result = subprocess.run(cmd, cwd=str(tmp_dir), capture_output=True, text=True, timeout=timeout_s)
        except Exception as e:  # subprocess.TimeoutExpired, OSError, etc.
            return {
                "status": "compile_failed",
                "stdout": "", "stderr": str(e),
                "issues": [{"severity": "error", "message": f"Compile invocation failed: {e}", "line": None, "in_generated_code": False}],
                "wrapper_source": wrapper_source, "axis_io_map": None,
                "axis_register_map": None, "axis_command_map": None,
                "full_source": full_source,
            }

        combined_output = result.stdout + result.stderr
        issues = _parse_issues(combined_output, code_start_line, code_end_line)
        has_errors = result.returncode != 0 or any(i["severity"] == "error" for i in issues)

        return {
            "status": "compile_failed" if has_errors else "compiled",
            "stdout": result.stdout,
            "stderr": result.stderr,
            "issues": issues,
            "wrapper_source": wrapper_source,
            "axis_io_map": axis_io_map if not has_errors else None,
            "axis_register_map": (
                dict(AXIS_ADAPTER_REGISTER_MAP)
                if axis_io_map is not None and not has_errors
                else None
            ),
            "axis_command_map": axis_command_map if not has_errors else None,
            "full_source": full_source,
        }
    finally:
        # best-effort cleanup; a stray temp dir isn't worth failing the request over
        for f in tmp_dir.glob("*"):
            try:
                f.unlink()
            except OSError:
                pass
        try:
            tmp_dir.rmdir()
        except OSError:
            pass
