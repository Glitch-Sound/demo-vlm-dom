import json
from pathlib import Path

import pytest
from PIL import Image

from app.driving_scene_annotation.analysis import parse_vlm_response
from app.driving_scene_annotation.images import (
    Annotation,
    prepare_inference,
    read_source,
    write_output,
)


def _source(path: Path, size: tuple[int, int] = (48, 32)) -> None:
    Image.new("RGB", size, "white").save(path)


def test_draws_configured_boxes_in_same_format(tmp_path: Path) -> None:
    png = tmp_path / "input.png"
    jpeg = tmp_path / "input.jpg"
    _source(png)
    _source(jpeg)
    annotations = [
        Annotation((2, 2, 12, 12), "#FF0000"),
        Annotation((16, 2, 26, 12), "#FFFF00"),
        Annotation((30, 2, 40, 12), "#0000FF"),
    ]
    output_png = tmp_path / "output.png"
    output_jpeg = tmp_path / "output.jpg"
    write_output(read_source(png), annotations, 3, output_png)
    write_output(read_source(jpeg), annotations, 3, output_jpeg)

    with Image.open(output_png) as result:
        assert result.format == "PNG"
        assert result.size == (48, 32)
        assert result.getpixel((2, 2)) == (255, 0, 0)
        assert result.getpixel((16, 2)) == (255, 255, 0)
        assert result.getpixel((30, 2)) == (0, 0, 255)
        assert result.getpixel((2, 4)) == (255, 0, 0)
        assert result.getpixel((5, 5)) == (255, 255, 255)
    with Image.open(output_jpeg) as result:
        assert result.format == "JPEG"
        assert result.size == (48, 32)


def test_writes_unchanged_scene_when_no_vehicles(tmp_path: Path) -> None:
    source_path = tmp_path / "source.png"
    destination = tmp_path / "result.png"
    _source(source_path)

    write_output(read_source(source_path), [], 3, destination)

    with Image.open(destination) as result:
        assert result.format == "PNG"
        assert result.size == (48, 32)
        assert result.getpixel((2, 2)) == (255, 255, 255)


def test_failed_write_preserves_existing_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_path = tmp_path / "source.png"
    destination = tmp_path / "result.png"
    _source(source_path)
    destination.write_bytes(b"previous output")

    def fail_save(*_args: object, **_kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(Image.Image, "save", fail_save)
    with pytest.raises(OSError, match="disk full"):
        write_output(read_source(source_path), [], 3, destination)

    assert destination.read_bytes() == b"previous output"
    assert sorted(path.name for path in tmp_path.iterdir()) == [
        "result.png",
        "source.png",
    ]


def test_success_replaces_existing_output(tmp_path: Path) -> None:
    source_path = tmp_path / "source.png"
    destination = tmp_path / "result.png"
    _source(source_path)
    destination.write_bytes(b"previous output")

    write_output(
        read_source(source_path),
        [Annotation((2, 2, 12, 12), "#FF0000")],
        3,
        destination,
    )

    assert destination.read_bytes() != b"previous output"
    with Image.open(destination) as result:
        assert result.getpixel((2, 2)) == (255, 0, 0)


def test_resized_inference_keeps_source_dimensions(tmp_path: Path) -> None:
    source_path = tmp_path / "large.png"
    destination = tmp_path / "output.png"
    _source(source_path, (1920, 1080))
    source = read_source(source_path)
    inference = prepare_inference(source, 1280, 720)
    response = json.dumps(
        {
            "scene_description": "road",
            "camera_lane": "center",
            "vehicles": [
                {
                    "id": "v1",
                    "bbox": [100, 100, 200, 200],
                    "path_relation": "ahead",
                    "evidence": "lane markings",
                }
            ],
        }
    )
    scene = parse_vlm_response(response, inference.size, source.size)
    assert scene.vehicles[0].box == (150, 150, 300, 300)

    write_output(source, [Annotation(scene.vehicles[0].box, "#FF0000")], 3, destination)

    with Image.open(destination) as result:
        assert result.format == "PNG"
        assert result.size == (1920, 1080)
        assert result.getpixel((150, 150)) == (255, 0, 0)
        assert result.getpixel((100, 100)) == (255, 255, 255)
