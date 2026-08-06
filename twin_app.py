"""Streamlit 2D digital-twin dashboard for the PLC-Assist axis adapter."""

from __future__ import annotations

import streamlit as st

from plc_config import load_plc_connection
from twin_client import TwinClient, TwinConnectionError, TwinState, effective_display_range
from twin_deployment import load_deployment
from twin_settings import load_settings, save_settings


st.set_page_config(page_title="PLC-Assist 2D Twin", page_icon="⚙️", layout="wide")


@st.cache_resource
def get_twin_client() -> TwinClient:
    return TwinClient()


def run_command(label: str, command) -> None:
    try:
        command()
        st.session_state["twin_message"] = ("success", f"{label}命令已送出")
    except (TwinConnectionError, ValueError) as exc:
        st.session_state["twin_message"] = ("error", str(exc))


def axis_svg(
    state: TwinState,
    minimum: float,
    maximum: float,
    limit_negative: float | None = None,
    limit_positive: float | None = None,
) -> str:
    span = max(maximum - minimum, 1.0)
    ratio = min(1.0, max(0.0, (state.position - minimum) / span))
    x = 55 + ratio * 790
    color = "#ef4444" if state.error or state.estop else ("#22c55e" if state.moving else "#3b82f6")
    arrow = "→" if state.velocity > 0 else ("←" if state.velocity < 0 else "■")
    limit_marks = ""
    for value, label in ((limit_negative, "Limit -"), (limit_positive, "Limit +")):
        if value is not None and minimum <= value <= maximum:
            limit_x = 55 + ((value - minimum) / span) * 790
            limit_marks += (
                f'<line x1="{limit_x:.1f}" y1="105" x2="{limit_x:.1f}" y2="158" '
                'stroke="#ef4444" stroke-width="4"/>'
                f'<text x="{limit_x:.1f}" y="181" text-anchor="middle" '
                f'font-size="14" fill="#fca5a5">{label} {value:.1f}</text>'
            )
    return f"""
    <svg viewBox="0 0 900 220" width="100%" role="img" aria-label="虛擬馬達位置">
      <defs><linearGradient id="rail" x1="0" x2="1"><stop stop-color="#64748b"/><stop offset="1" stop-color="#cbd5e1"/></linearGradient></defs>
      <rect x="35" y="35" width="830" height="155" rx="18" fill="#0f172a"/>
      <line x1="55" y1="132" x2="845" y2="132" stroke="url(#rail)" stroke-width="12" stroke-linecap="round"/>
      <line x1="55" y1="100" x2="55" y2="165" stroke="#f59e0b" stroke-width="6"/>
      <line x1="845" y1="100" x2="845" y2="165" stroke="#f59e0b" stroke-width="6"/>
      {limit_marks}
      <g transform="translate({x:.1f}, 110)">
        <rect x="-38" y="-42" width="76" height="72" rx="12" fill="{color}"/>
        <circle cx="0" cy="-6" r="19" fill="#e2e8f0" stroke="#334155" stroke-width="5"/>
        <text x="0" y="-1" text-anchor="middle" font-size="18" fill="#0f172a">⚙</text>
        <text x="0" y="58" text-anchor="middle" font-size="27" fill="#f8fafc">{arrow}</text>
      </g>
      <text x="55" y="87" font-size="16" fill="#fbbf24">{minimum:.1f} mm</text>
      <text x="845" y="87" text-anchor="end" font-size="16" fill="#fbbf24">{maximum:.1f} mm</text>
      <text x="450" y="67" text-anchor="middle" font-size="21" fill="#f8fafc">Position {state.position:.1f} mm</text>
    </svg>
    """


connection = load_plc_connection()
client = get_twin_client()
deployment = load_deployment()
runtime_authorized = bool(deployment and deployment.get("status") == "running")
interactive_absolute = bool(
    runtime_authorized
    and deployment.get("mode") == "Absolute Position"
    and deployment.get("interactive_target")
)
saved_settings = load_settings()
for setting_key, setting_value in saved_settings.items():
    st.session_state.setdefault(f"twin_{setting_key}", setting_value)

st.title("⚙️ PLC-Assist 2D Digital Twin")
st.caption(
    f"Modbus TCP：{connection.modbus_host}:{connection.modbus_port}｜"
    "畫面命令必須以 PLC 回傳狀態為準"
)

if runtime_authorized:
    target_text = (
        f"｜Target={deployment['target_position']:g} mm"
        if deployment.get("target_position") is not None
        else ""
    )
    st.success(
        f"已部署：{deployment.get('program_name', 'Unknown')}｜"
        f"模式：{deployment.get('mode', 'Unknown')}{target_text}"
    )
else:
    st.warning("尚未由 PLC-Assist 持續部署程式；控制按鈕已停用。請先在驗證結果按『部署至 2D Twin』。")

with st.sidebar:
    st.header("顯示範圍")
    with st.form("display_range_settings", border=False):
        display_min_input = st.number_input(
            "顯示最小值 (mm)", value=float(st.session_state["twin_display_min"]), step=100.0
        )
        display_max_input = st.number_input(
            "顯示最大值 (mm)", value=float(st.session_state["twin_display_max"]), step=100.0
        )
        apply_display = st.form_submit_button("儲存顯示範圍", use_container_width=True)
    if apply_display:
        try:
            updated = save_settings({
                "display_min": display_min_input,
                "display_max": display_max_input,
                "limit_negative": st.session_state["twin_limit_negative"],
                "limit_positive": st.session_state["twin_limit_positive"],
            })
            st.session_state["twin_display_min"] = updated["display_min"]
            st.session_state["twin_display_max"] = updated["display_max"]
            st.success("顯示範圍已保存")
        except ValueError as exc:
            st.error(str(exc))
    axis_min = float(st.session_state["twin_display_min"])
    axis_max = float(st.session_state["twin_display_max"])
    st.divider()
    st.header("模擬軟限位")
    with st.form("soft_limit_settings", border=False):
        limit_negative_input = st.number_input(
            "Limit - (mm)",
            value=float(st.session_state["twin_limit_negative"]),
            min_value=-3276.8,
            max_value=3276.7,
            step=100.0,
        )
        limit_positive_input = st.number_input(
            "Limit + (mm)",
            value=float(st.session_state["twin_limit_positive"]),
            min_value=-3276.8,
            max_value=3276.7,
            step=100.0,
        )
        apply_limits = st.form_submit_button("套用限位", use_container_width=True)
    if apply_limits:
        try:
            updated = save_settings({
                "display_min": st.session_state["twin_display_min"],
                "display_max": st.session_state["twin_display_max"],
                "limit_negative": limit_negative_input,
                "limit_positive": limit_positive_input,
            })
            client.configure_soft_limits(
                updated["limit_negative"], updated["limit_positive"]
            )
            st.session_state["twin_limit_negative"] = updated["limit_negative"]
            st.session_state["twin_limit_positive"] = updated["limit_positive"]
            st.session_state["soft_limits_applied_to"] = (deployment or {}).get("program_name")
            st.success("模擬軟限位已保存並套用至 PLC")
        except (TwinConnectionError, ValueError) as exc:
            st.error(str(exc))
    limit_negative = float(st.session_state["twin_limit_negative"])
    limit_positive = float(st.session_state["twin_limit_positive"])
    st.caption(f"有效範圍：{limit_negative:g} ～ {limit_positive:g} mm")
    if runtime_authorized and (deployment or {}).get("adapter_version", 0) < 2:
        st.warning("目前部署版本尚未支援 PLC 掃描週期軟限位，請重新編譯驗證並部署。")
    st.divider()
    st.warning("E-Stop 與軟限位僅為模擬訊號，不能取代實機安全迴路與限位開關。")

buttons = st.columns(6)
buttons[0].button("▶ 啟動", type="primary", disabled=not runtime_authorized, use_container_width=True, on_click=run_command, args=("啟動", client.start))
buttons[1].button("■ 停止", disabled=not runtime_authorized, use_container_width=True, on_click=run_command, args=("停止", client.stop))
buttons[2].button("⇄ 切換方向", disabled=not runtime_authorized, use_container_width=True, on_click=run_command, args=("方向切換", lambda: client.set_signal("reverse", not st.session_state.get("last_reverse", False))))
buttons[3].button("↺ Reset", disabled=not runtime_authorized, use_container_width=True, on_click=run_command, args=("Reset", client.pulse_reset))
buttons[4].button("⛔ E-Stop", disabled=not runtime_authorized, use_container_width=True, on_click=run_command, args=("E-Stop", lambda: client.set_signal("estop", True)))
buttons[5].button("解除 E-Stop", disabled=not runtime_authorized, use_container_width=True, on_click=run_command, args=("解除 E-Stop", lambda: client.set_signal("estop", False)))

@st.fragment
def absolute_command_panel() -> None:
    st.subheader("🎯 Absolute Position 互動命令")
    if deployment and deployment.get("mode") == "Absolute Position" and not interactive_absolute:
        st.warning("這份程式的 Position／Velocity 不是可寫入變數，請重新生成並部署符合規範的程式。")
    default_target = float((deployment or {}).get("target_position", 0.0))
    default_velocity = abs(float((deployment or {}).get("target_velocity", 100.0))) or 100.0
    with st.form("absolute_position_command", border=True):
        target_cols = st.columns([2, 2, 2])
        target_position = target_cols[0].number_input(
            "新目標位置 (mm)",
            min_value=-3276.8,
            max_value=3276.7,
            value=min(3276.7, max(-3276.8, default_target)),
            step=10.0,
            disabled=not interactive_absolute,
        )
        target_velocity = target_cols[1].number_input(
            "移動速度",
            min_value=0.1,
            max_value=3276.7,
            value=min(3276.7, max(0.1, default_velocity)),
            step=10.0,
            disabled=not interactive_absolute,
        )
        submitted = target_cols[2].form_submit_button(
            "移動至目標",
            type="primary",
            disabled=not interactive_absolute,
            use_container_width=True,
        )
    if submitted:
        try:
            with st.spinner("正在套用新目標..."):
                client.move_absolute(
                    target_position,
                    target_velocity,
                    limit_negative,
                    limit_positive,
                )
            st.success(
                f"定位命令已送出：Position={target_position:g} mm｜"
                f"Velocity={target_velocity:g}"
            )
        except (TwinConnectionError, ValueError) as exc:
            st.error(str(exc))
    st.caption("命令會先解除舊 Execute，再寫入新目標並重新觸發 MC_MoveAbsolute；目前位置範圍受 16-bit Modbus 限制。")


absolute_command_panel()

message = st.session_state.pop("twin_message", None)
if message:
    getattr(st, message[0])(message[1])


@st.fragment(run_every=0.5)
def live_panel() -> None:
    try:
        state = client.read_state()
        st.session_state["last_reverse"] = state.reverse
        deployment_name = (deployment or {}).get("program_name")
        if (
            runtime_authorized
            and (deployment or {}).get("adapter_version", 0) >= 2
            and st.session_state.get("soft_limits_applied_to") != deployment_name
        ):
            client.configure_soft_limits(limit_negative, limit_positive)
            st.session_state["soft_limits_applied_to"] = deployment_name
    except TwinConnectionError as exc:
        st.error(f"Twin 離線：{exc}。請先啟動 OpenPLC 並部署含 AXIS_REF adapter 的程式。")
        return

    status = "E-STOP" if state.estop else ("FAULT" if state.error else ("MOVING" if state.moving else "STOPPED"))
    metrics = st.columns(6)
    metrics[0].metric("狀態", status)
    metrics[1].metric("位置", f"{state.position:.1f} mm")
    metrics[2].metric("速度", f"{state.velocity:.1f} mm/s")
    metrics[3].metric("目標位置", f"{state.target_position:.1f} mm")
    metrics[4].metric("Axis State", state.axis_state)
    metrics[5].metric("Error ID", state.error_id)

    if axis_max > axis_min:
        display_min, display_max = effective_display_range(
            axis_min,
            axis_max,
            min(state.position, state.target_position, limit_negative, limit_positive),
            max(state.position, state.target_position, limit_negative, limit_positive),
        )
        st.markdown(
            axis_svg(
                state, display_min, display_max, limit_negative, limit_positive
            ),
            unsafe_allow_html=True,
        )
        if display_min != axis_min or display_max != axis_max:
            st.caption(
                f"目前位置、目標或限位超出設定範圍，尺規已自動擴展為 "
                f"{display_min:.1f} ～ {display_max:.1f} mm（僅影響畫面顯示）。"
            )

    flags = st.columns(8)
    for column, (name, value) in zip(flags, (
        ("Enabled", state.enabled), ("Busy", state.busy), ("Active", state.active),
        ("Done", state.done), ("Moving", state.moving), ("Reverse", state.reverse),
        ("Limit -", state.limit_negative), ("Limit +", state.limit_positive),
    )):
        column.markdown(f"**{'🟢' if value else '⚪'} {name}**")


live_panel()
