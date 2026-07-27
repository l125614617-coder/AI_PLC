import service_manager


class _Process:
    pid = 4321

    def poll(self):
        return None


def test_start_tracks_owned_process(monkeypatch, tmp_path):
    monkeypatch.setattr(service_manager, "RUN_DIR", tmp_path)
    monkeypatch.setattr(service_manager, "STATE_FILE", tmp_path / "state.json")
    calls = {"count": 0}

    def becomes_healthy(service):
        calls["count"] += 1
        return calls["count"] >= 2

    monkeypatch.setattr(service_manager, "healthy", becomes_healthy)
    monkeypatch.setattr(service_manager.subprocess, "Popen", lambda *args, **kwargs: _Process())
    monkeypatch.setattr(service_manager.ServiceManager, "_pid_alive", staticmethod(lambda pid: True))
    monkeypatch.setattr(
        service_manager.ServiceManager,
        "_pid_command",
        staticmethod(lambda pid: str(service_manager.ROOT / "app_codex.py")),
    )
    monkeypatch.setattr(
        service_manager.ServiceManager,
        "_listener_pid",
        staticmethod(lambda service: 4321),
    )

    manager = service_manager.ServiceManager()
    monkeypatch.setattr(manager, "preflight", lambda key: [])
    result = manager.start("ui_codex")

    assert result["owned"] is True
    assert result["pid"] == 4321
    assert manager.state["ui_codex"]["command"][2:5] == [
        "streamlit",
        "run",
        str(service_manager.ROOT / "app_codex.py"),
    ]


def test_online_external_service_is_not_started_or_stopped(monkeypatch, tmp_path):
    monkeypatch.setattr(service_manager, "RUN_DIR", tmp_path)
    monkeypatch.setattr(service_manager, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(service_manager, "healthy", lambda service: True)
    monkeypatch.setattr(
        service_manager.subprocess,
        "Popen",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not start")),
    )

    manager = service_manager.ServiceManager()

    assert manager.start("ollama")["source"] == "external"
    assert manager.stop("ollama")["source"] == "external"


def test_mode_adds_openplc_once(monkeypatch, tmp_path):
    monkeypatch.setattr(service_manager, "RUN_DIR", tmp_path)
    monkeypatch.setattr(service_manager, "STATE_FILE", tmp_path / "state.json")
    manager = service_manager.ServiceManager()
    started = []
    monkeypatch.setattr(manager, "status", lambda key: {"online": False})
    monkeypatch.setattr(manager, "start", lambda key: started.append(key) or {"key": key})

    manager.start_mode("llamacpp", include_openplc=True)

    assert started == ["llamacpp", "ui_llamacpp", "openplc"]


def test_msys_path_is_derived_from_project_location():
    converted = service_manager._msys_path(service_manager.ROOT)

    assert converted.lower().endswith("/ai_plc")
    assert converted.startswith("/d/")


def test_preflight_reports_missing_release_dependencies(monkeypatch, tmp_path):
    monkeypatch.setattr(service_manager, "ROOT", tmp_path)
    monkeypatch.setattr(service_manager, "PYTHON", tmp_path / "venv" / "Scripts" / "python.exe")
    manager = service_manager.ServiceManager()

    issues = manager.preflight("llamacpp")

    assert any("llama-server" in issue for issue in issues)
    assert any("27B model" in issue for issue in issues)


def test_owned_pid_requires_matching_command(monkeypatch, tmp_path):
    monkeypatch.setattr(service_manager, "RUN_DIR", tmp_path)
    monkeypatch.setattr(service_manager, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(service_manager, "healthy", lambda service: False)
    monkeypatch.setattr(service_manager.ServiceManager, "_pid_alive", staticmethod(lambda pid: True))
    monkeypatch.setattr(
        service_manager.ServiceManager,
        "_pid_command",
        staticmethod(lambda pid: "unrelated.exe"),
    )
    manager = service_manager.ServiceManager()
    manager.state["ui_codex"] = {"pid": 4321, "fingerprint": "app_codex.py"}

    result = manager.status("ui_codex")

    assert result["owned"] is False
    assert "ui_codex" not in manager.state
