"""Validate model results and map inference coordinates to the source image."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from app.driving_scene_annotation.images import Box

VLM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "scene_description": {"type": "string"},
        "camera_lane": {
            "type": "string",
            "enum": ["left", "center", "right", "single", "unknown"],
        },
        "vehicles": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "bbox": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "minItems": 4,
                        "maxItems": 4,
                    },
                    "path_relation": {"type": "string"},
                    "evidence": {"type": "string"},
                },
                "required": [
                    "id",
                    "bbox",
                    "path_relation",
                    "evidence",
                ],
            },
        },
    },
    "required": ["scene_description", "camera_lane", "vehicles"],
}

PRIORITIES = {"high", "medium", "low", "undetermined"}
LANES = {"left", "center", "right", "single", "unknown"}
MIN_NEAR_IMAGE_HEIGHT_PERCENT = 8
MIN_NEAR_RELATIVE_HEIGHT_PERCENT = 40


@dataclass(frozen=True)
class Vehicle:
    id: str
    box: Box
    path_relation: str
    evidence: str


@dataclass(frozen=True)
class Scene:
    description: str
    vehicles: list[Vehicle]
    discarded: list[str]
    camera_lane: str
    source_height: int


def is_visually_distant(scene: Scene, vehicle: Vehicle) -> bool:
    """Use apparent box height, never a metric distance estimate."""
    if not scene.vehicles or scene.source_height <= 0:
        return False
    height = vehicle.box[3] - vehicle.box[1]
    tallest = max(other.box[3] - other.box[1] for other in scene.vehicles)
    return (
        height * 100 < scene.source_height * MIN_NEAR_IMAGE_HEIGHT_PERCENT
        or height * 100 < tallest * MIN_NEAR_RELATIVE_HEIGHT_PERCENT
    )


def map_box(
    box: Box, inference_size: tuple[int, int], source_size: tuple[int, int]
) -> Box:
    width, height = inference_size
    source_width, source_height = source_size
    xmin, ymin, xmax, ymax = box
    return (
        xmin * source_width // width,
        ymin * source_height // height,
        (xmax * source_width + width - 1) // width,
        (ymax * source_height + height - 1) // height,
    )


def _is_valid_box(box: Box, width: int, height: int) -> bool:
    xmin, ymin, xmax, ymax = box
    return 0 <= xmin < xmax <= width and 0 <= ymin < ymax <= height


def parse_vlm_response(
    raw_text: str,
    inference_size: tuple[int, int],
    source_size: tuple[int, int],
) -> Scene:
    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"VLM の JSON を解析できません: {exc.msg}") from exc
    if not isinstance(data, dict):
        raise ValueError("VLM 応答の最上位はオブジェクトにしてください")
    description = data.get("scene_description")
    camera_lane = data.get("camera_lane")
    entries = data.get("vehicles")
    if (
        not isinstance(description, str)
        or not isinstance(camera_lane, str)
        or camera_lane not in LANES
        or not isinstance(entries, list)
    ):
        raise ValueError(
            "VLM 応答の scene_description、camera_lane または vehicles が不正です"
        )

    width, height = inference_size
    vehicles: list[Vehicle] = []
    discarded: list[str] = []
    seen: set[str] = set()
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ValueError(
                f"VLM 応答の vehicles[{index}] はオブジェクトにしてください"
            )
        vehicle_id = entry.get("id")
        coordinates = entry.get("bbox")
        relation = entry.get("path_relation")
        evidence = entry.get("evidence")
        if (
            not isinstance(vehicle_id, str)
            or not vehicle_id.strip()
            or not isinstance(coordinates, list)
            or len(coordinates) != 4
            or any(type(value) is not int for value in coordinates)
            or not isinstance(relation, str)
            or not relation.strip()
            or not isinstance(evidence, str)
        ):
            raise ValueError(
                f"VLM 応答の vehicles[{index}] に必須項目の欠落・型不正があります"
            )
        if vehicle_id in seen:
            raise ValueError(f"VLM 応答の車両 ID が重複しています: {vehicle_id}")
        seen.add(vehicle_id)
        if relation != "unknown" and not evidence.strip():
            raise ValueError(
                f"VLM 応答の車両 {vehicle_id} に位置関係の根拠がありません"
            )
        box: Box = (coordinates[0], coordinates[1], coordinates[2], coordinates[3])
        if not _is_valid_box(box, width, height):
            discarded.append(
                f"{vehicle_id}: 推論用画像の範囲外または逆転した矩形 {box}"
            )
            continue
        mapped = map_box(box, inference_size, source_size)
        vehicles.append(Vehicle(vehicle_id, mapped, relation, evidence))
    return Scene(description, vehicles, discarded, camera_lane, source_size[1])


def parse_dom_response(data: Any, vehicle_id: str) -> str:
    if not isinstance(data, dict):
        raise ValueError("DOM 応答の最上位はオブジェクトにしてください")
    answers = data.get("answers")
    if not isinstance(answers, dict) or vehicle_id not in answers:
        raise ValueError(f"DOM 応答に車両 {vehicle_id} の choice がありません")
    answer = answers[vehicle_id]
    if not isinstance(answer, dict) or answer.get("type") not in {None, "choice"}:
        raise ValueError(f"DOM 応答の車両 {vehicle_id} の形式が不正です")
    choice = answer.get("choice")
    if not isinstance(choice, str) or choice not in PRIORITIES:
        raise ValueError(f"DOM 応答の車両 {vehicle_id} に指定外の choice があります")
    return choice
