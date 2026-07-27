import pytest

from plc_config import PlcConnection


def _connection(**overrides):
    values = {
        "web_base": "http://127.0.0.1:8081",
        "modbus_host": "127.0.0.1",
        "modbus_port": 502,
        "web_username": "openplc",
        "web_password": "openplc",
        "allow_real_hardware": False,
    }
    values.update(overrides)
    return PlcConnection(**values)


def test_loopback_simulation_is_allowed():
    assert _connection().validate().modbus_port == 502


def test_remote_hardware_requires_explicit_opt_in():
    with pytest.raises(ValueError, match="Non-loopback PLC target refused"):
        _connection(
            web_base="http://192.168.1.20:8080",
            modbus_host="192.168.1.20",
        ).validate()


def test_remote_hardware_can_be_explicitly_enabled():
    connection = _connection(
        web_base="http://192.168.1.20:8080",
        modbus_host="192.168.1.20",
        allow_real_hardware=True,
    )

    assert connection.validate() is connection
