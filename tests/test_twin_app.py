from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from twin_client import TwinState, effective_display_range


STATE = TwinState(
    busy=False,
    done=True,
    error=False,
    enabled=True,
    active=False,
    aborted=False,
    in_velocity=False,
    moving=False,
    estop=False,
    limit_positive=False,
    limit_negative=False,
    reverse=False,
    position=1000.0,
    velocity=0.0,
    target_position=1000.0,
    target_velocity=200.0,
    error_id=0,
    axis_state=1,
)


def test_display_range_expands_for_position_outside_configured_scale():
    minimum, maximum = effective_display_range(-1000.0, 1000.0, -1100.0, -1100.0)

    assert minimum < -1100.0
    assert maximum == 1000.0


def test_display_range_stays_fixed_when_position_and_target_are_inside():
    assert effective_display_range(-1000.0, 1000.0, 250.0, 900.0) == (-1000.0, 1000.0)


def test_interactive_absolute_panel_sends_new_target():
    deployment = {
        "status": "running",
        "program_name": "absolute_demo",
        "mode": "Absolute Position",
        "target_position": 1000.0,
        "target_velocity": 200.0,
        "interactive_target": True,
    }
    settings = {
        "display_min": -1000.0,
        "display_max": 1000.0,
        "limit_negative": -1000.0,
        "limit_positive": 1000.0,
    }
    with patch("twin_deployment.load_deployment", return_value=deployment), patch(
        "twin_settings.load_settings", return_value=settings
    ), patch(
        "twin_client.TwinClient.read_state", return_value=STATE
    ), patch("twin_client.TwinClient.move_absolute") as move:
        app = AppTest.from_file("twin_app.py", default_timeout=30).run()
        position = next(n for n in app.number_input if n.label == "新目標位置 (mm)")
        velocity = next(n for n in app.number_input if n.label == "移動速度")
        position.set_value(500.0)
        velocity.set_value(100.0)
        app.run()
        button = next(b for b in app.button if b.label == "移動至目標")
        assert not button.disabled
        app = button.click().run()

    assert not app.exception
    move.assert_called_once_with(500.0, 100.0, -1000.0, 1000.0)
    assert any("Position=500 mm" in message.value for message in app.success)


def test_interactive_panel_is_disabled_without_compiler_binding():
    deployment = {
        "status": "running",
        "program_name": "literal_target",
        "mode": "Absolute Position",
        "interactive_target": False,
    }
    with patch("twin_deployment.load_deployment", return_value=deployment), patch(
        "twin_client.TwinClient.read_state", return_value=STATE
    ):
        app = AppTest.from_file("twin_app.py", default_timeout=30).run()

    button = next(b for b in app.button if b.label == "移動至目標")
    assert button.disabled
    assert any("不是可寫入變數" in warning.value for warning in app.warning)
