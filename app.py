import os
import re
import hashlib

import streamlit as st
from ollama import Client

# 匯入輕量本地驗證引擎
from validator import validate_st_code
from prompt_contract import authoritative_user_prompt, prompt_control_conflicts

# 匯入編譯檢查 (matiec) 與模擬部署 (OpenPLC + Modbus) 引擎 -- 選用，缺少工具鏈時優雅降級
try:
    from compiler import compile_st_code, iec2c_available
    from simulator import run_all_scenarios, openplc_available
    from scenarios import scenarios_for_code
    from motion_contract import validate_motion_contract
    from twin_deployment import (
        deploy_to_twin,
        load_deployment,
        stop_twin,
    )
    _SIMULATION_IMPORT_ERROR = None
except Exception as _e:  # 例如缺少 pymodbus/requests，或路徑尚未設定好
    _SIMULATION_IMPORT_ERROR = str(_e)
    deploy_to_twin = None
    load_deployment = None
    stop_twin = None
    validate_motion_contract = None

# ==========================================
# 1. 基礎設定與快取連線
# ==========================================
@st.cache_resource
def get_ollama_client():
    return Client(host="http://localhost:11434")


@st.cache_resource
def get_llamacpp_client():
    from local_provider import LlamaCppClient

    return LlamaCppClient(
        os.environ.get(
            "PLC_ASSIST_LLAMACPP_BASE",
            "http://127.0.0.1:8082/v1",
        )
    )


PROVIDER = os.environ.get("PLC_ASSIST_PROVIDER", "ollama").lower()
IS_CODEX = PROVIDER == "codex"
IS_LLAMACPP = PROVIDER in {"llamacpp", "llama.cpp"}
if IS_CODEX:
    client = None
    MODEL_NAME = os.environ.get("PLC_ASSIST_CODEX_MODEL", "gpt-5.6-sol")
    edition_name = "Codex 推理版"
    provider_label = "Codex CLI（唯讀暫時工作階段）"
elif IS_LLAMACPP:
    client = get_llamacpp_client()
    MODEL_NAME = os.environ.get(
        "PLC_ASSIST_LLAMACPP_MODEL",
        "Qwen3.6-27B-Q3_K_M.gguf",
    )
    edition_name = "llama.cpp MTP 版"
    provider_label = "本機 llama.cpp"
else:
    client = get_ollama_client()
    MODEL_NAME = os.environ.get("PLC_ASSIST_OLLAMA_MODEL", "qwen3.5:9b")
    edition_name = "Ollama 本地版"
    provider_label = "本機 Ollama"

st.set_page_config(page_title=f"PLC-Assist {edition_name}", layout="wide")

# ==========================================
# 2. 預設 Prompt (System / User 分離)
# ==========================================
DEFAULT_SYSTEM_PROMPT = (
    "你是一個精通 IEC 61131-3 標準的工業自動化專家，熟悉 CODESYS 平台與運動控制 (Motion Control) 架構。\n"
    "請依據使用者的需求，生成包含安全防護的『結構化文字 (ST)』程式碼。\n\n"
    "請保持精簡：程式碼裡『不要』寫大段解釋性註解，每行程式碼最多一個簡短行內註解就好，"
    "詳細的原理說明請放在 ### EXPLANATION 區塊，不要塞進程式碼裡——這樣可以避免輸出過長被截斷。\n\n"
    "你必須『嚴格』按照以下四個標題格式輸出：\n\n"
    "### CODE\n"
    "```st\n"
    "// 你的 ST 程式碼\n"
    "```\n\n"
    "### VARIABLES\n"
    "Name | Type | Direction | Description\n"
    "---|---|---|---\n"
    "bEnable | BOOL | VAR_INPUT | Enable flag\n\n"
    "### EXPLANATION\n"
    "- (條列式說明運作原理)\n\n"
    "### WARNINGS\n"
    "- (條列式說明安全警告與硬體互鎖建議)\n\n"
    "=== CODE 區塊的強制規範 (非常重要，違反會導致無法編譯/模擬) ===\n\n"
    "1. 整份程式碼只能有『一個』頂層 POU，而且必須是：\n"
    "   PROGRAM MAIN\n"
    "   ...\n"
    "   END_PROGRAM\n"
    "   不可以寫 FUNCTION_BLOCK 當作主程式、也不可以把名稱取成 MAIN 以外的名字。\n\n"
    "   本系統使用的編譯器要求 END_IF、END_FOR、END_WHILE、END_CASE 這些區塊結尾關鍵字後面『必須』"
    "加分號 (例如 END_IF;、END_FOR;)，即使你熟悉的其他 IEC 61131-3 工具不強制要求也一樣——"
    "這裡沒有加分號會導致編譯失敗，請務必每一個都加。\n\n"
    "   本系統的編譯器『不支援』指定長度的字串型別 (STRING[20] 或 STRING(20) 這兩種寫法都會編譯失敗)，"
    "如果需要字串變數，請只用不指定長度的 STRING。\n\n"
    "2. 以下型別與函式方塊已經由系統事先定義好，你『絕對不可以』自己重新宣告\n"
    "   TYPE AXIS_REF、也不可以自己寫 FUNCTION_BLOCK MC_Power / MC_Reset / MC_Stop / "
    "MC_MoveAbsolute / MC_MoveVelocity / MC_Home ——直接宣告一個 AXIS_REF 型別的變數、"
    "並呼叫這些現成的函式方塊即可。運動控制、安全互鎖 (緊急停止/極限開關) 的邏輯已經內建在這些函式方塊裡，"
    "你不需要也不應該自己重新實作這些安全邏輯。\n\n"
    "   可用的函式方塊簽章如下 (呼叫時用具名參數 Name := Value)：\n"
    "   - MC_Power(Enable: BOOL; Axis: AXIS_REF) -> Status: BOOL; Error: BOOL\n"
    "   - MC_Reset(Execute: BOOL; Axis: AXIS_REF) -> Done: BOOL; Error: BOOL\n"
    "   - MC_Stop(Execute: BOOL; Deceleration: REAL; Axis: AXIS_REF) -> Done: BOOL; Busy: BOOL\n"
    "   - MC_MoveAbsolute(Execute: BOOL; Position: REAL; Velocity: REAL; Axis: AXIS_REF) "
    "-> Done: BOOL; Busy: BOOL; Active: BOOL; CommandAborted: BOOL; Error: BOOL\n"
    "   - MC_MoveVelocity(Execute: BOOL; Velocity: REAL; Acceleration: REAL; Axis: AXIS_REF) "
    "-> InVelocity: BOOL; Busy: BOOL; Active: BOOL; CommandAborted: BOOL; Error: BOOL\n"
    "   - MC_Home(Execute: BOOL; Velocity: REAL; Axis: AXIS_REF) -> Done: BOOL; Busy: BOOL; Error: BOOL\n"
    "   所有函式方塊的 Axis 參數都是 VAR_IN_OUT，呼叫時傳入同一個 AXIS_REF 變數 (例如 Axis := Axis1)，"
    "讓多個函式方塊共享同一顆虛擬軸的狀態。\n\n"
    "   AXIS_REF 內部有這些你可以『讀取』來判斷狀態的欄位 (不要直接寫入，狀態由函式方塊自己維護)：\n"
    "   Position: REAL, Velocity: REAL, Busy: BOOL, Done: BOOL, Active: BOOL, Error: BOOL, "
    "ErrorID: DINT, Enabled: BOOL, Homed: BOOL, InVelocity: BOOL (皆為唯讀狀態)。\n"
    "   接收這些欄位的變數必須使用完全相同的型別；尤其 ErrorID 是 DINT，不是 DWORD。\n\n"
    "   AXIS_REF 另外還有 EStopActive、LimitPos、LimitNeg、HomeSwitch 這四個欄位——這些是由外部安全硬體/"
    "測試工具『自動寫入』的輸入訊號，不是你要自己判斷、賦值或提供邏輯的東西。你的程式碼『完全不需要』提到、"
    "讀取或寫入這四個欄位，也不要自己宣告 bEStop、bLimitSwitch 這類變數來模擬它們——每個函式方塊內部已經會"
    "自動檢查這些欄位，需要時會自行中止動作並回報 Error/ErrorID，這就是規則 2 說『安全互鎖邏輯已經內建、"
    "你不應該自己重新實作』的意思。你只需要呼叫函式方塊、視需要檢查 Busy/Done/Error 來決定下一步邏輯即可。\n\n"
    "   這條『不要模擬』的限制『只』適用於 EStopActive/LimitPos/LimitNeg/HomeSwitch 這四個特定欄位，"
    "跟其他一般操作變數『完全無關』：你可以自由宣告像是重置請求這樣的一般輸入變數 (例如 bResetReq : BOOL;)，"
    "並直接呼叫 MC_Reset(Execute := bResetReq, Axis := Axis1) 來清除錯誤狀態，這樣做完全不違反任何規則，"
    "不需要為此猶豫或反覆考慮。\n\n"
    "3. 運行模式對應：如果需求是『JOG』模式 (持續依指定速度移動，直到被要求停止)，請使用 MC_MoveVelocity；"
    "如果需求是『Absolute Position』模式 (移動到指定的目標位置後停止)，請使用 MC_MoveAbsolute。"
    "本系統『沒有』提供 MC_Jog，不要嘗試呼叫或發明這個函式方塊。\n\n"
    "4. PROGRAM MAIN 裡『必須』宣告一個名稱固定為 bEnable 的變數 (bEnable : BOOL;)，做為整個控制邏輯的"
    "總開關/啟動訊號——你的邏輯應該用這個 bEnable 來決定是否呼叫 MC_Power/MC_MoveAbsolute/MC_MoveVelocity "
    "等函式方塊的 Execute/Enable 參數。這個名稱是固定的，不可以取成 bStart、bRun 或其他名字，"
    "這樣外部測試工具才能自動找到它並驅動你的邏輯。\n\n"
    "5. 除了 AXIS_REF 變數和 bEnable 之外，你可以自由宣告其他一般變數做為對外的操作介面 "
    "(要跟 ### VARIABLES 表格對應)，例如目標速度/位置、狀態回報等。這些變數請宣告成一般變數，"
    "『不要』使用 AT %IX / %QX / %MW 這種底層記憶體位址語法——外部的記憶體對應由其他工具自動處理，你不需要管。\n\n"
    "6. 範例骨架 (僅供參考格式，實際邏輯依需求調整)：\n\n"
    "   範例 A -- Absolute Position 模式：\n"
    "   PROGRAM MAIN\n"
    "   VAR\n"
    "       Axis1     : AXIS_REF;\n"
    "       Pwr       : MC_Power;\n"
    "       Mover     : MC_MoveAbsolute;\n"
    "       bEnable   : BOOL;\n"
    "       rTargetPos: REAL;\n"
    "       bDone     : BOOL;\n"
    "   END_VAR\n"
    "   Pwr(Enable := bEnable, Axis := Axis1);\n"
    "   Mover(Execute := bEnable, Position := rTargetPos, Velocity := 100.0, Axis := Axis1);\n"
    "   bDone := Axis1.Done;\n"
    "   END_PROGRAM\n\n"
    "   範例 B -- JOG 模式：\n"
    "   PROGRAM MAIN\n"
    "   VAR\n"
    "       Axis1      : AXIS_REF;\n"
    "       Pwr        : MC_Power;\n"
    "       Jogger     : MC_MoveVelocity;\n"
    "       bEnable    : BOOL;\n"
    "       rJogVel    : REAL;\n"
    "       bInVelocity: BOOL;\n"
    "   END_VAR\n"
    "   Pwr(Enable := bEnable, Axis := Axis1);\n"
    "   Jogger(Execute := bEnable, Velocity := rJogVel, Acceleration := 200.0, Axis := Axis1);\n"
    "   bInVelocity := Axis1.InVelocity;\n"
    "   END_PROGRAM\n\n"
    "7. 輸出 CODE 前逐項自我檢查：\n"
    "   - 最後一行必須是 END_PROGRAM；所有在程式本體使用的變數都必須先在 VAR 區塊宣告。\n"
    "   - MC_Power 必須每個掃描週期呼叫一次，正常寫法是 Pwr(Enable := bEnable, Axis := Axis1)，"
    "不可以只在急停條件內呼叫，也不可以把 Enable 固定為 FALSE。\n"
    "   - UI 給定的速度/位置必須實際寫入程式（可用變數初值，例如 rJogVel : REAL := 1500.0），"
    "不可以只宣告一個未初始化變數。\n"
    "   - 若需求提到急停或極限限制，代表使用內建 MC_* 函式方塊的保護即可；"
    "CODE 仍然禁止直接提到 EStopActive、LimitPos、LimitNeg、HomeSwitch。\n"
    "   - Reset 只能由一般的 bResetReq 輸入驅動：Rst(Execute := bResetReq, Axis := Axis1)。"
    "不可以自行把 bResetReq 持續設成 TRUE，也不可以根據安全硬體欄位反向產生 Reset。\n"
)


def build_user_prompt(ui_data: dict) -> str:
    """依控制參數產生預設的 User Prompt 範本 (使用者可再自由編輯)。"""
    return (
        f"請建立一個控制功能區塊。設定如下：\n"
        f"- 啟用緊急停止: {ui_data['safety_guard_enabled']}\n"
        f"- 運行模式: {ui_data['mode']}\n"
        f"- 目標速度: {ui_data['requested_velocity']} rpm\n"
        f"- 目標位置: {ui_data['requested_position']} mm\n"
        f"- 方向: {ui_data['requested_direction']}\n"
        "極限與緊急停止由系統提供的 MC_* 函式方塊內建處理；CODE 不得直接讀寫 "
        "EStopActive、LimitPos、LimitNeg、HomeSwitch。請另外宣告一般輸入 "
        "bResetReq，並用 MC_Reset(Execute := bResetReq, Axis := Axis1) 提供人工復歸。"
    )


# ==========================================
# 3. 解析器：還原 PLC-Assist 的 Regex 拆解邏輯
# ==========================================
def _parse_response(text: str) -> dict:
    """Parse the LLM response into sections."""
    sections = {"code": "", "variables": "", "explanation": "", "warnings": ""}

    code_match = re.search(r"### CODE\s*```(?:iec|st|structured[_ ]?text)?\s*\n(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if code_match: sections["code"] = code_match.group(1).strip()

    var_match = re.search(r"### VARIABLES\s*\n(.*?)(?=### |\Z)", text, re.DOTALL | re.IGNORECASE)
    if var_match: sections["variables"] = var_match.group(1).strip()

    exp_match = re.search(r"### EXPLANATION\s*\n(.*?)(?=### |\Z)", text, re.DOTALL | re.IGNORECASE)
    if exp_match: sections["explanation"] = exp_match.group(1).strip()

    warn_match = re.search(r"### WARNINGS\s*\n(.*?)(?=### |\Z)", text, re.DOTALL | re.IGNORECASE)
    if warn_match: sections["warnings"] = warn_match.group(1).strip()

    if not sections["code"] and text.strip():
        sections["code"] = text.strip()

    return sections

# ==========================================
# 4. AI Agent 核心邏輯 (streaming：即時串流思考過程)
# ==========================================
def ask_ai_plc_assistant(system_prompt: str, user_prompt: str, think: bool = True,
                          think_area=None, answer_area=None) -> dict:
    """以 streaming 方式呼叫模型；think_area / answer_area 為 Streamlit placeholder，
    可即時把思考與答案逐字顯示給使用者。回傳解析與驗證後的結果字典。"""
    try:
        if IS_CODEX:
            from codex_provider import generate_with_codex

            def update_progress(text: str, attempt: int = 1) -> None:
                if think_area is not None:
                    prefix = (
                        "### 初次生成\n\n"
                        if attempt == 1 else
                        f"### 編譯修復第 {attempt - 1} 輪\n\n"
                    )
                    think_area.markdown(prefix + text)
                if answer_area is not None:
                    answer_area.markdown(
                        "✍️ Codex 正在產生最終 ST 答案..."
                        if attempt == 1 else
                        f"🔧 Codex 正在依 matiec 錯誤進行第 {attempt - 1} 輪修復..."
                    )

            response = generate_with_codex(
                system_prompt,
                user_prompt,
                on_progress=(lambda text: update_progress(text, 1)) if think else None,
            )
            responses = [response]
            parsed = _parse_response(response["raw_text"])
            compile_result = None
            max_repairs = int(os.environ.get("PLC_ASSIST_CODEX_MAX_REPAIRS", "2"))

            if not _SIMULATION_IMPORT_ERROR:
                for repair_index in range(1, max_repairs + 1):
                    compile_result = compile_st_code(parsed["code"])
                    if compile_result["status"] == "compiled":
                        break

                    issue_text = "\n".join(
                        f"- Line {issue.get('line')}: {issue.get('message')}"
                        for issue in compile_result.get("issues", [])
                    ) or f"- compiler status: {compile_result['status']}"
                    repair_prompt = (
                        f"{user_prompt}\n\n"
                        "上一版答案未通過本系統實際使用的 matiec 編譯器。"
                        "請依下列真實編譯錯誤修正，保留原始需求，重新輸出完整四區塊；"
                        "不要只輸出 diff，也不要解釋修復過程。\n\n"
                        f"<compiler_errors>\n{issue_text}\n</compiler_errors>\n\n"
                        f"<previous_answer>\n{response['raw_text']}\n</previous_answer>"
                    )
                    attempt = repair_index + 1
                    response = generate_with_codex(
                        system_prompt,
                        repair_prompt,
                        on_progress=(
                            lambda text, n=attempt: update_progress(text, n)
                        ) if think else None,
                    )
                    responses.append(response)
                    parsed = _parse_response(response["raw_text"])

                if compile_result is None or compile_result["status"] != "compiled":
                    compile_result = compile_st_code(parsed["code"])

            total_usage = {}
            for item in responses:
                for key, value in item.get("usage", {}).items():
                    if isinstance(value, int):
                        total_usage[key] = total_usage.get(key, 0) + value

            parsed["thinking"] = (
                "\n\n---\n\n".join(item["thinking"] for item in responses)
                if think else ""
            )
            parsed["think_requested"] = think
            parsed["model"] = response["model"]
            parsed["usage"] = total_usage
            parsed["generation_attempts"] = len(responses)
            parsed["auto_compile"] = compile_result
            parsed["validation"] = validate_st_code(
                parsed["code"],
                "Motion control with safety interlocks.",
                "motor_control",
            )
            return parsed

        stream = client.chat(
            model=MODEL_NAME,
            think=think,  # 開啟思考模式，思考增量會出現在 chunk.message.thinking
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            # num_predict 需涵蓋「思考 + 答案」；思考可能長達數千 token，故上限加大。
            # 這只是延後問題發生的機率，無法根治思考模式偶爾會耗盡預算、完全生不出程式碼的狀況
            # (見對話紀錄的實測案例)——真正的緩解方式是預設關閉思考模式 (show_thinking 預設 False)。
            options={"temperature": 0.2, "num_predict": 24576, "num_ctx": 32768},
            stream=True,
        )

        thinking_acc = ""
        content_acc = ""
        i = 0
        for chunk in stream:
            m = chunk.message
            t = getattr(m, "thinking", None)
            c = m.content
            if t:
                thinking_acc += t
            if c:
                content_acc += c
            i += 1
            # 節流：每幾個 chunk 才重繪一次，避免過度刷新造成卡頓
            if i % 3 == 0:
                if think_area is not None and thinking_acc:
                    think_area.markdown(thinking_acc + " ▌")
                if answer_area is not None and content_acc:
                    answer_area.markdown(f"✍️ 產生答案中... ({len(content_acc)} 字)")

        # 串流結束，最後完整重繪一次
        if think_area is not None and thinking_acc:
            think_area.markdown(thinking_acc)

        thinking = thinking_acc.strip()
        raw_text = content_acc.strip()

        # 後備：若模型把思考塞進 content 的 <think>...</think>，改由此擷取
        if not thinking:
            mt = re.search(r"<think>(.*?)</think>", raw_text, re.DOTALL | re.IGNORECASE)
            if mt:
                thinking = mt.group(1).strip()
                raw_text = re.sub(r"<think>.*?</think>", "", raw_text, flags=re.DOTALL | re.IGNORECASE).strip()

        # 1. 拆解內容
        parsed = _parse_response(raw_text)
        parsed["thinking"] = thinking
        parsed["think_requested"] = think

        # 2. 本地驗證 (輕量靜態分析)
        parsed["validation"] = validate_st_code(
            parsed["code"], "Motion control with safety interlocks.", "motor_control"
        )

        return parsed

    except Exception as e:
        return {"error": str(e)}

# ==========================================
# 4.5 編譯檢查 + 模擬部署 (選用，較慢，需點擊觸發)
# ==========================================
def run_compile_and_simulate(code: str, expected_control: dict | None = None) -> dict:
    """Stage 2 (matiec 真實編譯檢查) + Stages 3-5 (部署到 OpenPLC 並跑 Modbus 情境測試)。
    與 validate_st_code 不同，這裡會啟動外部程序、耗時 15-45 秒，因此只在使用者主動點擊時執行。

    情境測試跑的就是『這次 LLM 產生的程式碼』本身：compiler.py 會自動偵測程式碼裡宣告的
    AXIS_REF 變數與 (system prompt 規定的) bEnable 訊號，把它們接到固定的 Modbus 位址上，
    讓底下的情境測試可以不管 LLM 這次取了什麼變數名稱，直接驅動並觀察它的實際行為。
    如果這次生成的程式碼沒有照規範宣告 AXIS_REF 變數 (compile['axis_io_map'] 會是 None)，
    就沒有東西可以這樣接，只能停在「有沒有編過」，不會嘗試部署模擬。"""
    result = {
        "compile": None,
        "scenarios": None,
        "source_hash": hashlib.sha256((code or "").encode("utf-8")).hexdigest(),
        "contract": (
            validate_motion_contract(code, expected_control)
            if validate_motion_contract
            else {"status": "unavailable", "issues": []}
        ),
    }

    if _SIMULATION_IMPORT_ERROR:
        result["compile"] = {
            "status": "iec2c_unavailable",
            "issues": [{"severity": "error",
                        "message": f"編譯/模擬模組載入失敗：{_SIMULATION_IMPORT_ERROR}（請執行 setup/setup_windows_toolchain.ps1）",
                        "line": None, "in_generated_code": False}],
            "wrapper_source": "", "axis_io_map": None,
            "axis_register_map": None, "full_source": "",
        }
        return result

    try:
        result["compile"] = compile_st_code(code)
    except Exception as e:
        result["compile"] = {
            "status": "compile_failed",
            "issues": [{"severity": "error", "message": f"編譯呼叫發生例外：{e}", "line": None, "in_generated_code": False}],
            "wrapper_source": "", "axis_io_map": None,
            "axis_register_map": None, "full_source": "",
        }
        return result

    if result["compile"]["status"] != "compiled":
        return result  # 編不過就不用浪費時間部署了

    if result["contract"].get("status") == "failed":
        result["scenarios"] = {"status": "contract_failed"}
        return result

    axis_io_map = result["compile"].get("axis_io_map")
    if axis_io_map is None:
        result["scenarios"] = {"status": "no_axis_interface"}
        return result

    if not openplc_available():
        result["scenarios"] = {"status": "openplc_unavailable"}
        return result

    try:
        full_source = result["compile"]["full_source"]
        selected_scenarios = scenarios_for_code(code, contract=result["contract"])
        result["scenarios"] = {
            "status": "ran",
            "results": run_all_scenarios(
                selected_scenarios,
                axis_io_map,
                full_source,
                register_map=result["compile"].get("axis_register_map"),
            ),
        }
    except Exception as e:
        result["scenarios"] = {"status": "error", "message": str(e)}

    return result


# ==========================================
# 5. 前端 UI 介面層
# ==========================================
st.title(f"⚙️ Generate Structured Text (PLC-Assist {edition_name})")
st.caption(f"模型來源：{MODEL_NAME}｜{provider_label}")
st.markdown("---")

col1, col2 = st.columns([4, 6])

with col1:
    st.header("🧩 控制參數配置")
    enable_safety = st.checkbox("⚠️ 啟用緊急停止 (E-Stop)", value=True)
    action_type = st.radio("運行模式：", ("JOG", "Absolute Position"))
    input_velocity = st.number_input("速度 (rpm)：", min_value=0, max_value=5000, value=1500, step=100)
    target_position = st.number_input("位置 (mm)：", value=1000, step=100) if action_type == "Absolute Position" else 0
    direction = "forward" if action_type == "Absolute Position" else st.selectbox("方向：", ("forward", "reverse"))

    ui_puzzle_data = {
        "safety_guard_enabled": enable_safety,
        "mode": action_type,
        "requested_velocity": input_velocity,
        "requested_position": target_position,
        "requested_direction": direction,
    }

    st.markdown("---")

    # ---- User Prompt：預設模板 + 自由編輯 ----
    st.subheader("✏️ 需求描述 (User Prompt)")
    if "user_prompt" not in st.session_state:
        st.session_state["user_prompt"] = build_user_prompt(ui_puzzle_data)

    if st.button("🔄 依上方參數重建範本", use_container_width=True):
        st.session_state["user_prompt"] = build_user_prompt(ui_puzzle_data)

    st.text_area(
        "可自由編輯下方需求內容：",
        key="user_prompt",
        height=220,
    )
    prompt_conflicts = prompt_control_conflicts(
        st.session_state.get("user_prompt", ""), ui_puzzle_data
    )
    if prompt_conflicts:
        st.error(
            "控制參數與 User Prompt 不一致，請按「依上方參數重建範本」或修正下列內容：\n\n- "
            + "\n- ".join(prompt_conflicts)
        )

    # ---- System Prompt：可於進階區編輯 ----
    with st.expander("⚙️ 進階：System Prompt (角色與輸出格式設定)"):
        if "system_prompt" not in st.session_state:
            st.session_state["system_prompt"] = DEFAULT_SYSTEM_PROMPT
        if st.button("↩️ 還原預設 System Prompt"):
            st.session_state["system_prompt"] = DEFAULT_SYSTEM_PROMPT
        st.text_area("System Prompt：", key="system_prompt", height=260)

    st.markdown("---")
    is_generating = st.session_state.get("generating", False)
    show_thinking = st.checkbox(
        "🧠 顯示 Codex 推理摘要與進度" if IS_CODEX else "🧠 顯示思考過程 (Chain-of-Thought)",
        value=IS_CODEX,
        help=(
            "顯示 Codex 提供的安全推理摘要、工作階段進度與 token 使用量；"
            "不顯示模型私有的逐字思考鏈。"
            if IS_CODEX else
            "關閉 (預設)：快速模式，不顯示思考。開啟後會顯示本機模型回傳的 thinking 欄位，"
            "但可能增加延遲並消耗較多 token。"
        ),
        disabled=is_generating,
    )
    # 生成中鎖定按鈕，避免重複提交
    if st.button(
        "⏳ 生成中..." if is_generating else "🚀 Generate ST Code",
        type="primary",
        use_container_width=True,
        disabled=is_generating or bool(prompt_conflicts),
    ):
        # Snapshot the exact controls and prompt together. Subsequent widget
        # reruns must not change the contract belonging to this generation.
        pending_control = dict(ui_puzzle_data)
        st.session_state["pending_control"] = pending_control
        st.session_state["pending_user_prompt"] = authoritative_user_prompt(
            st.session_state.get("user_prompt", ""), pending_control
        )
        st.session_state["generating"] = True
        st.rerun()

with col2:
    if st.session_state.get("generating", False):
        generation_control = dict(
            st.session_state.get("pending_control", ui_puzzle_data)
        )
        generation_prompt = st.session_state.get(
            "pending_user_prompt",
            authoritative_user_prompt(
                st.session_state.get("user_prompt", ""), generation_control
            ),
        )
        # 即時串流顯示區
        think_area = None
        answer_area = None
        if show_thinking:
            st.markdown("### 🧠 Codex 推理摘要與進度" if IS_CODEX else "### 🧠 模型思考過程 (即時串流)")
            think_area = st.empty()
        answer_area = st.empty()

        spinner_msg = "Codex 正在推理並生成 ST Code..." if IS_CODEX else (
            "模型思考中..." if show_thinking else "快速生成 ST Code..."
        )
        with st.spinner(spinner_msg):
            generated_data = ask_ai_plc_assistant(
                st.session_state.get("system_prompt", DEFAULT_SYSTEM_PROMPT),
                generation_prompt,
                think=show_thinking,
                think_area=think_area,
                answer_area=answer_area,
            )
            generated_data["requested_mode"] = generation_control.get("mode", "Unknown")
            generated_data["requested_control"] = generation_control
            st.session_state["plc_data"] = generated_data
            st.session_state["generated"] = True
            # A compile result belongs to exactly one generated source. Never
            # offer a previous program for Twin deployment after regeneration.
            st.session_state.pop("sim_result", None)
            st.session_state.pop("twin_deploy_result", None)
        st.session_state["generating"] = False
        st.session_state.pop("pending_control", None)
        st.session_state.pop("pending_user_prompt", None)
        st.rerun()

    if st.session_state.get("generated", False):
        plc_data = st.session_state["plc_data"]

        if "error" in plc_data:
            st.error(f"Generation Failed: {plc_data['error']}")
        else:
            # --- 0. 模型推理摘要 / 本機 thinking ---
            thinking = plc_data.get("thinking", "")
            if thinking:
                with st.expander(
                    "🧠 Codex 推理摘要與進度" if IS_CODEX else "🧠 模型思考過程 (Chain-of-Thought)",
                    expanded=True,
                ):
                    st.markdown(thinking)
                    if IS_CODEX and plc_data.get("usage"):
                        st.json(plc_data["usage"])
                st.markdown("---")
            elif plc_data.get("think_requested"):
                st.info("ℹ️ 已開啟思考模式，但本次未取得思考內容（模型可能直接輸出答案）。")
                st.markdown("---")

            if IS_CODEX and plc_data.get("auto_compile"):
                auto_compile = plc_data["auto_compile"]
                attempts = plc_data.get("generation_attempts", 1)
                if auto_compile.get("status") == "compiled":
                    st.success(
                        f"✅ Codex 輸出已在回傳前通過 matiec 真實編譯"
                        f"（共 {attempts} 次生成嘗試）。"
                    )
                else:
                    st.error(
                        f"Codex 已自動修復 {max(0, attempts - 1)} 輪，"
                        "但輸出仍未通過 matiec；請查看下方 Compile Issues。"
                    )

            validation = plc_data.get("validation", {})
            score = validation.get("score", 0)
            status = validation.get("status", "unknown")
            stats = validation.get("stats", {})
            issues = validation.get("issues", [])

            # --- 1. Local Validation 面板 ---
            st.markdown("### 🟢 Local Validation")
            st.metric(label="Score", value=score)

            if status == "passed":
                st.success(f"Passed local ST checks with confidence score {score}.")
            elif status == "passed_with_warnings":
                st.warning(f"Passed core checks with {stats.get('warnings', 0)} warning(s) and confidence score {score}.")
            else:
                st.error(f"Needs review: {stats.get('errors', 0)} error(s), {stats.get('warnings', 0)} warning(s), score {score}.")

            st.caption(f"**Local static analysis** | {stats.get('declared_variables', 0)} declared vars | {stats.get('errors', 0)} errors | {stats.get('warnings', 0)} warnings | {stats.get('info', 0)} notes")

            # 顯示具體的 Error/Warning 項目
            if issues:
                with st.expander("🔍 檢視驗證詳細資訊 (Validation Issues)"):
                    for issue in issues:
                        line_info = f" (Line {issue['line']})" if "line" in issue else ""
                        if issue['severity'] == "error":
                            st.error(f"**{issue['code']}**: {issue['message']}{line_info}")
                        elif issue['severity'] == "warning":
                            st.warning(f"**{issue['code']}**: {issue['message']}{line_info}")
                        else:
                            st.info(f"**{issue['code']}**: {issue['message']}{line_info}")

            st.markdown("---")

            # --- 1.5 Compile + Simulate 面板 (選用，較慢，需點擊觸發) ---
            st.markdown("### 🧪 Compile + Simulate (OpenPLC)")
            is_simulating = st.session_state.get("simulating", False)
            if st.button(
                "⏳ 編譯並模擬中..." if is_simulating else "🧪 Run Compile + Simulate",
                disabled=is_simulating,
                help="真正呼叫 matiec 編譯，並部署到本機 OpenPLC 跑 Modbus 情境測試。比上面的 Local Validation 慢很多 (15-45 秒)，且需要本機已裝好編譯/模擬工具鏈 (見 setup/setup_windows_toolchain.ps1)。",
            ):
                st.session_state["simulating"] = True
                st.rerun()

            if is_simulating:
                with st.spinner("編譯並部署到 OpenPLC 模擬中，可能需要 15-45 秒..."):
                    st.session_state["sim_result"] = run_compile_and_simulate(
                        plc_data.get("code", ""),
                        plc_data.get("requested_control"),
                    )
                st.session_state["simulating"] = False
                st.rerun()

            if "sim_result" in st.session_state:
                sim_result = st.session_state["sim_result"]
                current_source_hash = hashlib.sha256(
                    plc_data.get("code", "").encode("utf-8")
                ).hexdigest()
                result_is_current = sim_result.get("source_hash") == current_source_hash

                if not result_is_current:
                    st.warning("目前驗證結果屬於上一份 ST，請重新執行 Compile + Simulate。")

                # --- 1.5a 編譯檢查 (matiec) ---
                st.markdown("#### 🛠️ Compile Check (matiec)")
                compile_result = sim_result.get("compile") or {}
                compile_status = compile_result.get("status")
                compile_issues = compile_result.get("issues", [])
                contract_result = sim_result.get("contract") or {}

                if compile_status == "compiled":
                    st.success("matiec 編譯通過，未發現語法/型別錯誤。")
                elif compile_status == "iec2c_unavailable":
                    st.warning("編譯工具鏈不可用，已略過此階段。")
                elif compile_status == "wrapper_synthesis_failed":
                    st.error("找不到可編譯的 PROGRAM/FUNCTION_BLOCK，無法產生包裝程式。")
                else:
                    st.error("matiec 編譯失敗，發現真實的語法/型別錯誤 (Local Validation 的規則式檢查未必能抓到這些)。")

                if compile_issues:
                    with st.expander("🔍 檢視編譯詳細資訊 (Compile Issues)"):
                        for issue in compile_issues:
                            line_info = f" (Line {issue['line']})" if issue.get("line") is not None else ""
                            scope_info = "" if issue.get("in_generated_code", True) else "（位於模擬用的樁函式庫，而非你的程式碼）"
                            msg = f"{issue['message']}{line_info}{scope_info}"
                            if issue["severity"] == "error":
                                st.error(msg)
                            elif issue["severity"] == "warning":
                                st.warning(msg)
                            else:
                                st.info(msg)

                st.markdown("#### 🎯 Motion Request Contract")
                if contract_result.get("status") == "passed":
                    contract_summary = (
                        f"生成程式符合需求模式：{contract_result.get('actual_mode')}"
                    )
                    if contract_result.get("observed_position") is not None:
                        contract_summary += (
                            f"｜Position={contract_result['observed_position']:g}"
                        )
                    if contract_result.get("observed_velocity") is not None:
                        contract_summary += (
                            f"｜Velocity={contract_result['observed_velocity']:g}"
                        )
                    st.success(contract_summary)
                elif contract_result.get("status") == "failed":
                    st.error(
                        f"需求模式為 {contract_result.get('expected_mode')}，"
                        f"實際生成為 {contract_result.get('actual_mode')}；已阻止 Runtime 與 Twin 部署。"
                    )
                    for issue in contract_result.get("issues", []):
                        st.error(f"{issue['code']}: {issue['message']}")
                else:
                    st.warning("本次沒有可用的運動需求契約，無法部署至 Twin。")

                # --- 1.5b 模擬部署 (OpenPLC + Modbus) ---
                st.markdown("#### 🧪 Runtime Simulation (OpenPLC + Modbus)")
                st.caption("部署的就是這次生成的程式碼本身 (自動偵測其中的 AXIS_REF 變數與 bEnable 訊號並接上 Modbus)，"
                           "不是固定的參考程式。系統會依實際運動模式驗證啟用、E-Stop、限位、Reset、JOG 啟停或"
                           "Absolute 到位；定位測試會依已驗證的距離與速度計算等待上限並輪詢完成狀態。")
                scenarios_result = sim_result.get("scenarios")

                if scenarios_result is None:
                    st.info("編譯未通過，已略過模擬部署階段。")
                elif scenarios_result.get("status") == "no_axis_interface":
                    st.warning("這次生成的程式碼沒有照規範宣告 AXIS_REF 變數，找不到東西可以接上 Modbus 觀察，已略過模擬部署階段。")
                elif scenarios_result.get("status") == "openplc_unavailable":
                    st.warning("OpenPLC 模擬環境不可用，已略過此階段。")
                elif scenarios_result.get("status") == "contract_failed":
                    st.error("生成程式不符合 UI 運動需求，已略過 OpenPLC Runtime 測試。")
                elif scenarios_result.get("status") == "error":
                    st.error(f"模擬部署發生錯誤：{scenarios_result.get('message', '')}")
                else:
                    scenario_runs = scenarios_result.get("results", [])
                    n_passed = sum(1 for r in scenario_runs if r.get("passed"))
                    st.metric(label="情境測試通過數", value=f"{n_passed} / {len(scenario_runs)}")
                    for run in scenario_runs:
                        label = f"{'✅' if run.get('passed') else '❌'} {run['name']}"
                        with st.expander(label):
                            if run.get("error"):
                                st.error(run["error"])
                            for step in run.get("steps", []):
                                st.write(("✅" if step["ok"] else "❌"), "expected:", step["expected"], "| actual:", step["actual"])

                scenario_runs = (
                    scenarios_result.get("results", [])
                    if scenarios_result and scenarios_result.get("status") == "ran"
                    else []
                )
                ready_for_twin = (
                    result_is_current
                    and compile_status == "compiled"
                    and contract_result.get("status") == "passed"
                    and compile_result.get("axis_io_map") is not None
                    and bool(scenario_runs)
                    and all(run.get("passed") for run in scenario_runs)
                )

                st.markdown("#### 🖥️ Deploy to 2D Digital Twin")
                st.caption(
                    "只有本次 ST 的所有 Runtime 情境通過後才能持續部署。"
                    "部署後 OpenPLC Runtime 會保持運行，供 Twin 互動操作。"
                )
                twin_info = load_deployment() if load_deployment else None
                deployed_current = bool(
                    twin_info
                    and twin_info.get("status") == "running"
                    and twin_info.get("source_hash") == current_source_hash
                )

                is_deploying_twin = st.session_state.get("deploying_twin", False)
                twin_cols = st.columns(3)
                if twin_cols[0].button(
                    "⏳ 部署中..." if is_deploying_twin else "🚀 部署至 2D Twin",
                    type="primary",
                    disabled=(
                        not ready_for_twin
                        or is_deploying_twin
                        or deploy_to_twin is None
                    ),
                    use_container_width=True,
                ):
                    st.session_state["deploying_twin"] = True
                    st.rerun()

                if is_deploying_twin:
                    with st.spinner("正在重新部署並保持 OpenPLC Runtime 運行..."):
                        st.session_state["twin_deploy_result"] = deploy_to_twin(
                            compile_result.get("full_source", ""),
                            plc_data.get("code", ""),
                            contract_result.get("actual_mode", "Unknown"),
                            contract=contract_result,
                            command_map=compile_result.get("axis_command_map"),
                        )
                    st.session_state["deploying_twin"] = False
                    st.rerun()

                if twin_cols[1].button(
                    "⏹️ 停止 Twin Runtime",
                    disabled=not twin_info or twin_info.get("status") != "running",
                    use_container_width=True,
                ):
                    st.session_state["twin_deploy_result"] = stop_twin()
                    st.rerun()

                twin_cols[2].link_button(
                    "↗️ 開啟 2D Twin",
                    "http://localhost:8504",
                    disabled=not deployed_current,
                    use_container_width=True,
                )

                deploy_result = st.session_state.get("twin_deploy_result")
                if deploy_result:
                    if deploy_result.get("status") == "running":
                        st.success(
                            f"Twin Runtime 已部署：{deploy_result.get('program_name')}｜"
                            f"模式：{deploy_result.get('mode')}"
                        )
                    elif deploy_result.get("status") == "stopped":
                        st.info("Twin Runtime 已停止。")
                    else:
                        st.error(
                            "Twin 部署失敗："
                            f"{deploy_result.get('message', deploy_result.get('status', 'unknown'))}"
                        )

            st.markdown("---")

            # --- 2. 程式碼區 ---
            st.markdown("### 📝 Structured Text Code")
            st.code(plc_data.get("code", ""), language="pascal")
            st.download_button("📥 Download .st", data=plc_data.get("code", ""), file_name="MainProgram.st")

            # --- 3. 變數表 ---
            st.markdown("### 📊 Variable Declaration Table")
            st.markdown(plc_data.get("variables", ""))

            # --- 4. How It Works ---
            st.markdown("### 🏫 How It Works")
            st.markdown(plc_data.get("explanation", ""))

            # --- 5. Warnings ---
            st.markdown("### ⚠️ Safety Warnings")
            st.markdown(plc_data.get("warnings", ""))
