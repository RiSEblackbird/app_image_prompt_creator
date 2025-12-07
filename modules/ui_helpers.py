"""PySide6 UI部品の生成や選択値取得をまとめたヘルパー。"""

from __future__ import annotations

from typing import Optional

from PySide6 import QtWidgets

from modules import config
from modules.llm import _normalize_language_code


def combo_language_code(combo: Optional[QtWidgets.QComboBox]) -> str:
    """コンボボックスの userData から言語コードを取り出し、正規化して返す。"""
    if combo is None:
        return "en"
    data = combo.currentData()
    return _normalize_language_code(data if isinstance(data, str) else None)


def create_language_combo() -> QtWidgets.QComboBox:
    """英語/日本語の2択を持つコンボボックスを生成する。"""
    combo = QtWidgets.QComboBox()
    for label, code in config.LANGUAGE_COMBO_CHOICES:
        combo.addItem(label, userData=code)
    combo.setCurrentIndex(0)
    return combo
