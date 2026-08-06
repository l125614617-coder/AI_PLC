import simulator


class _Response:
    def __init__(self, text="", status_code=200):
        self.text = text
        self.status_code = status_code


class _Session:
    def post(self, url, **kwargs):
        if url.endswith("/upload-program"):
            return _Response("<input value='server-file.st' id='prog_file'>")
        return _Response()

    def get(self, url, **kwargs):
        if url.endswith("/compilation-logs"):
            return _Response("still compiling")
        return _Response()


def test_deploy_program_reports_compile_timeout(monkeypatch):
    monkeypatch.setattr(simulator.requests, "Session", _Session)

    result = simulator.deploy_program("PROGRAM MAIN END_PROGRAM", "timeout", timeout_s=0)

    assert result["status"] == "compile_failed"
    assert "timed out" in result["log"]


def test_signed_register_and_comparisons():
    assert simulator._signed_register(0xFFFF) == -1
    assert simulator._signed_register(123) == 123
    assert simulator._register_matches(-10, {"lt": 0})
    assert simulator._register_matches(10, {"between": [5, 15]})
    assert simulator._register_matches(
        2500,
        {"equals_register": "target_position_x10"},
        {"target_position_x10": 2500},
    )
    assert not simulator._register_matches(20, {"lte": 15})


class _ModbusResponse:
    def __init__(self, *, bits=None, registers=None):
        self.bits = bits or []
        self.registers = registers or []

    def isError(self):
        return False


class _PollingClient:
    def __init__(self, *args, **kwargs):
        self.read_count = 0

    def connect(self):
        return True

    def close(self):
        pass

    def write_coil(self, address, value):
        return _ModbusResponse()

    def read_coils(self, address, count):
        self.read_count += 1
        bits = [False] * count
        bits[1] = self.read_count >= 3  # done
        return _ModbusResponse(bits=bits)

    def read_holding_registers(self, address, count):
        return _ModbusResponse(registers=[1000, 0, 1000, 200, 0, 1])


def test_runtime_step_polls_until_expectation_passes(monkeypatch):
    fake = _PollingClient()
    monkeypatch.setattr(
        simulator,
        "deploy_program",
        lambda *args, **kwargs: {"status": "started", "session": object()},
    )
    monkeypatch.setattr(simulator, "stop_openplc", lambda session: None)
    monkeypatch.setattr(simulator, "ModbusTcpClient", lambda *args, **kwargs: fake)
    scenario = {
        "name": "poll_done",
        "steps": [
            {
                "set": {"start": True},
                "poll_until_s": 0.2,
                "poll_interval_s": 0.001,
                "assert": {"done": True},
                "assert_register": {
                    "position_x10": {"equals_register": "target_position_x10"}
                },
            }
        ],
    }

    result = simulator.run_scenario(
        scenario,
        {"done": 1, "start": 8},
        "SOURCE",
        register_map={
            "position_x10": 0,
            "velocity_x10": 1,
            "target_position_x10": 2,
            "target_velocity_x10": 3,
            "error_id": 4,
            "axis_state": 5,
        },
    )

    assert result["passed"] is True
    assert fake.read_count == 3
