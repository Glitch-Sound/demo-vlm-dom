"""HTTP contracts for the VLM and decision model on Ollama."""

from __future__ import annotations

import base64
import json
from typing import Any

import httpx

from app.driving_scene_annotation.analysis import (
    VLM_SCHEMA,
    Scene,
    Vehicle,
    is_visually_distant,
    parse_dom_response,
)
from app.driving_scene_annotation.config import Settings
from app.driving_scene_annotation.images import InferenceImage

VLM_MODEL = "qwen2.5vl:7b"
DOM_MODEL = "tev1"

VLM_PROMPT = """Inspect only the supplied single driving-scene image.
Return a JSON object matching the schema. Describe the visible scene and list every
identifiable vehicle other than the camera vehicle. Give each vehicle a unique ID.
Include identifiable small vehicles in the distant background, with one box per
actual vehicle.
Identify the camera's current lane from visible road markings around the
bottom-center viewpoint, and return camera_lane as left, center, right, single,
or unknown. Use single when only one lane travels in the camera vehicle's
direction. In each vehicle's path_relation, describe its visible lane and whether
it is in the camera lane or a different lane. Being ahead alone does not make
a vehicle part of the camera lane. Keep evidence consistent with path_relation:
do not say a lane marking separates a vehicle that you placed in the camera
lane. Use unknown only when the relative position is not visible.
For each vehicle, give [xmin, ymin, xmax, ymax] in absolute pixels of the supplied
image, with exclusive right and bottom edges. Describe its visible position relative
to the camera vehicle's forward path using lanes, road markings or an intersection,
and give the visible evidence. If that relation cannot be determined, set
path_relation to 'unknown'. Do not decide priority. Do not infer speed, intent,
future movement, collision likelihood, or exact distance. Use an empty vehicles
array if no other vehicle is visible."""

DOM_CRITERIA = {
    "high": "The vehicle is immediately ahead in the camera lane, or visible evidence explicitly shows overlap with its forward path. Being ahead alone does not qualify.",
    "medium": "The vehicle is visually near in a different adjacent lane or near an intersection, without path overlap.",
    "low": "The visible position is known and meets neither the high nor the medium condition, including an opposite-direction lane.",
    "undetermined": "The camera lane or path relation is unknown, or visible evidence is insufficient; do not guess.",
}

DOM_WARMUP_CRITERIA = {
    "ready": "The service is responding to this warmup question.",
    "other": "The service is responding, but does not select ready.",
}


class ModelError(RuntimeError):
    def __init__(self, model: str, stage: str, detail: str) -> None:
        self.model = model
        self.stage = stage
        super().__init__(f"{model} の{stage}に失敗しました: {detail}")


class OllamaClient:
    def __init__(self, settings: Settings, client: httpx.Client | None = None) -> None:
        self.settings = settings
        self._client = client or httpx.Client(base_url=settings.ollama_url)
        self._loaded: set[str] = set()

    def __enter__(self) -> OllamaClient:
        return self

    def __exit__(self, *_exc: object) -> None:
        self._client.close()

    def _post(self, path: str, payload: dict[str, Any], model: str, stage: str) -> Any:
        timeout = (
            self.settings.preload_timeout_seconds
            if stage == "事前ロード"
            else self.settings.inference_timeout_seconds
        )
        try:
            response = self._client.post(path, json=payload, timeout=timeout)
            response.raise_for_status()
            return response.json()
        except httpx.TimeoutException as exc:
            raise ModelError(model, stage, "タイムアウト") from exc
        except httpx.HTTPStatusError as exc:
            raise ModelError(model, stage, f"HTTP {exc.response.status_code}") from exc
        except httpx.HTTPError as exc:
            raise ModelError(
                model, stage, f"接続エラー: {exc.__class__.__name__}"
            ) from exc
        except ValueError as exc:
            raise ModelError(model, stage, "JSON 応答を解析できません") from exc

    def preload(self, model: str) -> None:
        if model in self._loaded:
            return
        if model == VLM_MODEL:
            response = self._post(
                "/api/generate",
                {
                    "model": model,
                    "prompt": "",
                    "stream": False,
                    "keep_alive": self.settings.keep_alive,
                },
                model,
                "事前ロード",
            )
            if not isinstance(response, dict) or response.get("done") is not True:
                raise ModelError(model, "事前ロード", "ロード完了応答がありません")
        elif model == DOM_MODEL:
            response = self._post(
                "/v1/systemone",
                {
                    "model": model,
                    "state": "Warmup request before vehicle classification.",
                    "questions": {
                        "warmup": {
                            "type": "choice",
                            "instructions": "Choose either option to confirm a response.",
                            "criteria": DOM_WARMUP_CRITERIA,
                        }
                    },
                    "keep_alive": self.settings.keep_alive,
                },
                model,
                "事前ロード",
            )
            answers = response.get("answers") if isinstance(response, dict) else None
            answer = answers.get("warmup") if isinstance(answers, dict) else None
            if (
                not isinstance(answer, dict)
                or answer.get("type") != "choice"
                or not isinstance(answer.get("choice"), str)
                or answer["choice"] not in DOM_WARMUP_CRITERIA
            ):
                raise ModelError(model, "事前ロード", "ウォームアップ応答が不正です")
        else:
            raise ValueError(f"未対応モデル: {model}")
        self._loaded.add(model)

    def analyze(self, image: InferenceImage) -> str:
        self.preload(VLM_MODEL)
        response = self._post(
            "/api/chat",
            {
                "model": VLM_MODEL,
                "messages": [
                    {
                        "role": "user",
                        "content": VLM_PROMPT,
                        "images": [base64.b64encode(image.png).decode("ascii")],
                    }
                ],
                "format": VLM_SCHEMA,
                "stream": False,
                "keep_alive": self.settings.keep_alive,
            },
            VLM_MODEL,
            "画像推論",
        )
        if not isinstance(response, dict):
            raise ModelError(VLM_MODEL, "画像推論", "応答形式が不正です")
        message = response.get("message")
        if not isinstance(message, dict) or not isinstance(message.get("content"), str):
            raise ModelError(VLM_MODEL, "画像推論", "応答本文がありません")
        return message["content"]

    def classify(self, scene: Scene, vehicle: Vehicle) -> str:
        if is_visually_distant(scene, vehicle):
            return "low"
        if vehicle.path_relation == "unknown" or scene.camera_lane == "unknown":
            return "undetermined"
        self.preload(DOM_MODEL)
        state = json.dumps(
            {
                "scene": scene.description[:400],
                "camera_lane": scene.camera_lane,
                "vehicle_id": vehicle.id[:100],
                "bbox": vehicle.box,
                "visual_proximity": "near",
                "path_relation": vehicle.path_relation[:400],
                "visual_evidence": vehicle.evidence[:400],
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        response = self._post(
            "/v1/systemone",
            {
                "model": DOM_MODEL,
                "state": state,
                "questions": {
                    vehicle.id: {
                        "type": "choice",
                        "instructions": "The application has determined this vehicle appears near from its box size; use visual_proximity=near. Compare camera_lane with the lane stated in path_relation and evidence. A nearby vehicle in a different adjacent lane is medium, not low or high, unless there is explicit path overlap. An opposite-direction vehicle is low. Do not predict motion, intent, risk, or metric distance.",
                        "criteria": DOM_CRITERIA,
                    }
                },
                "keep_alive": self.settings.keep_alive,
            },
            DOM_MODEL,
            "車両判定",
        )
        try:
            return parse_dom_response(response, vehicle.id)
        except ValueError as exc:
            raise ModelError(DOM_MODEL, "車両判定", str(exc)) from exc
