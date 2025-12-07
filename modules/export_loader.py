"""CSVエクスポートモジュールのロードと欠損時ハンドリングをまとめたヘルパー。"""

from __future__ import annotations

import importlib
import logging

from PySide6 import QtWidgets

from modules.logging_utils import log_structured


def show_missing_export_module_dialog() -> None:
    """export_prompts_to_csv が見つからない場合の案内ダイアログ。"""
    instruction = (
        "CSVエクスポート用モジュール export_prompts_to_csv.py が見つかりません。\n\n"
        "復旧手順:\n"
        "1) リポジトリ直下に export_prompts_to_csv.py を配置する\n"
        "2) `git checkout -- export_prompts_to_csv.py` を実行して取得する\n"
        "3) 別リポジトリで管理している場合は README の案内や pip インストール手順を参照する"
    )
    try:
        QtWidgets.QMessageBox.critical(None, "CSVエクスポートモジュール未検出", instruction)
    except Exception:
        logging.error("export_prompts_to_csv.py が見つかりません: %s", instruction)


def load_export_module():
    """MJImage の実体をロードし、欠損時は案内専用のプレースホルダーを返す。"""
    try:
        module = importlib.import_module("export_prompts_to_csv")
        return module.MJImage
    except Exception as exc:
        log_structured(logging.ERROR, "export_module_missing", {"error": str(exc)})
        show_missing_export_module_dialog()

        class _MissingMJImage:
            """欠損時でもボタン押下で案内を出せるプレースホルダー。"""

            def run(self):
                show_missing_export_module_dialog()

        return _MissingMJImage
