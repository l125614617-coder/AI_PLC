import pytest

from plc_config import PlcConnection
from twin_client import TwinClient, TwinConnectionError


class _Response:
    def __init__(self, *, bits=None, registers=None, error=False):
        self.bits = bits or []
        self.registers = registers or []
        self._error = error

    def isError(self):
        return self._error


class _Client:
    def __init__(self, connected=True):
        self.connected = connected
        self.closed = False
        self.writes = []
        self.register_writes = []
        self.bits = [False] * 19
        self.registers = [0] * 6

    def connect(self):
        return self.connected

    def close(self):
        self.closed = True

    def read_coils(self, address, count):
        return _Response(bits=self.bits[:count])

    def read_holding_registers(self, address, count):
        return _Response(registers=self.registers[:count])

    def write_coil(self, address, value):
        self.writes.append((address, value))
        return _Response()

    def write_register(self, address, value):
        self.register_writes.append((address, value))
        return _Response()


def _connection():
    return PlcConnection(
        "http://127.0.0.1:8081", "127.0.0.1", 502,
        "openplc", "openplc", False,
    )


def test_reads_scaled_signed_axis_state():
    fake = _Client()
    fake.bits[3] = True
    fake.bits[13] = True
    fake.bits[14] = True
    fake.registers[:] = [0xFFF6, 250, 1000, 300, 2, 4]
    client = TwinClient(_connection(), lambda *args, **kwargs: fake)

    state = client.read_state()

    assert state.enabled is True
    assert state.moving is True
    assert state.reverse is True
    assert state.position == -1.0
    assert state.velocity == 25.0
    assert state.target_position == 100.0
    assert state.error_id == 2
    assert fake.closed is True


def test_only_allows_safe_adapter_commands():
    fake = _Client()
    client = TwinClient(_connection(), lambda *args, **kwargs: fake)

    client.start()
    assert fake.writes == [(8, True)]

    with pytest.raises(ValueError, match="not writable"):
        client.set_signal("enabled", True)


def test_connection_failure_is_clear_and_closes_socket():
    fake = _Client(connected=False)
    client = TwinClient(_connection(), lambda *args, **kwargs: fake)

    with pytest.raises(TwinConnectionError, match="127.0.0.1:502"):
        client.read_state()

    assert fake.closed is True


def test_reset_is_always_released(monkeypatch):
    fake = _Client()
    client = TwinClient(_connection(), lambda *args, **kwargs: fake)
    monkeypatch.setattr("twin_client.time.sleep", lambda duration: None)

    client.pulse_reset()

    assert fake.writes == [(12, True), (12, False)]


def test_absolute_target_writes_registers_and_pulses_apply(monkeypatch):
    fake = _Client()
    client = TwinClient(_connection(), lambda *args, **kwargs: fake)
    monkeypatch.setattr("twin_client.time.sleep", lambda duration: None)

    client.set_absolute_target(-250.5, 200.0)

    assert fake.register_writes == [(6, (-2505) & 0xFFFF), (7, 2000)]
    assert fake.writes == [(15, True), (15, False)]


def test_absolute_target_validates_range_and_speed():
    client = TwinClient(_connection(), lambda *args, **kwargs: _Client())

    with pytest.raises(ValueError, match="大於 0"):
        client.set_absolute_target(100, 0)
    with pytest.raises(ValueError, match="超出目前 Modbus 範圍"):
        client.set_absolute_target(4000, 100)


def test_move_absolute_rearms_execute_in_safe_order(monkeypatch):
    fake = _Client()
    client = TwinClient(_connection(), lambda *args, **kwargs: fake)
    events = []
    state = type("State", (), {"estop": False, "error": False})()
    monkeypatch.setattr(client, "read_state", lambda: state)
    monkeypatch.setattr(client, "stop", lambda: events.append("stop"))
    monkeypatch.setattr(
        client,
        "set_absolute_target",
        lambda position, velocity: events.append(("target", position, velocity)),
    )
    monkeypatch.setattr(client, "start", lambda: events.append("start"))
    monkeypatch.setattr("twin_client.time.sleep", lambda duration: None)

    client.move_absolute(500, 100)

    assert events == ["stop", ("target", 500, 100), "start"]


def test_move_absolute_rejects_target_outside_soft_limits(monkeypatch):
    client = TwinClient(_connection(), lambda *args, **kwargs: _Client())
    monkeypatch.setattr(client, "read_state", lambda: pytest.fail("must reject before I/O"))

    with pytest.raises(ValueError, match="超出模擬軟限位"):
        client.move_absolute(-1100, 200, -1000, 1000)


def test_configure_soft_limits_writes_limits_then_enables_plc_scan_logic():
    fake = _Client()
    client = TwinClient(_connection(), lambda *args, **kwargs: fake)

    client.configure_soft_limits(-1000.0, 1000.0)

    assert fake.register_writes == [(8, (-10000) & 0xFFFF), (9, 10000)]
    assert fake.writes == [(16, True)]
