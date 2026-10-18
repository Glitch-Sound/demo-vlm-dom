import json
import re
import subprocess
import sys
from pathlib import Path

import httpx
from PIL import Image

from app.driving_scene_annotation.cli import run
from app.driving_scene_annotation.config import Settings
from app.driving_scene_annotation.ollama_client import OllamaClient


def _settings(tmp_path: Path) -> Path:
    path = tmp_path / "config" / "setting.ini"
    path.parent.mkdir()
    path.write_text(Path("config/setting.ini").read_text())
    return path


def _image(path: Path) -> None:
    Image.new("RGB", (100, 60), "white").save(path)


def _factory(
    events: list[str], *, fail_first_chat: bool = False, empty_vehicles: bool = False
):
    def handle(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        stage = " warmup" if "warmup" in body.get("questions", {}) else ""
        events.append(f"{body['model']} {request.url.path}{stage}")
        if request.url.path == "/api/generate":
            return httpx.Response(200, json={"done": True})
        if request.url.path == "/api/chat":
            if fail_first_chat and events.count("qwen2.5vl:7b /api/chat") == 1:
                return httpx.Response(503)
            content = json.dumps(
                {
                    "scene_description": "A marked road",
                    "camera_lane": "center",
                    "vehicles": []
                    if empty_vehicles
                    else [
                        {
                            "id": "v1",
                            "bbox": [10, 10, 30, 30],
                            "path_relation": "ahead in the camera lane",
                            "evidence": "lane markings surround the vehicle",
                        }
                    ],
                }
            )
            return httpx.Response(200, json={"message": {"content": content}})
        if "warmup" in body["questions"]:
            return httpx.Response(
                200,
                json={"answers": {"warmup": {"type": "choice", "choice": "ready"}}},
            )
        return httpx.Response(
            200, json={"answers": {"v1": {"type": "choice", "choice": "high"}}}
        )

    def build(settings: Settings) -> OllamaClient:
        client = httpx.Client(
            base_url=settings.ollama_url, transport=httpx.MockTransport(handle)
        )
        return OllamaClient(settings, client)

    return build


def test_processes_all_images(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    source_dir = tmp_path / "src"
    destination_dir = tmp_path / "dest"
    source_dir.mkdir()
    _image(source_dir / "a.png")
    _image(source_dir / "b.png")
    events: list[str] = []

    assert run(settings, source_dir, destination_dir, _factory(events)) == 0

    assert sorted(path.name for path in destination_dir.iterdir()) == ["a.png", "b.png"]
    with Image.open(destination_dir / "a.png") as result:
        assert result.getpixel((10, 10)) == (255, 0, 0)
    assert events.count("qwen2.5vl:7b /api/generate") == 1
    assert events.count("tev1 /v1/systemone warmup") == 1
    assert events.count("tev1 /v1/systemone") == 2
    assert events.count("qwen2.5vl:7b /api/chat") == 2


def test_continues_after_corrupt_image(tmp_path: Path, capsys) -> None:
    settings = _settings(tmp_path)
    source_dir = tmp_path / "src"
    destination_dir = tmp_path / "dest"
    source_dir.mkdir()
    (source_dir / "a.png").write_bytes(b"broken image")
    _image(source_dir / "b.png")

    assert run(settings, source_dir, destination_dir, _factory([])) == 1

    output = capsys.readouterr().out
    assert "失敗 a.png:" in output
    assert "成功 b.png:" in output
    assert not (destination_dir / "a.png").exists()
    assert (destination_dir / "b.png").exists()


def test_reports_counts_files_and_duration(tmp_path: Path, capsys) -> None:
    settings = _settings(tmp_path)
    source_dir = tmp_path / "src"
    destination_dir = tmp_path / "dest"
    source_dir.mkdir()
    _image(source_dir / "good.png")
    (source_dir / "bad.png").write_bytes(b"broken image")

    assert run(settings, source_dir, destination_dir, _factory([])) == 1

    output = capsys.readouterr().out
    assert "結果: 成功 1 件 / 失敗 1 件" in output
    assert "失敗ファイル: bad.png" in output
    assert re.search(r"処理時間: \d+\.\d{3} 秒", output)


def test_continues_after_model_failure(tmp_path: Path, capsys) -> None:
    settings = _settings(tmp_path)
    source_dir = tmp_path / "src"
    destination_dir = tmp_path / "dest"
    source_dir.mkdir()
    destination_dir.mkdir()
    _image(source_dir / "a.png")
    _image(source_dir / "b.png")
    (destination_dir / "a.png").write_bytes(b"previous output")

    assert (
        run(settings, source_dir, destination_dir, _factory([], fail_first_chat=True))
        == 1
    )

    output = capsys.readouterr().out
    assert "qwen2.5vl:7b の画像推論に失敗しました: HTTP 503" in output
    assert "成功 b.png:" in output
    assert (destination_dir / "a.png").read_bytes() == b"previous output"
    assert (destination_dir / "b.png").exists()


def test_no_vehicles_skips_dom_and_writes_plain_image(tmp_path: Path, capsys) -> None:
    settings = _settings(tmp_path)
    source_dir = tmp_path / "src"
    destination_dir = tmp_path / "dest"
    source_dir.mkdir()
    _image(source_dir / "plain.png")
    events: list[str] = []

    assert (
        run(
            settings, source_dir, destination_dir, _factory(events, empty_vehicles=True)
        )
        == 0
    )

    assert "車両なし、矩形なしで出力" in capsys.readouterr().out
    assert not any(event.startswith("tev1") for event in events)
    with Image.open(destination_dir / "plain.png") as result:
        assert result.getpixel((10, 10)) == (255, 255, 255)


def test_cli_runs_on_supported_platform(tmp_path: Path) -> None:
    assert sys.version_info[:2] == (3, 13)
    assert sys.platform in {"darwin", "linux"}
    _settings(tmp_path)
    (tmp_path / "data" / "src").mkdir(parents=True)
    executable = Path(sys.executable).with_name("demo")

    result = subprocess.run(  # noqa: S603 - fixed venv entry point under test
        [str(executable)], cwd=tmp_path, capture_output=True, text=True, check=False
    )

    assert result.returncode == 0
    assert "結果: 成功 0 件 / 失敗 0 件" in result.stdout
