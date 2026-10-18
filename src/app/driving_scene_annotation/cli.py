"""Batch command for the driving scene demo."""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

from app.driving_scene_annotation.analysis import parse_vlm_response
from app.driving_scene_annotation.config import Settings, SettingsError, load_settings
from app.driving_scene_annotation.images import (
    Annotation,
    prepare_inference,
    read_source,
    write_output,
)
from app.driving_scene_annotation.ollama_client import OllamaClient


def run(
    settings_path: Path = Path("config/setting.ini"),
    source_dir: Path = Path("data/src"),
    destination_dir: Path = Path("data/dest"),
    client_factory: Callable[[Settings], OllamaClient] = OllamaClient,
) -> int:
    started = time.perf_counter()
    try:
        settings = load_settings(settings_path)
        if not source_dir.is_dir():
            raise SettingsError(f"入力ディレクトリ {source_dir} がありません")
        files = sorted(
            (
                path
                for path in source_dir.iterdir()
                if path.is_file() and not path.name.startswith(".")
            ),
            key=lambda p: p.name,
        )
    except (OSError, SettingsError) as exc:
        print(f"設定エラー: {exc}")
        return 2

    successes = 0
    failures: list[str] = []
    with client_factory(settings) as client:
        for source_path in files:
            try:
                source = read_source(source_path)
                inference = prepare_inference(
                    source, settings.inference_max_width, settings.inference_max_height
                )
                raw_response = client.analyze(inference)
                scene = parse_vlm_response(raw_response, inference.size, source.size)
                annotations: list[Annotation] = []
                undetermined: list[str] = []
                for vehicle in scene.vehicles:
                    priority = client.classify(scene, vehicle)
                    if priority == "undetermined":
                        reason = (
                            "前方進路との位置関係が不明"
                            if vehicle.path_relation == "unknown"
                            else (
                                "自車線が不明"
                                if scene.camera_lane == "unknown"
                                else "DOM が判断材料不足と判定"
                            )
                        )
                        undetermined.append(f"{vehicle.id}: {reason}")
                    else:
                        annotations.append(
                            Annotation(vehicle.box, settings.color_for(priority))
                        )
                write_output(
                    source,
                    annotations,
                    settings.line_width,
                    destination_dir / source_path.name,
                )
                successes += 1
                print(f"成功 {source_path.name}: 描画 {len(annotations)} 件")
                if not scene.vehicles and not scene.discarded:
                    print(f"  {source_path.name}: 車両なし、矩形なしで出力")
                if scene.discarded:
                    print(
                        f"  {source_path.name}: 無効矩形 {len(scene.discarded)} 件を除外"
                    )
                    for reason in scene.discarded:
                        print(f"    {reason}")
                if undetermined:
                    print(f"  {source_path.name}: 判定不能 {len(undetermined)} 件")
                    for reason in undetermined:
                        print(f"    {reason}")
            except Exception as exc:
                failures.append(source_path.name)
                print(f"失敗 {source_path.name}: {exc}")

    elapsed = time.perf_counter() - started
    print(f"結果: 成功 {successes} 件 / 失敗 {len(failures)} 件")
    if failures:
        print(f"失敗ファイル: {', '.join(failures)}")
    print(f"処理時間: {elapsed:.3f} 秒")
    return 1 if failures else 0


def main() -> None:
    raise SystemExit(run())
