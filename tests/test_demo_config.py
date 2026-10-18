from pathlib import Path

import pytest
from PIL import Image

from app.driving_scene_annotation.config import SettingsError, load_settings
from app.driving_scene_annotation.images import SourceImage, prepare_inference


def test_applies_ini_settings(tmp_path: Path) -> None:
    content = Path("config/setting.ini").read_text()
    custom = content.replace("inference_max_width = 1280", "inference_max_width = 640")
    custom = custom.replace("inference_max_height = 720", "inference_max_height = 360")
    custom = custom.replace(
        "preload_timeout_seconds = 600", "preload_timeout_seconds = 12"
    )
    custom = custom.replace(
        "inference_timeout_seconds = 300", "inference_timeout_seconds = 8"
    )
    custom = custom.replace("keep_alive = 10m", "keep_alive = 5m")
    custom = custom.replace("high_color = #FF0000", "high_color = #123456")
    path = tmp_path / "setting.ini"
    path.write_text(custom)

    settings = load_settings(path)

    assert settings.inference_max_width == 640
    assert settings.inference_max_height == 360
    assert settings.preload_timeout_seconds == 12
    assert settings.inference_timeout_seconds == 8
    assert settings.keep_alive == "5m"
    assert settings.color_for("high") == "#123456"
    source = SourceImage(Image.new("RGB", (1920, 1080)), "PNG")
    assert prepare_inference(
        source, settings.inference_max_width, settings.inference_max_height
    ).size == (640, 360)

    for bad_value in ("0", "-1", "2.5"):
        path.write_text(
            custom.replace(
                "inference_max_width = 640", f"inference_max_width = {bad_value}"
            )
        )
        with pytest.raises(SettingsError, match="image.inference_max_width"):
            load_settings(path)
