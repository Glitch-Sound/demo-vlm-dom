import json
from pathlib import Path

import httpx
import pytest
from PIL import Image

from app.driving_scene_annotation.analysis import (
    Scene,
    Vehicle,
    is_visually_distant,
    parse_dom_response,
    parse_vlm_response,
)
from app.driving_scene_annotation.config import load_settings
from app.driving_scene_annotation.images import SourceImage, prepare_inference
from app.driving_scene_annotation.ollama_client import DOM_CRITERIA, OllamaClient


def _vlm(vehicles: list[dict[str, object]]) -> str:
    return json.dumps(
        {
            "scene_description": "A marked road",
            "camera_lane": "center",
            "vehicles": vehicles,
        }
    )


def _vehicle(
    vehicle_id: str, box: list[int], relation: str = "ahead"
) -> dict[str, object]:
    return {
        "id": vehicle_id,
        "bbox": box,
        "path_relation": relation,
        "evidence": "Visible lane markings" if relation != "unknown" else "",
    }


def test_accepts_vehicle_coordinates_and_evidence() -> None:
    scene = parse_vlm_response(
        _vlm([_vehicle("v1", [10, 5, 20, 15])]), (100, 50), (200, 100)
    )

    assert scene.description == "A marked road"
    assert scene.camera_lane == "center"
    assert scene.vehicles == [
        Vehicle("v1", (20, 10, 40, 30), "ahead", "Visible lane markings")
    ]
    assert scene.discarded == []


def test_drops_invalid_box() -> None:
    scene = parse_vlm_response(
        _vlm(
            [
                _vehicle("reverse", [20, 0, 10, 5]),
                _vehicle("outside", [-1, 0, 10, 5]),
                _vehicle("edge", [0, 0, 100, 50]),
            ]
        ),
        (100, 50),
        (200, 100),
    )

    assert [vehicle.id for vehicle in scene.vehicles] == ["edge"]
    assert scene.vehicles[0].box == (0, 0, 200, 100)
    assert len(scene.discarded) == 2
    assert "reverse" in scene.discarded[0]
    assert "outside" in scene.discarded[1]


@pytest.mark.parametrize(
    "payload",
    [
        "not JSON",
        json.dumps({"scene_description": "road"}),
        _vlm([_vehicle("same", [0, 0, 10, 10]), _vehicle("same", [10, 10, 20, 20])]),
        _vlm([_vehicle("v1", [True, 0, 10, 10])]),
        json.dumps({"scene_description": "road", "camera_lane": [], "vehicles": []}),
        json.dumps(
            {"scene_description": "road", "camera_lane": "lane_9", "vehicles": []}
        ),
    ],
)
def test_rejects_invalid_vlm_result(payload: str) -> None:
    with pytest.raises(ValueError):
        parse_vlm_response(payload, (100, 50), (200, 100))


def test_maps_priority_choices() -> None:
    assert "Being ahead alone does not qualify" in DOM_CRITERIA["high"]
    for priority in ("high", "medium", "low"):
        assert (
            parse_dom_response(
                {"answers": {"v1": {"type": "choice", "choice": priority}}}, "v1"
            )
            == priority
        )


@pytest.mark.parametrize(
    "camera_lane,relation",
    [
        ("unknown", "ahead"),
        ("center", "unknown"),
    ],
)
def test_marks_unknown_without_choice(camera_lane: str, relation: str) -> None:
    settings = load_settings(Path("config/setting.ini"))
    transport = httpx.MockTransport(
        lambda _request: pytest.fail("DOM must not be called")
    )
    scene = Scene(
        "road",
        [Vehicle("v1", (0, 0, 10, 10), relation, "")],
        [],
        camera_lane,
        100,
    )

    with OllamaClient(settings, httpx.Client(transport=transport)) as client:
        assert client.classify(scene, scene.vehicles[0]) == "undetermined"


def test_marks_visually_distant_vehicle_low() -> None:
    settings = load_settings(Path("config/setting.ini"))
    near = Vehicle("near", (0, 500, 200, 700), "same camera lane", "ahead")
    far = Vehicle("far", (300, 300, 330, 350), "unknown", "")
    scene = Scene("road", [near, far], [], "center", 1000)
    assert not is_visually_distant(scene, near)
    assert is_visually_distant(scene, far)

    transport = httpx.MockTransport(
        lambda _request: pytest.fail("DOM must not be called for distant vehicles")
    )
    with OllamaClient(settings, httpx.Client(transport=transport)) as client:
        assert client.classify(scene, far) == "low"

    boundary = Vehicle("boundary", (0, 0, 100, 80), "same camera lane", "ahead")
    assert not is_visually_distant(
        Scene("road", [boundary], [], "center", 1000), boundary
    )
    relative = Vehicle("relative", (0, 0, 100, 100), "same camera lane", "ahead")
    tall = Vehicle("tall", (200, 0, 400, 300), "same camera lane", "ahead")
    assert is_visually_distant(
        Scene("road", [relative, tall], [], "center", 1000), relative
    )
    relative_boundary = Vehicle(
        "relative_boundary", (0, 0, 100, 120), "same camera lane", "ahead"
    )
    assert not is_visually_distant(
        Scene("road", [relative_boundary, tall], [], "center", 1000),
        relative_boundary,
    )


@pytest.mark.parametrize(
    "response",
    [
        {"answers": {}},
        {"answers": {"v1": {"type": "choice", "choice": "urgent"}}},
        {"answers": {"v1": {"type": "score", "choice": "high"}}},
    ],
)
def test_rejects_invalid_dom_choice(response: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        parse_dom_response(response, "v1")


def test_resizes_and_maps_box_to_source() -> None:
    source = SourceImage(Image.new("RGB", (4000, 3000)), "PNG")
    inference = prepare_inference(source, 1280, 720)
    assert inference.size == (960, 720)

    scene = parse_vlm_response(
        _vlm([_vehicle("v1", [96, 72, 480, 360])]), inference.size, source.size
    )
    assert scene.vehicles[0].box == (400, 300, 2000, 1500)

    small = SourceImage(Image.new("RGB", (640, 360)), "PNG")
    assert prepare_inference(small, 1280, 720).size == small.size
