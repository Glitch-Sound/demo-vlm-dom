import json
from pathlib import Path

import httpx
import pytest

from app.driving_scene_annotation.analysis import parse_vlm_response
from app.driving_scene_annotation.config import load_settings
from app.driving_scene_annotation.images import InferenceImage
from app.driving_scene_annotation.ollama_client import ModelError, OllamaClient


def _vlm_text() -> str:
    return json.dumps(
        {
            "scene_description": "A road with one vehicle",
            "camera_lane": "center",
            "vehicles": [
                {
                    "id": "v1",
                    "bbox": [10, 10, 20, 20],
                    "path_relation": "ahead in the same marked lane",
                    "evidence": "lane markings enclose the vehicle",
                }
            ],
        }
    )


def test_preloads_each_model_before_first_inference() -> None:
    settings = load_settings(Path("config/setting.ini"))
    events: list[tuple[str, str]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["keep_alive"] == settings.keep_alive
        if request.url.path == "/api/generate":
            assert body["prompt"] == ""
            assert (
                request.extensions["timeout"]["read"]
                == settings.preload_timeout_seconds
            )
            events.append((body["model"], "preload"))
            return httpx.Response(200, json={"done": True})
        if request.url.path == "/api/chat":
            assert body["format"]["required"] == [
                "scene_description",
                "camera_lane",
                "vehicles",
            ]
            assert body["messages"][0]["images"]
            assert (
                request.extensions["timeout"]["read"]
                == settings.inference_timeout_seconds
            )
            events.append((body["model"], "analyze"))
            return httpx.Response(200, json={"message": {"content": _vlm_text()}})
        assert request.url.path == "/v1/systemone"
        assert "images" not in body
        if "warmup" in body["questions"]:
            assert set(body["questions"]["warmup"]["criteria"]) == {
                "ready",
                "other",
            }
            assert (
                request.extensions["timeout"]["read"]
                == settings.preload_timeout_seconds
            )
            events.append((body["model"], "warmup"))
            return httpx.Response(
                200,
                json={"answers": {"warmup": {"type": "choice", "choice": "other"}}},
            )
        assert body["questions"]["v1"]["type"] == "choice"
        assert set(body["questions"]["v1"]["criteria"]) == {
            "high",
            "medium",
            "low",
            "undetermined",
        }
        events.append((body["model"], "classify"))
        assert (
            request.extensions["timeout"]["read"] == settings.inference_timeout_seconds
        )
        return httpx.Response(
            200, json={"answers": {"v1": {"type": "choice", "choice": "high"}}}
        )

    http_client = httpx.Client(
        base_url=settings.ollama_url, transport=httpx.MockTransport(handle)
    )
    with OllamaClient(settings, http_client) as client:
        raw = client.analyze(InferenceImage(b"png", (100, 100)))
        scene = parse_vlm_response(raw, (100, 100), (100, 100))
        assert client.classify(scene, scene.vehicles[0]) == "high"

    assert events == [
        ("qwen2.5vl:7b", "preload"),
        ("qwen2.5vl:7b", "analyze"),
        ("tev1", "warmup"),
        ("tev1", "classify"),
    ]


def test_retries_preload_for_later_image() -> None:
    settings = load_settings(Path("config/setting.ini"))
    attempts = 0
    events: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        if request.url.path == "/api/generate":
            attempts += 1
            events.append("preload")
            if attempts == 1:
                return httpx.Response(503)
            return httpx.Response(200, json={"done": True})
        events.append("analyze")
        return httpx.Response(200, json={"message": {"content": _vlm_text()}})

    http_client = httpx.Client(
        base_url=settings.ollama_url, transport=httpx.MockTransport(handle)
    )
    with OllamaClient(settings, http_client) as client:
        with pytest.raises(ModelError, match="事前ロード"):
            client.analyze(InferenceImage(b"png", (100, 100)))
        assert client.analyze(InferenceImage(b"png", (100, 100))) == _vlm_text()

    assert events == ["preload", "preload", "analyze"]

    vehicle = parse_vlm_response(_vlm_text(), (100, 100), (100, 100)).vehicles[0]
    scene = parse_vlm_response(_vlm_text(), (100, 100), (100, 100))
    dom_attempts = 0
    dom_events: list[str] = []

    def handle_dom(request: httpx.Request) -> httpx.Response:
        nonlocal dom_attempts
        body = json.loads(request.content)
        assert request.url.path == "/v1/systemone"
        if "warmup" in body["questions"]:
            dom_attempts += 1
            dom_events.append("warmup")
            if dom_attempts == 1:
                return httpx.Response(503)
            return httpx.Response(
                200,
                json={"answers": {"warmup": {"type": "choice", "choice": "ready"}}},
            )
        dom_events.append("classify")
        return httpx.Response(
            200, json={"answers": {"v1": {"type": "choice", "choice": "high"}}}
        )

    dom_http_client = httpx.Client(
        base_url=settings.ollama_url, transport=httpx.MockTransport(handle_dom)
    )
    with OllamaClient(settings, dom_http_client) as client:
        with pytest.raises(ModelError, match="事前ロード"):
            client.classify(scene, vehicle)
        assert client.classify(scene, vehicle) == "high"

    assert dom_events == ["warmup", "warmup", "classify"]


def test_rejects_invalid_dom_warmup_response() -> None:
    settings = load_settings(Path("config/setting.ini"))
    scene = parse_vlm_response(_vlm_text(), (100, 100), (100, 100))

    def handle(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/systemone"
        return httpx.Response(
            200,
            json={"answers": {"warmup": {"type": "choice", "choice": []}}},
        )

    http_client = httpx.Client(
        base_url=settings.ollama_url, transport=httpx.MockTransport(handle)
    )
    with (
        OllamaClient(settings, http_client) as client,
        pytest.raises(ModelError, match="ウォームアップ応答が不正"),
    ):
        client.classify(scene, scene.vehicles[0])


def test_supplies_distinct_lanes_to_dom() -> None:
    settings = load_settings(Path("config/setting.ini"))
    payload = json.loads(_vlm_text())
    payload["vehicles"][0]["path_relation"] = "left lane, ahead"
    scene = parse_vlm_response(json.dumps(payload), (100, 100), (100, 100))
    calls: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert request.url.path == "/v1/systemone"
        if "warmup" in body["questions"]:
            calls.append("warmup")
            return httpx.Response(
                200,
                json={"answers": {"warmup": {"type": "choice", "choice": "ready"}}},
            )
        state = json.loads(body["state"])
        assert state["camera_lane"] == "center"
        assert state["visual_proximity"] == "near"
        assert state["path_relation"] == "left lane, ahead"
        assert "different adjacent lane" in body["questions"]["v1"]["instructions"]
        calls.append("classify")
        return httpx.Response(
            200, json={"answers": {"v1": {"type": "choice", "choice": "medium"}}}
        )

    http_client = httpx.Client(
        base_url=settings.ollama_url, transport=httpx.MockTransport(handle)
    )
    with OllamaClient(settings, http_client) as client:
        assert client.classify(scene, scene.vehicles[0]) == "medium"

    assert calls == ["warmup", "classify"]
