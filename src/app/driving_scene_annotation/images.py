"""Image decoding, inference preparation, and atomic output."""

from __future__ import annotations

import io
import os
import tempfile
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

from PIL import Image, ImageDraw

Box = tuple[int, int, int, int]


@dataclass(frozen=True)
class SourceImage:
    pixels: Image.Image
    format: str

    @property
    def size(self) -> tuple[int, int]:
        return self.pixels.size


@dataclass(frozen=True)
class InferenceImage:
    png: bytes
    size: tuple[int, int]


@dataclass(frozen=True)
class Annotation:
    box: Box
    color: str


def read_source(path: Path) -> SourceImage:
    with Image.open(path) as opened:
        if getattr(opened, "n_frames", 1) != 1:
            raise ValueError("複数フレーム画像は対象外です")
        if opened.format is None:
            raise ValueError("画像形式を判別できません")
        opened.load()
        return SourceImage(opened.copy(), opened.format)


def prepare_inference(
    source: SourceImage, max_width: int, max_height: int
) -> InferenceImage:
    width, height = source.size
    if width < 1 or height < 1:
        raise ValueError("画像の幅・高さが不正です")
    scale = min(Fraction(1), Fraction(max_width, width), Fraction(max_height, height))
    target_width = max(1, width * scale.numerator // scale.denominator)
    target_height = max(1, height * scale.numerator // scale.denominator)
    pixels = source.pixels
    if (target_width, target_height) != source.size:
        pixels = pixels.resize((target_width, target_height), Image.Resampling.LANCZOS)
    if pixels.mode not in {"RGB", "RGBA"}:
        pixels = pixels.convert("RGB")
    stream = io.BytesIO()
    pixels.save(stream, format="PNG")
    return InferenceImage(stream.getvalue(), (target_width, target_height))


def write_output(
    source: SourceImage,
    annotations: list[Annotation],
    line_width: int,
    destination: Path,
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.pixels.mode == "RGBA" and source.format == "PNG":
        output = source.pixels.copy()
    else:
        output = source.pixels.convert("RGB")
    if annotations:
        draw = ImageDraw.Draw(output)
        for annotation in annotations:
            xmin, ymin, xmax, ymax = annotation.box
            draw.rectangle(
                (xmin, ymin, xmax - 1, ymax - 1),
                outline=annotation.color,
                width=line_width,
            )
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=f".{destination.stem}.",
            suffix=destination.suffix,
            dir=destination.parent,
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
        output.save(temporary_path, format=source.format)
        os.replace(temporary_path, destination)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
