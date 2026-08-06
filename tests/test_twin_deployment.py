import twin_deployment


def test_source_hash_is_stable_and_sensitive():
    assert twin_deployment.source_hash("PROGRAM MAIN") == twin_deployment.source_hash(
        "PROGRAM MAIN"
    )
    assert twin_deployment.source_hash("A") != twin_deployment.source_hash("B")


def test_persistent_deploy_records_identity(monkeypatch, tmp_path):
    monkeypatch.setattr(twin_deployment, "STATE_FILE", tmp_path / "deployment.json")
    monkeypatch.setattr(twin_deployment.time, "time", lambda: 1234567890)
    stops = []
    monkeypatch.setattr(twin_deployment.simulator, "stop_openplc", lambda: stops.append(True))
    monkeypatch.setattr(
        twin_deployment.simulator,
        "deploy_program",
        lambda source, name, timeout_s: {"status": "started", "session": object()},
    )
    monkeypatch.setattr(
        twin_deployment,
        "_ensure_twin_ui",
        lambda: {"state": "ready", "url": "http://127.0.0.1:8504"},
    )

    result = twin_deployment.deploy_to_twin(
        "COMPILED SOURCE",
        "PROGRAM MAIN END_PROGRAM",
        "JOG",
        contract={"observed_velocity": 1500.0, "observed_position": None},
        command_map=None,
    )

    assert result["status"] == "running"
    assert result["program_name"].startswith("twin_jog_")
    assert result["mode"] == "JOG"
    assert result["target_velocity"] == 1500.0
    assert result["interactive_target"] is False
    assert result["twin_url"] == "http://127.0.0.1:8504"
    assert stops == [True]
    assert twin_deployment.load_deployment() == result


def test_failed_deploy_does_not_claim_runtime(monkeypatch, tmp_path):
    monkeypatch.setattr(twin_deployment, "STATE_FILE", tmp_path / "deployment.json")
    monkeypatch.setattr(twin_deployment.simulator, "stop_openplc", lambda: None)
    monkeypatch.setattr(
        twin_deployment.simulator,
        "deploy_program",
        lambda source, name, timeout_s: {
            "status": "compile_failed",
            "log": "bad ST",
        },
    )

    result = twin_deployment.deploy_to_twin("SOURCE", "CODE", "JOG")

    assert result["status"] == "compile_failed"
    assert result["message"] == "bad ST"
    assert twin_deployment.load_deployment()["status"] == "compile_failed"


def test_twin_ui_start_failure_does_not_claim_success(monkeypatch, tmp_path):
    monkeypatch.setattr(twin_deployment, "STATE_FILE", tmp_path / "deployment.json")
    monkeypatch.setattr(twin_deployment.simulator, "stop_openplc", lambda: None)
    monkeypatch.setattr(
        twin_deployment.simulator,
        "deploy_program",
        lambda source, name, timeout_s: {"status": "started"},
    )

    def fail_to_start():
        raise RuntimeError("port unavailable")

    monkeypatch.setattr(twin_deployment, "_ensure_twin_ui", fail_to_start)

    result = twin_deployment.deploy_to_twin("SOURCE", "CODE", "JOG")

    assert result["status"] == "ui_start_failed"
    assert "port unavailable" in result["message"]
    assert twin_deployment.load_deployment()["status"] == "ui_start_failed"


def test_stop_marks_deployment_stopped(monkeypatch, tmp_path):
    monkeypatch.setattr(twin_deployment, "STATE_FILE", tmp_path / "deployment.json")
    twin_deployment._save({"status": "running", "program_name": "demo"})
    calls = []
    monkeypatch.setattr(twin_deployment.simulator, "stop_openplc", lambda: calls.append(True))

    result = twin_deployment.stop_twin()

    assert calls == [True]
    assert result["status"] == "stopped"
    assert twin_deployment.load_deployment()["status"] == "stopped"
