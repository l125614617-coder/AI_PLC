"""Small Modbus control/read layer for the PLC-Assist 2D digital twin."""

from __future__ import annotations

import time
import math
from dataclasses import dataclass
from typing import Callable

from pymodbus.client.sync import ModbusTcpClient

from compiler import (
    AXIS_ADAPTER_COMMAND_MAP,
    AXIS_ADAPTER_IO_MAP,
    AXIS_ADAPTER_REGISTER_MAP,
)
from plc_config import PlcConnection, load_plc_connection


def effective_display_range(
    minimum: float, maximum: float, position: float, target_position: float
) -> tuple[float, float]:
    """Expand a visual scale when live values fall outside its configured range."""
    if maximum <= minimum:
        return minimum, maximum
    span = maximum - minimum
    padding = max(span * 0.05, 10.0)
    live_min = min(position, target_position)
    live_max = max(position, target_position)
    effective_min = live_min - padding if live_min < minimum else minimum
    effective_max = live_max + padding if live_max > maximum else maximum
    return effective_min, effective_max


class TwinConnectionError(RuntimeError):
    """Raised when the Twin cannot communicate with its configured PLC."""


@dataclass(frozen=True)
class TwinState:
    busy: bool
    done: bool
    error: bool
    enabled: bool
    active: bool
    aborted: bool
    in_velocity: bool
    moving: bool
    estop: bool
    limit_positive: bool
    limit_negative: bool
    reverse: bool
    position: float
    velocity: float
    target_position: float
    target_velocity: float
    error_id: int
    axis_state: int


def _signed_register(value: int) -> int:
    return value - 0x10000 if value & 0x8000 else value


class TwinClient:
    """Read and drive the fixed adapter contract injected by ``compiler.py``.

    Connections are deliberately short lived. This makes Streamlit reruns and
    an OpenPLC restart recover cleanly without keeping a stale socket cached.
    """

    def __init__(
        self,
        connection: PlcConnection | None = None,
        client_factory: Callable[..., ModbusTcpClient] = ModbusTcpClient,
    ) -> None:
        self.connection = connection or load_plc_connection()
        self._client_factory = client_factory

    def _open(self):
        client = self._client_factory(
            self.connection.modbus_host,
            port=self.connection.modbus_port,
            timeout=2,
        )
        if not client.connect():
            client.close()
            raise TwinConnectionError(
                "無法連接 Modbus TCP "
                f"{self.connection.modbus_host}:{self.connection.modbus_port}"
            )
        return client

    @staticmethod
    def _require_ok(response, action: str) -> None:
        if response is None or response.isError():
            raise TwinConnectionError(f"Modbus {action}失敗：{response}")

    def read_state(self) -> TwinState:
        client = self._open()
        try:
            coil_count = max(AXIS_ADAPTER_IO_MAP.values()) + 1
            register_count = max(AXIS_ADAPTER_REGISTER_MAP.values()) + 1
            coil_response = client.read_coils(0, coil_count)
            register_response = client.read_holding_registers(0, register_count)
            self._require_ok(coil_response, "讀取 coils")
            self._require_ok(register_response, "讀取 holding registers")

            coils = {
                name: bool(coil_response.bits[address])
                for name, address in AXIS_ADAPTER_IO_MAP.items()
            }
            registers = {
                name: _signed_register(register_response.registers[address])
                for name, address in AXIS_ADAPTER_REGISTER_MAP.items()
            }
            return TwinState(
                busy=coils["busy"],
                done=coils["done"],
                error=coils["error"],
                enabled=coils["enabled"],
                active=coils["active"],
                aborted=coils["aborted"],
                in_velocity=coils["invelocity"],
                moving=coils["moving"],
                estop=coils["estop"],
                limit_positive=coils["limitpos"] or coils["softlimitpos"],
                limit_negative=coils["limitneg"] or coils["softlimitneg"],
                reverse=coils["reverse"],
                position=registers["position_x10"] / 10.0,
                velocity=registers["velocity_x10"] / 10.0,
                target_position=registers["target_position_x10"] / 10.0,
                target_velocity=registers["target_velocity_x10"] / 10.0,
                error_id=registers["error_id"],
                axis_state=registers["axis_state"],
            )
        finally:
            client.close()

    def set_signal(self, signal: str, value: bool) -> None:
        writable = {
            "start", "reverse", "reset", "estop", "limitpos", "limitneg"
        }
        if signal not in writable:
            raise ValueError(f"Twin signal is not writable: {signal}")
        client = self._open()
        try:
            response = client.write_coil(AXIS_ADAPTER_IO_MAP[signal], bool(value))
            self._require_ok(response, f"寫入 {signal}")
        finally:
            client.close()

    def start(self) -> None:
        self.set_signal("start", True)

    def stop(self) -> None:
        self.set_signal("start", False)

    def pulse_reset(self, duration_s: float = 0.1) -> None:
        self.set_signal("reset", True)
        try:
            time.sleep(duration_s)
        finally:
            self.set_signal("reset", False)

    @staticmethod
    def _scaled_register(value: float, label: str, positive: bool = False) -> int:
        numeric = float(value)
        if not math.isfinite(numeric):
            raise ValueError(f"{label}必須是有限數值")
        if positive and numeric <= 0:
            raise ValueError(f"{label}必須大於 0")
        scaled = round(numeric * 10.0)
        if not -32768 <= scaled <= 32767:
            raise ValueError(f"{label}超出目前 Modbus 範圍 -3276.8～3276.7")
        return scaled & 0xFFFF

    def set_absolute_target(
        self, position: float, velocity: float, pulse_s: float = 0.1
    ) -> None:
        position_raw = self._scaled_register(position, "目標位置")
        velocity_raw = self._scaled_register(velocity, "移動速度", positive=True)
        client = self._open()
        applied = False
        try:
            self._require_ok(
                client.write_register(
                    AXIS_ADAPTER_COMMAND_MAP["command_position_x10"], position_raw
                ),
                "寫入目標位置",
            )
            self._require_ok(
                client.write_register(
                    AXIS_ADAPTER_COMMAND_MAP["command_velocity_x10"], velocity_raw
                ),
                "寫入移動速度",
            )
            self._require_ok(
                client.write_coil(AXIS_ADAPTER_COMMAND_MAP["apply_target"], True),
                "套用目標",
            )
            applied = True
            time.sleep(pulse_s)
        finally:
            if applied:
                response = client.write_coil(
                    AXIS_ADAPTER_COMMAND_MAP["apply_target"], False
                )
                self._require_ok(response, "解除套用目標")
            client.close()

    def move_absolute(
        self,
        position: float,
        velocity: float,
        negative_limit: float | None = None,
        positive_limit: float | None = None,
    ) -> None:
        if negative_limit is not None and positive_limit is not None:
            if positive_limit <= negative_limit:
                raise ValueError("Limit + 必須大於 Limit -")
            if not negative_limit <= position <= positive_limit:
                raise ValueError(
                    f"目標位置 {position:g} mm 超出模擬軟限位 "
                    f"{negative_limit:g}～{positive_limit:g} mm"
                )
        state = self.read_state()
        if state.estop:
            raise ValueError("E-Stop 尚未解除，不能送出定位命令")
        if state.error:
            raise ValueError("軸仍在 ErrorStop，請先解除原因並 Reset")
        # MC_MoveAbsolute accepts a new command on Execute's rising edge. Drop
        # start long enough for one 20 ms OpenPLC scan before applying/rearming.
        self.stop()
        time.sleep(0.1)
        self.set_absolute_target(position, velocity)
        self.start()

    def configure_soft_limits(
        self, negative_limit: float, positive_limit: float, enabled: bool = True
    ) -> None:
        if positive_limit <= negative_limit:
            raise ValueError("Limit + 必須大於 Limit -")
        negative_raw = self._scaled_register(negative_limit, "Limit -")
        positive_raw = self._scaled_register(positive_limit, "Limit +")
        client = self._open()
        try:
            self._require_ok(
                client.write_register(
                    AXIS_ADAPTER_COMMAND_MAP["soft_limit_negative_x10"], negative_raw
                ),
                "寫入 Limit -",
            )
            self._require_ok(
                client.write_register(
                    AXIS_ADAPTER_COMMAND_MAP["soft_limit_positive_x10"], positive_raw
                ),
                "寫入 Limit +",
            )
            self._require_ok(
                client.write_coil(
                    AXIS_ADAPTER_COMMAND_MAP["soft_limits_enable"], bool(enabled)
                ),
                "啟用模擬軟限位",
            )
        finally:
            client.close()
