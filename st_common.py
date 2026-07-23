"""Small ST-parsing helpers shared by validator.py's heuristics and the
compile/simulate pipeline (compiler.py). Kept dependency-free like validator.py.
"""

import re

# Same POU-name pattern used by validator.py's undeclared-variable heuristic
# (validator.py:156-157), factored out here rather than duplicated so both
# call sites stay in sync if the grammar subset we care about ever grows.
_POU_PATTERN = re.compile(
    r"\b(FUNCTION_BLOCK|FUNCTION|PROGRAM)\s+([A-Za-z_]\w*)", re.IGNORECASE
)

_COMMENT_BLOCK = re.compile(r"\(\*.*?\*\)", re.DOTALL)
_COMMENT_LINE = re.compile(r"//.*")


def strip_comments(code: str) -> str:
    """Blank out (* *) and // comments, preserving line count/newlines so
    line-number remapping stays valid. Same approach as validator.py's private
    _strip_comments, factored out here because compiler.py also needs it: this
    matiec build's error recovery gets badly confused by non-ASCII (e.g.
    Chinese) text inside comments, producing a cascade of unrelated error
    messages instead of the real one -- discovered when a genuinely broken
    generated program (an empty ELSE branch) was reported as a dozen bogus
    'invalid variable(s) declaration' errors purely because of Chinese
    comments elsewhere in the file. iec2c doesn't need comments at all, so
    stripping them before compiling sidesteps the whole class of issue."""
    def _blank(m):
        return re.sub(r"[^\n]", " ", m.group(0))
    no_block = _COMMENT_BLOCK.sub(_blank, code)
    no_line = _COMMENT_LINE.sub(_blank, no_block)
    return no_line


def extract_pous(code: str) -> list:
    """Return [{'name', 'kind'}] for each top-level POU declared in code, in
    source order. 'kind' is one of FUNCTION_BLOCK / FUNCTION / PROGRAM (uppercased)."""
    pous = []
    for kind, name in _POU_PATTERN.findall(code or ""):
        pous.append({"name": name, "kind": kind.upper()})
    return pous


def extract_var_table(variables_markdown: str) -> list:
    """Parse the '### VARIABLES' markdown table app.py already extracts
    (Name | Type | Direction | Description, with or without leading/trailing
    pipes) into [{'name', 'type', 'direction'}]. Tolerates the header row, the
    '---|---' separator row, and malformed rows by skipping anything that
    doesn't look like a real variable row."""
    rows = []
    for line in (variables_markdown or "").splitlines():
        line = line.strip().strip("|")
        if "|" not in line:
            continue
        cells = [c.strip() for c in line.split("|")]
        if len(cells) < 3:
            continue
        name, type_, direction = cells[0], cells[1], cells[2]
        if not re.fullmatch(r"[A-Za-z_]\w*", name):
            continue  # separator row ('---') or junk
        if name.lower() == "name" and type_.lower() == "type":
            continue  # header row
        rows.append({"name": name, "type": type_, "direction": direction.upper()})
    return rows
