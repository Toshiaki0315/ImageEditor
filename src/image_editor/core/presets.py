"""加工設定のプリセット（名前付きの加工の組み合わせ）の保存・読み込み。"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, fields, replace
from pathlib import Path
from typing import Any

from image_editor.core.filters import FilterType
from image_editor.core.frames import FrameType
from image_editor.core.pipeline import EditSettings
from image_editor.core.shapes import ShapeType

PRESETS_VERSION = 1
PRESET_NAME_MAX = 50


class PresetError(Exception):
    """プリセットのファイルを読み書きできないときに送出する例外。"""


@dataclass(frozen=True)
class Preset:
    """名前付きの加工の組み合わせ。

    テイスト・色の調整・ディテール（シャープ・ぼかし・ノイズ除去）・フレーム・形を持つ。
    サイズ変更・トリミング・回転は画像ごとの
    設定なので含めない。
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
    frame: FrameType = FrameType.NONE
    shape: ShapeType = ShapeType.RECTANGLE
    corner_radius: int = EditSettings.corner_radius


# プリセットが持つ設定の項目（name 以外。EditSettings の同名の項目に対応する）
PRESET_FIELDS: tuple[str, ...] = tuple(f.name for f in fields(Preset) if f.name != "name")
_ENUM_FIELDS: dict[str, type[FilterType] | type[FrameType] | type[ShapeType]] = {
    "filter": FilterType,
    "frame": FrameType,
    "shape": ShapeType,
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
        data[key] = value.value if key in _ENUM_FIELDS else value
    return data


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
            if key in _ENUM_FIELDS:
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
