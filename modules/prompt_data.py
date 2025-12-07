from __future__ import annotations

import csv
import logging
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import List

import yaml

from . import config
from .logging_utils import log_structured


@dataclass
class AttributeType:
    id: int
    attribute_name: str
    description: str


@dataclass
class AttributeDetail:
    id: int
    attribute_type_id: int
    description: str
    value: str
    content_count: int


def load_exclusion_words() -> List[str]:
    """除外語句CSVを読み込み、コンボ用の選択肢リストを返す。欠損時は空要素のみ。"""
    try:
        with open(config.EXCLUSION_CSV, "r", encoding="utf-8", newline="") as file:
            reader = csv.reader(file, quotechar='"', quoting=csv.QUOTE_ALL)
            return [""] + [row[0] for row in reader if row]
    except FileNotFoundError:
        return [""]


def _normalize_tail_presets(raw_presets: dict) -> dict:
    """YAML の末尾プリセット定義を内部表現へ正規化する。"""
    if not isinstance(raw_presets, dict):
        return deepcopy(config.DEFAULT_TAIL_PRESETS)

    normalized: dict = {}
    for media_type, items in raw_presets.items():
        if not isinstance(items, list):
            continue
        bucket = []
        for item in items:
            if not isinstance(item, dict):
                continue
            prompt = str(item.get("prompt", ""))
            description = str(item.get("description_ja", prompt))
            bucket.append({"description_ja": description, "prompt": prompt})
        if bucket:
            normalized[str(media_type)] = bucket

    if not normalized:
        return deepcopy(config.DEFAULT_TAIL_PRESETS)
    return normalized


def load_tail_presets_from_yaml() -> None:
    """末尾プリセット YAML を読み込み、グローバルな TAIL_PRESETS を更新する。"""
    path = Path(config.TAIL_PRESETS_YAML)
    if not path.exists():
        log_structured(logging.WARNING, "tail_presets_yaml_missing", {"path": str(path)})
        config.TAIL_PRESETS = deepcopy(config.DEFAULT_TAIL_PRESETS)
        return

    try:
        with path.open("r", encoding="utf-8") as fp:
            data = yaml.safe_load(fp) or {}
    except yaml.YAMLError as error:
        log_structured(
            logging.ERROR,
            "tail_presets_yaml_parse_error",
            {"path": str(path), "error": str(error)},
        )
        config.TAIL_PRESETS = deepcopy(config.DEFAULT_TAIL_PRESETS)
        return
    except OSError as error:
        log_structured(
            logging.ERROR,
            "tail_presets_yaml_io_error",
            {"path": str(path), "error": str(error)},
        )
        config.TAIL_PRESETS = deepcopy(config.DEFAULT_TAIL_PRESETS)
        return

    tails = data.get("tails")
    if not isinstance(tails, dict):
        log_structured(
            logging.WARNING,
            "tail_presets_yaml_invalid_schema",
            {"path": str(path), "reason": "missing_or_non_mapping_tails"},
        )
        config.TAIL_PRESETS = deepcopy(config.DEFAULT_TAIL_PRESETS)
        return

    config.TAIL_PRESETS = _normalize_tail_presets(tails)
    log_structured(
        logging.INFO,
        "tail_presets_yaml_loaded",
        {"path": str(path), "media_types": list(config.TAIL_PRESETS.keys())},
    )


def load_arrange_presets_from_yaml() -> None:
    """アレンジプリセット YAML を読み込み、ARRANGE_PRESETS を更新する。"""
    path = Path(config.ARRANGE_PRESETS_YAML)
    try:
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        presets = data.get("presets", [])
        normalized: List[dict] = []
        for p in presets:
            if not isinstance(p, dict):
                continue
            preset_id = p.get("id") or p.get("key") or p.get("name")
            if not preset_id:
                continue
            normalized.append(
                {
                    "id": str(preset_id),
                    "label": p.get("label") or p.get("name") or p.get("id") or str(preset_id),
                    "guidance": p.get("guidance") or "",
                }
            )
        config.ARRANGE_PRESETS = normalized or deepcopy(config.DEFAULT_ARRANGE_PRESETS)
        log_structured(
            logging.INFO,
            "arrange_presets_yaml_loaded",
            {"path": str(path), "count": len(config.ARRANGE_PRESETS)},
        )
    except FileNotFoundError:
        log_structured(logging.WARNING, "arrange_presets_yaml_missing", {"path": str(path)})
        config.ARRANGE_PRESETS = deepcopy(config.DEFAULT_ARRANGE_PRESETS)
    except Exception as error:
        log_structured(
            logging.ERROR,
            "arrange_presets_yaml_error",
            {"path": str(path), "error": str(error)},
        )
        config.ARRANGE_PRESETS = deepcopy(config.DEFAULT_ARRANGE_PRESETS)
