"""Persistent user settings for the PLC-Assist 2D Twin."""

from __future__ import annotations

import json
from pathlib import Path


SETTINGS_FILE = Path(__file__).resolve().parent / ".runlogs" / "twin-settings.json"
DEFAULT_SETTINGS = {
    "display_min": -1000.0,
    "display_max": 1000.0,
    "limit_negative": -1000.0,
    "limit_positive": 1000.0,
}


def validate_settings(settings: dict) -> dict:
    result = {key: float(settings.get(key, value)) for key, value in DEFAULT_SETTINGS.items()}
    if result["display_max"] <= result["display_min"]:
        raise ValueError("顯示最大值必須大於顯示最小值")
    if result["limit_positive"] <= result["limit_negative"]:
        raise ValueError("Limit + 必須大於 Limit -")
    for key in ("limit_negative", "limit_positive"):
        if not -3276.8 <= result[key] <= 3276.7:
            raise ValueError("模擬軟限位超出 Modbus 範圍 -3276.8～3276.7")
    return result


def load_settings() -> dict:
    try:
        value = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        return validate_settings(value) if isinstance(value, dict) else dict(DEFAULT_SETTINGS)
    except (OSError, ValueError, TypeError):
        return dict(DEFAULT_SETTINGS)


def save_settings(settings: dict) -> dict:
    result = validate_settings(settings)
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary = SETTINGS_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(SETTINGS_FILE)
    return result
