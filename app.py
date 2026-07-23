import streamlit as st
import re
from ollama import Client

# 匯入輕量本地驗證引擎
from validator import validate_st_code

# 匯入編譯檢查 (matiec) 與模擬部署 (OpenPLC + Modbus) 引擎 -- 選用，缺少工具鏈時優雅降級
try:
    from compiler import compile_st_code, iec2c_available
    from simulator import run_all_scenarios, openplc_available
    from scenarios import ALL_SCENARIOS
    _SIMULATION_IMPORT_ERROR = None
except Exception as _e:  # 例如缺少 pymodbus/requests，或路徑尚未設定好
    _SIMULATION_IMPORT_ERROR = str(_e)

# ==========================================
# 1. 基礎設定與快取連線
# ==========================================
@st.cache_resource
def get_ollama_client():
    return Client(host="http://localhost:11434")

client = get_ollama_client()
MODEL_NAME = "qwen3.5:9b"

st.set_page_config(page_title="PLC-Assist 結構化文字生成器", layout="wide")

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
    "   Position, Velocity, Busy, Done, Active, Error, ErrorID, Enabled, Homed, InVelocity (皆為唯讀狀態)。\n\n"
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
    "   END_PROGRAM\n"
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
        "請確保有處理極限限制與復歸 (Reset) 的邏輯。"
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
def run_compile_and_simulate(code: str) -> dict:
    """Stage 2 (matiec 真實編譯檢查) + Stages 3-5 (部署到 OpenPLC 並跑 Modbus 情境測試)。
    與 validate_st_code 不同，這裡會啟動外部程序、耗時 15-45 秒，因此只在使用者主動點擊時執行。

    情境測試跑的就是『這次 LLM 產生的程式碼』本身：compiler.py 會自動偵測程式碼裡宣告的
    AXIS_REF 變數與 (system prompt 規定的) bEnable 訊號，把它們接到固定的 Modbus 位址上，
    讓底下的情境測試可以不管 LLM 這次取了什麼變數名稱，直接驅動並觀察它的實際行為。
    如果這次生成的程式碼沒有照規範宣告 AXIS_REF 變數 (compile['axis_io_map'] 會是 None)，
    就沒有東西可以這樣接，只能停在「有沒有編過」，不會嘗試部署模擬。"""
    result = {"compile": None, "scenarios": None}

    if _SIMULATION_IMPORT_ERROR:
        result["compile"] = {
            "status": "iec2c_unavailable",
            "issues": [{"severity": "error",
                        "message": f"編譯/模擬模組載入失敗：{_SIMULATION_IMPORT_ERROR}（請執行 setup/setup_windows_toolchain.ps1）",
                        "line": None, "in_generated_code": False}],
            "wrapper_source": "", "axis_io_map": None, "full_source": "",
        }
        return result

    try:
        result["compile"] = compile_st_code(code)
    except Exception as e:
        result["compile"] = {
            "status": "compile_failed",
            "issues": [{"severity": "error", "message": f"編譯呼叫發生例外：{e}", "line": None, "in_generated_code": False}],
            "wrapper_source": "", "axis_io_map": None, "full_source": "",
        }
        return result

    if result["compile"]["status"] != "compiled":
        return result  # 編不過就不用浪費時間部署了

    axis_io_map = result["compile"].get("axis_io_map")
    if axis_io_map is None:
        result["scenarios"] = {"status": "no_axis_interface"}
        return result

    if not openplc_available():
        result["scenarios"] = {"status": "openplc_unavailable"}
        return result

    try:
        full_source = result["compile"]["full_source"]
        result["scenarios"] = {"status": "ran", "results": run_all_scenarios(ALL_SCENARIOS, axis_io_map, full_source)}
    except Exception as e:
        result["scenarios"] = {"status": "error", "message": str(e)}

    return result


# ==========================================
# 5. 前端 UI 介面層
# ==========================================
st.title("⚙️ Generate Structured Text (PLC-Assist 專業版)")
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
        "🧠 顯示思考過程 (Chain-of-Thought)",
        value=False,
        help="關閉 (預設)：快速模式，不顯示思考——實測對這組規範較多的 system prompt 更穩定。"
             "開啟：顯示模型推理過程，但這個模型在規則較複雜時容易陷入反覆推敲、"
             "甚至耗盡整個 token 預算導致完全沒有輸出程式碼，開啟前請留意。",
        disabled=is_generating,
    )
    # 生成中鎖定按鈕，避免重複提交
    if st.button(
        "⏳ 生成中..." if is_generating else "🚀 Generate ST Code",
        type="primary",
        use_container_width=True,
        disabled=is_generating,
    ):
        st.session_state["generating"] = True
        st.rerun()

with col2:
    if st.session_state.get("generating", False):
        # 即時串流顯示區
        think_area = None
        answer_area = None
        if show_thinking:
            st.markdown("### 🧠 模型思考過程 (即時串流)")
            think_area = st.empty()
        answer_area = st.empty()

        spinner_msg = "模型思考中..." if show_thinking else "快速生成 ST Code..."
        with st.spinner(spinner_msg):
            st.session_state["plc_data"] = ask_ai_plc_assistant(
                st.session_state.get("system_prompt", DEFAULT_SYSTEM_PROMPT),
                st.session_state.get("user_prompt", ""),
                think=show_thinking,
                think_area=think_area,
                answer_area=answer_area,
            )
            st.session_state["generated"] = True
        st.session_state["generating"] = False
        st.rerun()

    if st.session_state.get("generated", False):
        plc_data = st.session_state["plc_data"]

        if "error" in plc_data:
            st.error(f"Generation Failed: {plc_data['error']}")
        else:
            # --- 0. 模型思考過程 (Chain-of-Thought) ---
            thinking = plc_data.get("thinking", "")
            if thinking:
                with st.expander("🧠 模型思考過程 (Chain-of-Thought)", expanded=True):
                    st.markdown(thinking)
                st.markdown("---")
            elif plc_data.get("think_requested"):
                st.info("ℹ️ 已開啟思考模式，但本次未取得思考內容（模型可能直接輸出答案）。")
                st.markdown("---")

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
                    st.session_state["sim_result"] = run_compile_and_simulate(plc_data.get("code", ""))
                st.session_state["simulating"] = False
                st.rerun()

            if "sim_result" in st.session_state:
                sim_result = st.session_state["sim_result"]

                # --- 1.5a 編譯檢查 (matiec) ---
                st.markdown("#### 🛠️ Compile Check (matiec)")
                compile_result = sim_result.get("compile") or {}
                compile_status = compile_result.get("status")
                compile_issues = compile_result.get("issues", [])

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

                # --- 1.5b 模擬部署 (OpenPLC + Modbus) ---
                st.markdown("#### 🧪 Runtime Simulation (OpenPLC + Modbus)")
                st.caption("部署的就是這次生成的程式碼本身 (自動偵測其中的 AXIS_REF 變數與 bEnable 訊號並接上 Modbus)，"
                           "不是固定的參考程式——但只驗證 MC_Power 的啟用/緊急停止回應，這是不管生成的程式用哪個"
                           "運動控制函式方塊都通用的行為；更細節的動作正確性 (例如有沒有真的移動到定位) 目前還沒涵蓋。")
                scenarios_result = sim_result.get("scenarios")

                if scenarios_result is None:
                    st.info("編譯未通過，已略過模擬部署階段。")
                elif scenarios_result.get("status") == "no_axis_interface":
                    st.warning("這次生成的程式碼沒有照規範宣告 AXIS_REF 變數，找不到東西可以接上 Modbus 觀察，已略過模擬部署階段。")
                elif scenarios_result.get("status") == "openplc_unavailable":
                    st.warning("OpenPLC 模擬環境不可用，已略過此階段。")
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
