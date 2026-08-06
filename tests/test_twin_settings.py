import twin_settings


def test_settings_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(twin_settings, "SETTINGS_FILE", tmp_path / "settings.json")

    saved = twin_settings.save_settings({
        "display_min": -1500,
        "display_max": 1500,
        "limit_negative": -900,
        "limit_positive": 900,
    })

    assert twin_settings.load_settings() == saved


def test_invalid_settings_are_rejected():
    try:
        twin_settings.validate_settings({
            "display_min": -1000,
            "display_max": 1000,
            "limit_negative": 500,
            "limit_positive": -500,
        })
    except ValueError as exc:
        assert "Limit +" in str(exc)
    else:
        raise AssertionError("invalid limits must be rejected")
