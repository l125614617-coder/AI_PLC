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
