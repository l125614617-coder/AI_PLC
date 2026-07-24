"""
輕量版 IEC 61131-3 結構化文字 (ST) 靜態驗證引擎
--------------------------------------------------
不呼叫任何外部編譯器、零第三方依賴、完全離線。
以啟發式規則掃描 LLM 產生的 ST 程式碼，回傳與 app UI 相容的結構：

    {
        "score":  int(0-100),          # 信心分數
        "status": "passed" | "passed_with_warnings" | "needs_review",
        "stats":  {declared_variables, errors, warnings, info},
        "issues": [{code, message, severity, line?}]
    }

severity: "error" | "warning" | "info"
"""

import re

# ------------------------------------------------------------------
# 保留字 / 標準型別 / 標準功能區塊，用於「使用未宣告變數」判斷時排除
# ------------------------------------------------------------------
_KEYWORDS = {
    "IF", "THEN", "ELSE", "ELSIF", "END_IF", "FOR", "TO", "BY", "DO", "END_FOR",
    "WHILE", "END_WHILE", "REPEAT", "UNTIL", "END_REPEAT", "CASE", "OF", "END_CASE",
    "FUNCTION", "END_FUNCTION", "FUNCTION_BLOCK", "END_FUNCTION_BLOCK",
    "PROGRAM", "END_PROGRAM", "VAR", "VAR_INPUT", "VAR_OUTPUT", "VAR_IN_OUT",
    "VAR_GLOBAL", "VAR_TEMP", "VAR_EXTERNAL", "END_VAR", "CONSTANT", "RETAIN",
    "STRUCT", "END_STRUCT", "TYPE", "END_TYPE", "RETURN", "EXIT", "CONTINUE",
    "AND", "OR", "XOR", "NOT", "MOD", "TRUE", "FALSE", "AT",
}
_TYPES = {
    "BOOL", "BYTE", "WORD", "DWORD", "LWORD", "SINT", "INT", "DINT", "LINT",
    "USINT", "UINT", "UDINT", "ULINT", "REAL", "LREAL", "TIME", "LTIME",
    "DATE", "TIME_OF_DAY", "TOD", "DATE_AND_TIME", "DT", "STRING", "WSTRING",
    "CHAR", "WCHAR", "POINTER", "ARRAY", "REFERENCE",
}
_STD_FUNCS = {
    "TON", "TOF", "TP", "R_TRIG", "F_TRIG", "CTU", "CTD", "CTUD", "RS", "SR",
    "ABS", "SQRT", "LN", "LOG", "EXP", "SIN", "COS", "TAN", "MIN", "MAX",
    "LIMIT", "MUX", "SEL", "MOVE", "ADD", "SUB", "MUL", "DIV", "SHL", "SHR",
    "ROL", "ROR", "MC_MOVEABSOLUTE", "MC_MOVEVELOCITY", "MC_POWER", "MC_RESET",
    "MC_STOP", "MC_HOME",
}

# 需成對出現的區塊關鍵字 (opener -> closer)
_BLOCK_PAIRS = [
    (r"\bFUNCTION_BLOCK\b", r"\bEND_FUNCTION_BLOCK\b", "FUNCTION_BLOCK"),
    (r"\bFUNCTION\b(?!_BLOCK)", r"\bEND_FUNCTION\b", "FUNCTION"),
    (r"\bPROGRAM\b", r"\bEND_PROGRAM\b", "PROGRAM"),
    (r"\bIF\b", r"\bEND_IF\b", "IF"),
    (r"\bFOR\b", r"\bEND_FOR\b", "FOR"),
    (r"\bWHILE\b", r"\bEND_WHILE\b", "WHILE"),
    (r"\bREPEAT\b", r"\bEND_REPEAT\b", "REPEAT"),
    (r"\bCASE\b", r"\bEND_CASE\b", "CASE"),
    (r"\bSTRUCT\b", r"\bEND_STRUCT\b", "STRUCT"),
]

# VAR 家族開頭 (任一種) 皆以 END_VAR 收尾
_VAR_OPENER = re.compile(
    r"\bVAR(_INPUT|_OUTPUT|_IN_OUT|_GLOBAL|_TEMP|_EXTERNAL)?\b", re.IGNORECASE
)
_END_VAR = re.compile(r"\bEND_VAR\b", re.IGNORECASE)

_COMMENT_BLOCK = re.compile(r"\(\*.*?\*\)", re.DOTALL)
_COMMENT_LINE = re.compile(r"//.*")
_STRING_LIT = re.compile(r"'[^']*'")


def _strip_comments(code: str) -> str:
    """移除 (* *) 與 // 註解，避免誤判 (保留行數用空白填回)。"""
    def _blank(m):
        return re.sub(r"[^\n]", " ", m.group(0))
    no_block = _COMMENT_BLOCK.sub(_blank, code)
    no_line = _COMMENT_LINE.sub("", no_block)
    return no_line


def _count(pattern: str, text: str) -> int:
    return len(re.findall(pattern, text, re.IGNORECASE))


def validate_st_code(code: str, description: str = "", category: str = "generic") -> dict:
    issues = []
    code = (code or "").strip()

    # ---- 0. 空程式 ----
    if not code:
        return {
            "score": 0,
            "status": "needs_review",
            "stats": {"declared_variables": 0, "errors": 1, "warnings": 0, "info": 0},
            "issues": [{"code": "E000", "message": "沒有偵測到任何程式碼。", "severity": "error"}],
        }

    clean = _strip_comments(code)
    clean_nostr = _STRING_LIT.sub("''", clean)
    lines = code.splitlines()

    # ---- 1. 註解 (* *) 配對 ----
    open_cmt = code.count("(*")
    close_cmt = code.count("*)")
    if open_cmt != close_cmt:
        issues.append({
            "code": "E010",
            "message": f"區塊註解不對稱：(* 出現 {open_cmt} 次，*) 出現 {close_cmt} 次。",
            "severity": "error",
        })

    # ---- 2. 區塊關鍵字配對 ----
    for open_pat, close_pat, name in _BLOCK_PAIRS:
        o = _count(open_pat, clean_nostr)
        c = _count(close_pat, clean_nostr)
        if o != c:
            issues.append({
                "code": "E020",
                "message": f"{name} 區塊未配對：{name} x{o} vs END_{name} x{c}。",
                "severity": "error",
            })

    # VAR 家族 vs END_VAR
    var_open = len(_VAR_OPENER.findall(clean_nostr))
    var_close = len(_END_VAR.findall(clean_nostr))
    if var_open != var_close:
        issues.append({
            "code": "E021",
            "message": f"VAR 區塊未配對：VAR* x{var_open} vs END_VAR x{var_close}。",
            "severity": "error",
        })

    # ---- 3. 收集宣告變數 ----
    declared = set()
    in_var = False
    for raw in _strip_comments(code).splitlines():
        line = raw.strip()
        if _VAR_OPENER.match(line):
            in_var = True
            continue
        if _END_VAR.match(line):
            in_var = False
            continue
        if in_var and ":" in line:
            names = line.split(":")[0]
            names = re.sub(r"\bAT\b.*", "", names, flags=re.IGNORECASE)  # 去掉 AT %I0.0
            for nm in names.split(","):
                nm = nm.strip()
                if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", nm):
                    declared.add(nm.upper())

    # ---- 4. 使用未宣告變數 (啟發式, info) ----
    body = _strip_comments(code)
    # 移除 VAR 區塊本身，只看程式邏輯
    body = re.sub(r"\bVAR(_\w+)?\b.*?\bEND_VAR\b", "", body, flags=re.IGNORECASE | re.DOTALL)
    body = _STRING_LIT.sub("", body)
    reserved = _KEYWORDS | _TYPES | _STD_FUNCS
    # POU (FUNCTION_BLOCK/FUNCTION/PROGRAM) 名稱本身不算變數
    for pou in re.findall(r"\b(?:FUNCTION_BLOCK|FUNCTION|PROGRAM)\s+([A-Za-z_]\w*)",
                          code, re.IGNORECASE):
        reserved.add(pou.upper())
    used = {}
    for i, raw in enumerate(body.splitlines(), 1):
        # AXIS_REF/FB member names (Axis1.Busy) and named call parameters
        # (Enable := ...) are not standalone variables.
        member_or_param = {
            match.group(1).upper()
            for match in re.finditer(
                r"(?:\(|,)\s*([A-Za-z_][A-Za-z0-9_]*)\s*:=",
                raw,
            )
        }
        member_or_param.update(
            match.group(1).upper()
            for match in re.finditer(r"\.\s*([A-Za-z_][A-Za-z0-9_]*)", raw)
        )
        for tok in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", raw):
            up = tok.upper()
            if up in reserved:
                continue
            if up in declared:
                continue
            if up in member_or_param:
                continue
            if re.fullmatch(r"T#.*", tok, re.IGNORECASE):
                continue
            # 疑似函式呼叫 (後面接括號) 先略過，降低誤報
            used.setdefault(up, (tok, i))
    undeclared = list(used.values())[:8]
    for name, ln in undeclared:
        issues.append({
            "code": "W030",
            "message": f"識別字 '{name}' 未在 VAR 區塊宣告 (可能是常數/列舉或漏宣告)。",
            "severity": "warning",
            "line": ln,
        })

    # ---- 5. 賦值運算子 := 檢查 (常見 LLM 誤用 = 當賦值) ----
    assign_warn = 0
    for i, raw in enumerate(_strip_comments(code).splitlines(), 1):
        line = raw.strip()
        low = line.upper()
        if low.startswith(("IF", "ELSIF", "WHILE", "UNTIL", "CASE")):
            continue  # 條件式用 = 是合法比較
        # 敘述句中出現單一 = 卻沒有 := / <= / >= / <> / =
        stripped = re.sub(r"(:=|<=|>=|<>|=>)", "", line)
        if re.search(r"[A-Za-z0-9_\]\)]\s*=\s*[A-Za-z0-9_\(]", stripped) and ":=" not in line:
            assign_warn += 1
            if assign_warn <= 5:
                issues.append({
                    "code": "W040",
                    "message": "疑似用 '=' 當賦值，ST 賦值應為 ':='。",
                    "severity": "warning",
                    "line": i,
                })

    # ---- 6. 敘述句缺分號 (啟發式, warning) ----
    _control_end = ("THEN", "DO", "OF", "ELSE")
    _skip_kw = tuple(k for k in _KEYWORDS)
    missing_semi = 0
    for i, raw in enumerate(_strip_comments(code).splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        low = line.upper()
        if line.endswith((";", ",", "(", "{", "[")):
            continue
        if low.endswith(_control_end):
            continue
        # 純關鍵字 / 區塊標記行
        first = re.split(r"[\s(]", low, maxsplit=1)[0]
        if first in _skip_kw or _VAR_OPENER.match(line) or _END_VAR.match(line):
            continue
        if line.endswith(":") or re.match(r"^[\w,\s]+:$", line):  # CASE 標籤
            continue
        # 看起來像敘述句 (含 := 或函式呼叫) 卻沒 ;
        if ":=" in line or re.search(r"\w\s*\(", line):
            missing_semi += 1
            if missing_semi <= 5:
                issues.append({
                    "code": "W050",
                    "message": "敘述句可能缺少結尾分號 ';'。",
                    "severity": "warning",
                    "line": i,
                })

    # ---- 7. 馬達 / 運動控制安全語意 (info) ----
    if category == "motor_control":
        up = code.upper()
        forbidden_axis_inputs = re.findall(
            r"\.\s*(ESTOPACTIVE|LIMITPOS|LIMITNEG|HOMESWITCH)\b",
            clean,
            re.IGNORECASE,
        )
        for field in sorted(set(name.upper() for name in forbidden_axis_inputs)):
            issues.append({
                "code": "E063",
                "message": (
                    f"不可在生成程式直接讀寫 AXIS_REF.{field}；"
                    "此安全輸入由外部介面與 MC_* 函式方塊處理。"
                ),
                "severity": "error",
            })
        if not re.search(r"E[_]?STOP|EMERGENCY|ESTOP", up):
            issues.append({
                "code": "I060",
                "message": "未偵測到緊急停止 (E-Stop) 相關邏輯，建議加入安全互鎖。",
                "severity": "info",
            })
        if not re.search(r"LIMIT|LIM_|LSW|END_?SWITCH", up):
            issues.append({
                "code": "I061",
                "message": "未偵測到極限開關 (Limit Switch) 處理。",
                "severity": "info",
            })
        if not re.search(r"RESET|\bACK\b|\bRST\b", up):
            issues.append({
                "code": "I062",
                "message": "未偵測到復歸 (Reset/Ack) 邏輯。",
                "severity": "info",
            })

    # ---- 8. 統計與評分 ----
    errors = sum(1 for x in issues if x["severity"] == "error")
    warnings = sum(1 for x in issues if x["severity"] == "warning")
    info = sum(1 for x in issues if x["severity"] == "info")

    score = 100 - errors * 25 - warnings * 8 - info * 3
    score = max(0, min(100, score))

    if errors > 0:
        status = "needs_review"
    elif warnings > 0:
        status = "passed_with_warnings"
    else:
        status = "passed"

    return {
        "score": score,
        "status": status,
        "stats": {
            "declared_variables": len(declared),
            "errors": errors,
            "warnings": warnings,
            "info": info,
        },
        "issues": issues,
    }
