"""加工設定のプリセット（名前付きの加工の組み合わせ）の保存・読み込み。"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, fields, replace
from pathlib import Path
from typing import Any

from image_editor.core.diorama import DioramaDirection
from image_editor.core.filters import FilterType
from image_editor.core.frames import FrameType
from image_editor.core.pipeline import EditSettings
from image_editor.core.shapes import ShapeType
from image_editor.core.text import TextFont, TextPosition, TextSettings

PRESETS_VERSION = 1
PRESET_NAME_MAX = 50


class PresetError(Exception):
    """プリセットのファイルを読み書きできないときに送出する例外。"""


@dataclass(frozen=True)
class Preset:
    """名前付きの加工の組み合わせ。

    テイスト・色の調整・ディテール（シャープ・ぼかし・ノイズ除去）・ジオラマ・フレーム・形・
    文字を持つ。サイズ変更・トリミング・回転は画像ごとの設定なので含めない。
    """

    name: str
    filter: FilterType = FilterType.NONE
    exposure: float = 0.0
    brightness: int = 0
    contrast: int = 0
    temperature: int = EditSettings.temperature
    saturation: int = 0
    vignette: int = 0
    aging: int = 0
    sharpen: int = 0
    blur: int = 0
    denoise: int = 0
    diorama_blur: int = 0
    diorama_direction: DioramaDirection = EditSettings.diorama_direction
    diorama_position: int = EditSettings.diorama_position
    diorama_width: int = EditSettings.diorama_width
    diorama_vivid: int = EditSettings.diorama_vivid
    frame: FrameType = FrameType.NONE
    shape: ShapeType = ShapeType.RECTANGLE
    corner_radius: int = EditSettings.corner_radius
    text: TextSettings = TextSettings()


# プリセットが持つ設定の項目（name 以外。EditSettings の同名の項目に対応する）
PRESET_FIELDS: tuple[str, ...] = tuple(f.name for f in fields(Preset) if f.name != "name")
_ENUM_FIELDS: dict[
    str, type[FilterType] | type[FrameType] | type[ShapeType] | type[DioramaDirection]
] = {
    "filter": FilterType,
    "frame": FrameType,
    "shape": ShapeType,
    "diorama_direction": DioramaDirection,
}


def preset_from_settings(name: str, settings: EditSettings) -> Preset:
    """今の設定から、加工の組み合わせだけを取り出したプリセットを作る。"""
    return Preset(name=name, **{key: getattr(settings, key) for key in PRESET_FIELDS})


def apply_preset(settings: EditSettings, preset: Preset) -> EditSettings:
    """設定にプリセットの加工を当てはめた新しい設定を返す（サイズ・範囲・向きはそのまま）。"""
    return replace(settings, **{key: getattr(preset, key) for key in PRESET_FIELDS})


def normalize_name(name: str) -> str:
    """プリセット名の前後の空白を除き、長すぎる名前を切り詰める。"""
    return name.strip()[:PRESET_NAME_MAX]


def upsert_preset(presets: list[Preset], preset: Preset) -> list[Preset]:
    """同じ名前があれば置き換え、なければ末尾に加えた新しい一覧を返す。"""
    if any(p.name == preset.name for p in presets):
        return [preset if p.name == preset.name else p for p in presets]
    return [*presets, preset]


def remove_preset(presets: list[Preset], name: str) -> list[Preset]:
    """name のプリセットを除いた新しい一覧を返す。"""
    return [p for p in presets if p.name != name]


def load_presets(path: Path) -> list[Preset]:
    """ファイルからプリセットの一覧を読む。ファイルがなければ空の一覧。

    読めない・形式が違うファイルは PresetError。一覧の中の壊れた項目（知らない値など）は
    読み飛ばす。
    """
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    except OSError as e:
        raise PresetError(f"プリセットを読み込めません: {path}\n({e})") from e
    try:
        data = json.loads(text)
        items = data["presets"]
        if not isinstance(items, list):
            raise TypeError("presets がリストではありません")
    except (ValueError, KeyError, TypeError) as e:
        raise PresetError(f"プリセットのファイルの形式が正しくありません: {path}") from e

    presets: list[Preset] = []
    for item in items:
        preset = _preset_from_dict(item)
        if preset is not None and all(p.name != preset.name for p in presets):
            presets.append(preset)
    return presets


def save_presets(path: Path, presets: list[Preset]) -> None:
    """プリセットの一覧をファイルに書く（途中で失敗しても元のファイルを壊さない）。"""
    data = {"version": PRESETS_VERSION, "presets": [_preset_to_dict(p) for p in presets]}
    text = json.dumps(data, ensure_ascii=False, indent=2)
    temporary = path.with_name(path.name + ".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(text + "\n", encoding="utf-8")
        os.replace(temporary, path)
    except OSError as e:
        raise PresetError(f"プリセットを保存できません: {path}\n({e})") from e


def _preset_to_dict(preset: Preset) -> dict[str, Any]:
    data: dict[str, Any] = {"name": preset.name}
    for key in PRESET_FIELDS:
        value = getattr(preset, key)
        if key == "text":
            data[key] = _text_to_dict(value)
        else:
            data[key] = value.value if key in _ENUM_FIELDS else value
    return data


def _text_to_dict(settings: TextSettings) -> dict[str, Any]:
    return {
        "text": settings.text,
        "font": settings.font.name,
        "size": settings.size,
        "color": list(settings.color),
        "opacity": settings.opacity,
        "position": settings.position.value,
    }


def _text_from_dict(item: object) -> TextSettings | None:
    """文字の設定を辞書から作る。壊れていれば None（項目がなければ既定値）。"""
    if not isinstance(item, dict):
        return None
    default = TextSettings()
    try:
        text = item.get("text", default.text)
        color = item.get("color", list(default.color))
        if not isinstance(text, str) or not isinstance(color, list) or len(color) != 3:
            return None
        if not all(isinstance(c, int) and not isinstance(c, bool) for c in color):
            return None
        opacity = item.get("opacity", default.opacity)
        size = item.get("size", default.size)
        if isinstance(opacity, bool) or isinstance(size, bool):
            return None
        return TextSettings(
            text=text,
            font=TextFont[item["font"]] if "font" in item else default.font,
            size=float(size),
            color=(
                min(max(color[0], 0), 255),
                min(max(color[1], 0), 255),
                min(max(color[2], 0), 255),
            ),
            opacity=int(opacity),
            position=TextPosition(item["position"]) if "position" in item else default.position,
        )
    except (KeyError, ValueError, TypeError):
        return None


def _preset_from_dict(item: object) -> Preset | None:
    """1 件分の辞書からプリセットを作る。壊れていれば None（項目がなければ既定値）。"""
    if not isinstance(item, dict):
        return None
    name = item.get("name")
    if not isinstance(name, str) or not normalize_name(name):
        return None
    values: dict[str, Any] = {}
    default = Preset(name="")
    try:
        for key in PRESET_FIELDS:
            if key not in item:
                continue
            raw = item[key]
            if key == "text":
                text = _text_from_dict(raw)
                if text is None:
                    return None
                values[key] = text
            elif key in _ENUM_FIELDS:
                values[key] = _ENUM_FIELDS[key](raw)
            elif isinstance(getattr(default, key), float):
                values[key] = float(raw)
            else:
                if isinstance(raw, bool) or not isinstance(raw, int | float):
                    return None
                values[key] = int(raw)
    except (ValueError, TypeError):
        return None
    return Preset(name=normalize_name(name), **values)
