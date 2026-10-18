"""Validated settings for the driving scene demo."""

from __future__ import annotations

import configparser
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


class SettingsError(ValueError):
    """The supplied configuration cannot be used."""


@dataclass(frozen=True)
class Settings:
    ollama_url: str
    preload_timeout_seconds: float
    inference_timeout_seconds: float
    keep_alive: str
    inference_max_width: int
    inference_max_height: int
    line_width: int
    high_color: str
    medium_color: str
    low_color: str

    def color_for(self, priority: str) -> str:
        return {
            "high": self.high_color,
            "medium": self.medium_color,
            "low": self.low_color,
        }[priority]


def _required(parser: configparser.ConfigParser, section: str, key: str) -> str:
    if not parser.has_option(section, key):
        raise SettingsError(f"設定項目 {section}.{key} がありません")
    value = parser.get(section, key).strip()
    if not value:
        raise SettingsError(f"設定項目 {section}.{key} が空です")
    return value


def _positive_float(parser: configparser.ConfigParser, section: str, key: str) -> float:
    raw = _required(parser, section, key)
    try:
        value = float(raw)
    except ValueError as exc:
        raise SettingsError(f"設定項目 {section}.{key} は正の数にしてください") from exc
    if not 0 < value < float("inf"):
        raise SettingsError(f"設定項目 {section}.{key} は正の数にしてください")
    return value


def _positive_int(parser: configparser.ConfigParser, section: str, key: str) -> int:
    raw = _required(parser, section, key)
    if not raw.isascii() or not raw.isdecimal() or int(raw) < 1:
        raise SettingsError(f"設定項目 {section}.{key} は正の整数にしてください")
    return int(raw)


def _color(parser: configparser.ConfigParser, key: str) -> str:
    value = _required(parser, "colors", key)
    if re.fullmatch(r"#[0-9A-Fa-f]{6}", value) is None:
        raise SettingsError(f"設定項目 colors.{key} は #RRGGBB 形式にしてください")
    return value.upper()


def load_settings(path: Path) -> Settings:
    parser = configparser.ConfigParser(interpolation=None)
    try:
        with path.open(encoding="utf-8") as config_file:
            parser.read_file(config_file)
    except (OSError, configparser.Error) as exc:
        raise SettingsError(f"設定ファイル {path} を読めません: {exc}") from exc

    url = _required(parser, "ollama", "ollama_url").rstrip("/")
    parsed_url = urlparse(url)
    if (
        parsed_url.scheme not in {"http", "https"}
        or not parsed_url.hostname
        or parsed_url.username
        or parsed_url.password
    ):
        raise SettingsError(
            "設定項目 ollama.ollama_url は認証情報を含まない HTTP(S) URL にしてください"
        )
    keep_alive = _required(parser, "ollama", "keep_alive")
    if re.fullmatch(r"[1-9][0-9]*(ms|s|m|h)", keep_alive) is None:
        raise SettingsError(
            "設定項目 ollama.keep_alive は 10m などの時間形式にしてください"
        )

    return Settings(
        ollama_url=url,
        preload_timeout_seconds=_positive_float(
            parser, "ollama", "preload_timeout_seconds"
        ),
        inference_timeout_seconds=_positive_float(
            parser, "ollama", "inference_timeout_seconds"
        ),
        keep_alive=keep_alive,
        inference_max_width=_positive_int(parser, "image", "inference_max_width"),
        inference_max_height=_positive_int(parser, "image", "inference_max_height"),
        line_width=_positive_int(parser, "image", "line_width"),
        high_color=_color(parser, "high_color"),
        medium_color=_color(parser, "medium_color"),
        low_color=_color(parser, "low_color"),
    )
