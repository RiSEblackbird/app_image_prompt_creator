"""PySide6 版 画像プロンプトランダム生成ツール。

Tkinter 実装から移行し、QMainWindow/QWidget ベースのUIへ再設計。
主な機能:
- DBから属性を読み込み、行数とオプションを指定してプロンプト生成
- 末尾プリセット選択、オプションコンボ、クリップボードコピー
- LLM 呼び出し（非同期スレッド実行）
- CSV の投入・出力、除外語句 CSV オープン
- 動画用 JSON への整形
"""
from __future__ import annotations

import csv
import faulthandler
import importlib
import json
import logging
import os
import platform
import random
import re
import socket
import sqlite3
import subprocess
import sys
import traceback
from contextlib import closing
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import time
from typing import Iterable, List, Optional, Set, Tuple

import requests
from PySide6 import QtCore, QtGui, QtWidgets

# =============================
# 設定・定数
# =============================
WINDOW_TITLE = "画像プロンプトランダム生成ツール (PySide6)"
DEFAULT_ROW_NUM = 10
DEFAULT_TAIL_MEDIA_TYPE = "image"
AVAILABLE_LLM_MODELS = [
    "gpt-4o-mini",
    "gpt-4o",
    "gpt-5.1",
]
DEFAULT_LLM_MODEL = AVAILABLE_LLM_MODELS[0]
LANGUAGE_COMBO_CHOICES = [
    ("英語", "en"),
    ("日本語", "ja"),
]

# 末尾プリセットのデフォルト定義。
# YAML が欠損・パース失敗した場合にも既存挙動を維持できるよう、
# ここに「英語/JSON の実プロンプト」と「日本語 description（UI 表示専用）」の両方を持たせる。
DEFAULT_TAIL_PRESETS = {
    "image": [
        {"description_ja": "（なし）", "prompt": ""},
        {
            "description_ja": "超高解像度写真 (8K)",
            "prompt": "A high resolution photograph. Very high resolution. 8K photo",
        },
        {
            "description_ja": "日本画・墨絵スタイル",
            "prompt": "a Japanese ink painting. Zen painting",
        },
        {
            "description_ja": "中世ヨーロッパ絵画スタイル",
            "prompt": "a Medieval European painting.",
        },
    ],
    "movie": [
        {"description_ja": "（なし）", "prompt": ""},
        {
            "description_ja": "70mmフィルムのシネマティック全編",
            "prompt": "{\"video_style\":{\"scope\":\"full_movie\",\"description\":\"sweeping cinematic sequence shot on 70mm film\",\"look\":\"dramatic lighting\"}}",
        },
        {
            "description_ja": "4K HDR の高精細トラッキングショット",
            "prompt": "{\"video_style\":{\"scope\":\"full_movie\",\"description\":\"dynamic tracking shot captured as ultra high fidelity footage\",\"format\":\"4K HDR\"}}",
        },
        {
            "description_ja": "ムーディーなアートハウス短編",
            "prompt": "{\"video_style\":{\"scope\":\"full_movie\",\"description\":\"moody arthouse short film\",\"camera\":\"deliberate movement\"}}",
        },
        {
            "description_ja": "モダンな映画予告編風の高速モンタージュ",
            "prompt": "{\"video_style\":{\"scope\":\"full_movie\",\"description\":\"fast-paced montage cut like a modern movie trailer\",\"grade\":\"Dolby Vision\"}}",
        },
        {
            "description_ja": "タイトなシネマティックショット (4K)",
            "prompt": "{\"video_style\":{\"scope\":\"full_movie\",\"description\":\"tight cinematic shot with controlled, fluid camera motion\",\"format\":\"4K\"}}",
        },
        {
            "description_ja": "1960年代フィルムプリント風の雰囲気カット",
            "prompt": "{\"video_style\":{\"scope\":\"full_movie\",\"description\":\"atmospheric sequence graded like a 1960s film print\",\"grade\":\"film emulation\"}}",
        },
        {
            "description_ja": "スタジオライティングの高コントラストショット",
            "prompt": "{\"video_style\":{\"scope\":\"full_movie\",\"description\":\"crisp studio-lit shot with high contrast and clean composition\",\"look\":\"studio lighting\"}}",
        },
        {
            "description_ja": "ハンドヘルド撮影の自然なモーションブラー",
            "prompt": "{\"video_style\":{\"scope\":\"full_movie\",\"description\":\"handheld cinematic shot with subtle motion blur and natural grain\",\"camera\":\"handheld\"}}",
        },
        {
            "description_ja": "8K マスターのスムーズな編集シネマティック",
            "prompt": "{\"video_style\":{\"scope\":\"full_movie\",\"description\":\"cinematic shot mastered in 8K with smooth editing rhythm\",\"format\":\"8K\"}}",
        },
        {
            "description_ja": "ドローンによるワンテイク空撮",
            "prompt": "{\"video_style\":{\"scope\":\"full_movie\",\"description\":\"continuous one-take aerial drone footage flying smoothly through the scene\",\"camera\":\"drone one-shot\"}}",
        },
        {
            "description_ja": "サスペンスドラマ風の緊張感あるシーン",
            "prompt": "{\"video_style\":{\"scope\":\"full_movie\",\"description\":\"tense, dramatic scene from a suspense TV drama with moody lighting and framing\",\"genre\":\"suspense drama\"}}",
        },
        {
            "description_ja": "ワンショット・ドキュメンタリー調の現実的トーン",
            "prompt": "{\"video_style\":{\"scope\":\"full_movie\",\"description\":\"single-take documentary-style shot that follows this world in a realistic tone\",\"style\":\"one-shot documentary\"}}",
        },
    ],
}

# 実際に UI/生成で利用する末尾プリセット（起動時に YAML から上書き）
TAIL_PRESETS = deepcopy(DEFAULT_TAIL_PRESETS)

# アレンジプリセット（LLMスタイル用）は Tk 版と同じ YAML (`arrange_presets.yaml`) を共有する。
# Qt 版では現時点で UI バインディングのみ未実装だが、データ層としてプリセットの読込とホットリロードに対応しておく。
DEFAULT_ARRANGE_PRESETS = [
    {"id": "auto", "label": "auto", "guidance": ""},
]
ARRANGE_PRESETS: List[dict] = deepcopy(DEFAULT_ARRANGE_PRESETS)
S_OPTIONS = ["", "0", "10", "20", "30", "40", "50", "100", "150", "200", "250", "300", "400", "500", "600", "700", "800", "900", "1000"]
AR_OPTIONS = ["", "16:9", "9:16", "4:3", "3:4"]
CHAOS_OPTIONS = ["", "0", "10", "20", "30", "40", "50", "60", "70", "80", "90", "100"]
Q_OPTIONS = ["", "1", "2"]
WEIRD_OPTIONS = ["", "0", "10", "20", "30", "40", "50", "100", "150", "200", "250", "500", "750", "1000", "1250", "1500", "1750", "2000", "2250", "2500", "2750", "3000"]
LABEL_EXCLUSION_WORDS = "除外語句："
CHAT_COMPLETIONS_URL = "https://api.openai.com/v1/chat/completions"
RESPONSES_API_URL = "https://api.openai.com/v1/responses"
RESPONSES_MODEL_PREFIXES = ("gpt-5",)
LENGTH_LIMIT_REASONS = {"length", "max_output_tokens"}
HOSTNAME = socket.gethostname()
SCRIPT_DIR = Path(__file__).resolve().parent

LOG_DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"
LOG_FORMAT = (
    "%(asctime)s.%(msecs)03d\t%(levelname)s\t%(hostname)s\t"
    "pid=%(process)d\tthread=%(threadName)s\t%(name)s:%(lineno)d\t%(message)s"
)
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT, datefmt=LOG_DATETIME_FORMAT)
try:
    faulthandler.enable()
except Exception:
    logging.getLogger(__name__).warning("Failed to enable faulthandler; native crashes may lack stack traces.")


class _HostnameContextFilter(logging.Filter):
    """ターミナル出力でホスト名を常に表示し、障害発生環境を即時判別できるようにする。"""

    def filter(self, record: logging.LogRecord) -> bool:
        record.hostname = HOSTNAME
        return True


logging.getLogger().addFilter(_HostnameContextFilter())

FONT_SCALE_PRESETS = [
    {"label": "標準", "pt": 11},
    {"label": "大", "pt": 13},
    {"label": "特大", "pt": 16},
    {"label": "4K", "pt": 20},
]

# 設定ファイルが欠損した場合も動かせるよう、サンプル相当のデフォルト値を持っておく。
DEFAULT_APP_SETTINGS = {
    "POSITION_FILE": "window_position_app_image_prompt_creator.txt",
    "BASE_FOLDER": ".",
    "DEFAULT_TXT_PATH": "image_prompt_parts.txt",
    "DEFAULT_DB_PATH": "image_prompt_parts.db",
    "EXCLUSION_CSV": "exclusion_targets.csv",
    "ARRANGE_PRESETS_YAML": "arrange_presets.yaml",
    "TAIL_PRESETS_YAML": "tail_presets.yaml",
    "DEDUPLICATE_PROMPTS": True,
    "LLM_ENABLED": False,
    "LLM_MODEL": DEFAULT_LLM_MODEL,
    "LLM_MAX_COMPLETION_TOKENS": 4500,
    "LLM_TIMEOUT": 30,
    "OPENAI_API_KEY_ENV": "OPENAI_API_KEY",
    "LLM_INCLUDE_TEMPERATURE": False,
    "LLM_TEMPERATURE": 0.7,
}

SETTINGS_SNAPSHOT_KEYS = [
    "BASE_FOLDER",
    "DEFAULT_DB_PATH",
    "EXCLUSION_CSV",
    "ARRANGE_PRESETS_YAML",
    "TAIL_PRESETS_YAML",
    "LLM_ENABLED",
    "LLM_MODEL",
    "LLM_MAX_COMPLETION_TOKENS",
    "LLM_TIMEOUT",
    "LLM_INCLUDE_TEMPERATURE",
]

# 設定読み込み中の警告やフォールバック内容を貯めて、ウィンドウ生成後にまとめて案内する。
SETTINGS_LOAD_NOTES: List[str] = []


def _coerce_json_safe(value):
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (Path, datetime)):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _coerce_json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_coerce_json_safe(v) for v in value]
    return str(value)


def log_structured(level: int, event: str, context: Optional[dict] = None) -> None:
    """環境依存の調査を容易にするため、ホスト名と経路情報を含む構造化ログを出力する。"""

    payload = {"event": event, "hostname": HOSTNAME}
    if context:
        safe_context = {str(k): _coerce_json_safe(v) for k, v in context.items()}
        payload.update(safe_context)
    logging.log(level, json.dumps(payload, ensure_ascii=False))


def _normalize_language_code(code: Optional[str]) -> str:
    """UIなどから受け取った言語コードを 'en' / 'ja' のいずれかへ正規化する。"""

    return "ja" if code == "ja" else "en"


def _language_directives(code: Optional[str]) -> Tuple[str, str, str]:
    """LLMプロンプトに埋め込む言語指定（コード/ラベル/指示文）をまとめて返す。"""

    normalized = _normalize_language_code(code)
    if normalized == "ja":
        label = "Japanese"
        instruction = (
            "Output language: Japanese. Respond ONLY in Japanese sentences except for unavoidable proper nouns."
        )
    else:
        label = "English"
        instruction = "Output language: English. Respond ONLY in English sentences."
    return normalized, label, instruction


def _combo_language_code(combo: Optional[QtWidgets.QComboBox]) -> str:
    """コンボボックスの userData から言語コードを取り出し、正規化して返す。"""

    if combo is None:
        return "en"
    data = combo.currentData()
    return _normalize_language_code(data if isinstance(data, str) else None)


def _create_language_combo() -> QtWidgets.QComboBox:
    """英語/日本語の2択を持つコンボボックスを生成する。"""

    combo = QtWidgets.QComboBox()
    for label, code in LANGUAGE_COMBO_CHOICES:
        combo.addItem(label, userData=code)
    combo.setCurrentIndex(0)
    return combo


def install_global_exception_logger():
    """未捕捉例外やQtメッセージを構造化ログに流し、ターミナル調査を容易にする。"""

    if getattr(install_global_exception_logger, "_installed", False):
        return

    def _handle_exception(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        trace = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
        log_structured(
            logging.CRITICAL,
            "unhandled_exception",
            {
                "exception_type": exc_type.__name__,
                "message": str(exc_value),
                "traceback": trace,
            },
        )

    sys.excepthook = _handle_exception

    def _qt_message_handler(mode, context, message):
        level_map = {
            QtCore.QtDebugMsg: logging.DEBUG,
            QtCore.QtInfoMsg: logging.INFO,
            QtCore.QtWarningMsg: logging.WARNING,
            QtCore.QtCriticalMsg: logging.ERROR,
            QtCore.QtFatalMsg: logging.CRITICAL,
        }
        payload = {
            "category": getattr(context, "category", ""),
            "file": getattr(context, "file", ""),
            "line": getattr(context, "line", 0),
            "function": getattr(context, "function", ""),
            "message": message,
        }
        log_structured(level_map.get(mode, logging.INFO), "qt_message", payload)
        if mode == QtCore.QtFatalMsg:
            raise SystemExit(1)

    try:
        QtCore.qInstallMessageHandler(_qt_message_handler)
    except Exception:
        logging.getLogger(__name__).debug("Qt message handler installation skipped.", exc_info=True)

    install_global_exception_logger._installed = True


def log_startup_environment():
    """アプリ起動直後の実行環境を計測し、障害再現を容易にする。"""

    payload = {
        "python_version": platform.python_version(),
        "executable": sys.executable,
        "cwd": os.getcwd(),
        "script_dir": str(SCRIPT_DIR),
        "default_db_path": DEFAULT_DB_PATH,
        "settings_path": str(_resolve_path("desktop_gui_settings.yaml")),
        "qt_version": QtCore.qVersion(),
        "hostname": HOSTNAME,
    }
    log_structured(logging.INFO, "startup_environment", payload)


def _show_missing_export_module_dialog() -> None:
    """CSVエクスポートモジュール欠損時の案内をダイアログで提示する。"""

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


def _load_export_module():
    """MJImage の実体を起動時にロードし、欠損時は代替を返す。"""

    try:
        module = importlib.import_module("export_prompts_to_csv")
        return module.MJImage
    except Exception as exc:
        log_structured(logging.ERROR, "export_module_missing", {"error": str(exc)})
        _show_missing_export_module_dialog()

        class _MissingMJImage:
            """欠損時でもボタン押下で案内を出せるプレースホルダー。"""

            def run(self):
                _show_missing_export_module_dialog()

        return _MissingMJImage


MJImage = _load_export_module()


def _resolve_path(path_value, base_dir=SCRIPT_DIR):
    if path_value is None:
        return base_dir
    if isinstance(path_value, Path):
        path = path_value
    else:
        path = Path(str(path_value))
    if path.is_absolute():
        return path
    return base_dir / path


def _prompt_settings_path(parent: Optional[QtWidgets.QWidget], resolved_path: Path) -> Optional[Path]:
    """設定ファイル欠損時に、ユーザーへパス確認/再指定を促すダイアログを表示。"""

    app = QtWidgets.QApplication.instance()
    if app is None:
        SETTINGS_LOAD_NOTES.append(
            f"設定ファイルが見つからないためデフォルト設定を使用しました: {resolved_path}"
        )
        return None

    dialog = QtWidgets.QMessageBox(parent)
    dialog.setWindowTitle("設定ファイルが見つかりません")
    dialog.setText("設定ファイル desktop_gui_settings.yaml が見つかりませんでした。")
    dialog.setInformativeText(
        "デフォルト設定で続行するか、正しいYAMLファイルを選択してください。"
    )
    use_default_button = dialog.addButton("デフォルト設定を使う", QtWidgets.QMessageBox.AcceptRole)
    choose_file_button = dialog.addButton("ファイルを選択", QtWidgets.QMessageBox.ActionRole)
    dialog.exec()

    if dialog.clickedButton() == choose_file_button:
        file_path, _ = QtWidgets.QFileDialog.getOpenFileName(
            parent,
            "設定ファイルを選択",
            str(resolved_path.parent),
            "YAML Files (*.yaml *.yml);;All Files (*)",
        )
        if file_path:
            return Path(file_path)
    elif dialog.clickedButton() != use_default_button:
        SETTINGS_LOAD_NOTES.append(
            "設定ファイルの選択をキャンセルしたため、デフォルト設定で続行しました。"
        )
    return None


def _handle_yaml_error(parent: Optional[QtWidgets.QWidget], resolved_path: Path, error: Exception):
    """YAML構文エラーを要約し、再試行手順を案内する。"""

    error_summary = str(error)
    location_hint = ""
    if hasattr(error, "problem_mark") and getattr(error, "problem_mark"):
        mark = error.problem_mark
        location_hint = f" (行 {mark.line + 1}, 列 {mark.column + 1})"

    message = (
        f"設定ファイルの構文エラーを検出しました: {resolved_path}{location_hint}\n"
        "ファイルを修正するか、別の設定ファイルを選択して再試行してください。"
    )
    SETTINGS_LOAD_NOTES.append(message)

    app = QtWidgets.QApplication.instance()
    if app is None:
        return None

    dialog = QtWidgets.QMessageBox(parent)
    dialog.setWindowTitle("設定ファイルの読み込みに失敗")
    dialog.setText("YAMLの構文エラーが発生しました。")
    dialog.setInformativeText(message)
    dialog.setDetailedText(error_summary)
    dialog.setStandardButtons(QtWidgets.QMessageBox.Retry | QtWidgets.QMessageBox.Cancel)
    retry_path_button = dialog.addButton("別のファイルを選ぶ", QtWidgets.QMessageBox.ActionRole)
    dialog.exec()

    if dialog.clickedButton() == retry_path_button:
        file_path, _ = QtWidgets.QFileDialog.getOpenFileName(
            parent,
            "設定ファイルを選択",
            str(resolved_path.parent),
            "YAML Files (*.yaml *.yml);;All Files (*)",
        )
        if file_path:
            return Path(file_path)
    elif dialog.standardButton(dialog.clickedButton()) == QtWidgets.QMessageBox.Retry:
        return resolved_path
    return None


def load_yaml_settings(file_path, parent: Optional[QtWidgets.QWidget] = None):
    """YAML設定のロードを安全に行い、失敗時はフォールバックや再選択を提示する。"""

    resolved_path = _resolve_path(file_path)
    log_structured(logging.INFO, "yaml_settings_load_start", {"path": str(resolved_path)})
    try:
        with open(resolved_path, "r", encoding="utf-8") as file:
            settings = yaml.safe_load(file) or {}
        log_structured(
            logging.INFO,
            "yaml_settings_load_success",
            {
                "path": str(resolved_path),
                "section_keys": sorted(settings.keys()) if isinstance(settings, dict) else [],
            },
        )
        return settings
    except FileNotFoundError:
        log_structured(logging.WARNING, "yaml_settings_missing", {"path": str(resolved_path)})
        alternative = _prompt_settings_path(parent, resolved_path)
        if alternative:
            return load_yaml_settings(alternative, parent)
    except yaml.YAMLError as error:
        log_structured(
            logging.ERROR,
            "yaml_settings_parse_error",
            {
                "path": str(resolved_path),
                "error": str(error),
            },
        )
        retry_target = _handle_yaml_error(parent, resolved_path, error)
        if retry_target:
            return load_yaml_settings(retry_target, parent)
    log_structured(logging.INFO, "yaml_settings_fallback_default", {"path": str(resolved_path)})
    return deepcopy({"app_image_prompt_creator": DEFAULT_APP_SETTINGS})


# YAML設定の読込（Tk版と互換性維持）
import yaml

yaml_settings_path = _resolve_path("desktop_gui_settings.yaml")
settings = {"app_image_prompt_creator": deepcopy(DEFAULT_APP_SETTINGS)}
BASE_FOLDER = DEFAULT_APP_SETTINGS["BASE_FOLDER"]
DEFAULT_TXT_PATH = DEFAULT_APP_SETTINGS["DEFAULT_TXT_PATH"]
DEFAULT_DB_PATH = DEFAULT_APP_SETTINGS["DEFAULT_DB_PATH"]
POSITION_FILE = DEFAULT_APP_SETTINGS["POSITION_FILE"]
EXCLUSION_CSV = DEFAULT_APP_SETTINGS["EXCLUSION_CSV"]
DEDUPLICATE_PROMPTS = DEFAULT_APP_SETTINGS["DEDUPLICATE_PROMPTS"]
LLM_ENABLED = DEFAULT_APP_SETTINGS["LLM_ENABLED"]
LLM_MODEL = DEFAULT_APP_SETTINGS["LLM_MODEL"]
LLM_TEMPERATURE = DEFAULT_APP_SETTINGS["LLM_TEMPERATURE"]
LLM_MAX_COMPLETION_TOKENS = DEFAULT_APP_SETTINGS["LLM_MAX_COMPLETION_TOKENS"]
LLM_TIMEOUT = DEFAULT_APP_SETTINGS["LLM_TIMEOUT"]
OPENAI_API_KEY_ENV = DEFAULT_APP_SETTINGS["OPENAI_API_KEY_ENV"]
ARRANGE_PRESETS_YAML = str(_resolve_path(DEFAULT_APP_SETTINGS["ARRANGE_PRESETS_YAML"]))
TAIL_PRESETS_YAML = str(_resolve_path(DEFAULT_APP_SETTINGS["TAIL_PRESETS_YAML"]))
LLM_INCLUDE_TEMPERATURE = DEFAULT_APP_SETTINGS["LLM_INCLUDE_TEMPERATURE"]


def _merge_app_settings(raw_settings: dict) -> dict:
    """読み込んだ設定をデフォルトにマージして欠損値を補完する。"""

    merged = {"app_image_prompt_creator": deepcopy(DEFAULT_APP_SETTINGS)}
    if isinstance(raw_settings, dict):
        merged_app = raw_settings.get("app_image_prompt_creator") or {}
        merged["app_image_prompt_creator"].update(merged_app)
    return merged


def _normalize_llm_model(model_name: Optional[str]) -> str:
    """設定値のモデル名を検証し、無効なら最初の有効モデルへフォールバックする。"""

    if model_name in AVAILABLE_LLM_MODELS:
        return model_name

    fallback_model = AVAILABLE_LLM_MODELS[0]
    SETTINGS_LOAD_NOTES.append(
        f"無効なLLMモデル '{model_name}' を検出したため '{fallback_model}' へフォールバックしました。"
    )
    log_structured(
        logging.WARNING,
        "llm_model_invalid_fallback",
        {
            "invalid_model": model_name,
            "fallback_model": fallback_model,
        },
    )
    return fallback_model


def _apply_app_settings(app_settings: dict):
    """マージ済み設定をグローバル変数へ適用する。"""

    global BASE_FOLDER, DEFAULT_TXT_PATH, DEFAULT_DB_PATH, POSITION_FILE, EXCLUSION_CSV, DEDUPLICATE_PROMPTS
    global LLM_ENABLED, LLM_MODEL, LLM_TEMPERATURE, LLM_MAX_COMPLETION_TOKENS
    global LLM_TIMEOUT, OPENAI_API_KEY_ENV, ARRANGE_PRESETS_YAML, TAIL_PRESETS_YAML, LLM_INCLUDE_TEMPERATURE, settings

    settings = {"app_image_prompt_creator": deepcopy(app_settings)}
    BASE_FOLDER = str(_resolve_path(app_settings.get("BASE_FOLDER", DEFAULT_APP_SETTINGS["BASE_FOLDER"])))
    DEFAULT_TXT_PATH = str(_resolve_path(app_settings.get("DEFAULT_TXT_PATH", DEFAULT_APP_SETTINGS["DEFAULT_TXT_PATH"])))
    DEFAULT_DB_PATH = str(_resolve_path(app_settings.get("DEFAULT_DB_PATH", DEFAULT_APP_SETTINGS["DEFAULT_DB_PATH"])))
    POSITION_FILE = str(_resolve_path(app_settings.get("POSITION_FILE", DEFAULT_APP_SETTINGS["POSITION_FILE"])))
    EXCLUSION_CSV = str(_resolve_path(app_settings.get("EXCLUSION_CSV", DEFAULT_APP_SETTINGS["EXCLUSION_CSV"])))
    DEDUPLICATE_PROMPTS = app_settings.get("DEDUPLICATE_PROMPTS", DEFAULT_APP_SETTINGS["DEDUPLICATE_PROMPTS"])
    LLM_ENABLED = app_settings.get("LLM_ENABLED", DEFAULT_APP_SETTINGS["LLM_ENABLED"])
    LLM_MODEL = _normalize_llm_model(app_settings.get("LLM_MODEL", DEFAULT_APP_SETTINGS["LLM_MODEL"]))
    LLM_TEMPERATURE = app_settings.get("LLM_TEMPERATURE", DEFAULT_APP_SETTINGS["LLM_TEMPERATURE"])
    LLM_MAX_COMPLETION_TOKENS = app_settings.get(
        "LLM_MAX_COMPLETION_TOKENS", DEFAULT_APP_SETTINGS["LLM_MAX_COMPLETION_TOKENS"]
    )
    LLM_TIMEOUT = app_settings.get("LLM_TIMEOUT", DEFAULT_APP_SETTINGS["LLM_TIMEOUT"])
    OPENAI_API_KEY_ENV = app_settings.get("OPENAI_API_KEY_ENV", DEFAULT_APP_SETTINGS["OPENAI_API_KEY_ENV"])
    ARRANGE_PRESETS_YAML = str(
        _resolve_path(app_settings.get("ARRANGE_PRESETS_YAML", DEFAULT_APP_SETTINGS["ARRANGE_PRESETS_YAML"]))
    )
    TAIL_PRESETS_YAML = str(
        _resolve_path(app_settings.get("TAIL_PRESETS_YAML", DEFAULT_APP_SETTINGS["TAIL_PRESETS_YAML"]))
    )
    LLM_INCLUDE_TEMPERATURE = app_settings.get(
        "LLM_INCLUDE_TEMPERATURE", DEFAULT_APP_SETTINGS["LLM_INCLUDE_TEMPERATURE"]
    )
    settings["app_image_prompt_creator"]["LLM_MODEL"] = LLM_MODEL
    snapshot = {k.lower(): app_settings.get(k) for k in SETTINGS_SNAPSHOT_KEYS if k in app_settings}
    log_structured(logging.INFO, "app_settings_applied", snapshot)


def initialize_settings(parent: Optional[QtWidgets.QWidget] = None):
    """設定ファイルを読み込み、フォールバック結果を反映する初期化関数。"""

    raw_settings = load_yaml_settings(yaml_settings_path, parent)
    merged_settings = _merge_app_settings(raw_settings)
    _apply_app_settings(merged_settings["app_image_prompt_creator"])


def show_deferred_settings_notes(parent: Optional[QtWidgets.QWidget]):
    """アプリ起動後にまとめて設定読み込み時の警告を表示する。"""

    if not SETTINGS_LOAD_NOTES:
        return
    QtWidgets.QMessageBox.information(
        parent,
        "設定ファイルの確認",
        "\n\n".join(SETTINGS_LOAD_NOTES),
    )
    SETTINGS_LOAD_NOTES.clear()


# =============================
# ユーティリティ
# =============================
def get_exception_trace() -> str:
    t, v, tb = sys.exc_info()
    trace = traceback.format_exception(t, v, tb)
    return "".join(trace)


def load_exclusion_words() -> List[str]:
    try:
        with open(EXCLUSION_CSV, "r", encoding="utf-8", newline="") as file:
            reader = csv.reader(file, quotechar='"', quoting=csv.QUOTE_ALL)
            return [""] + [row[0] for row in reader if row]
    except FileNotFoundError:
        return [""]


def load_arrange_presets_from_yaml() -> None:
    """アレンジプリセット YAML を読み込み、グローバルな ARRANGE_PRESETS を更新する。

    Tk版と同じ `presets` 配列スキーマを想定し、id/label/guidance を正規化して保持する。
    読み込みに失敗した場合は DEFAULT_ARRANGE_PRESETS を使用する。
    """

    global ARRANGE_PRESETS

    path = Path(ARRANGE_PRESETS_YAML)
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
        ARRANGE_PRESETS = normalized or deepcopy(DEFAULT_ARRANGE_PRESETS)
        log_structured(
            logging.INFO,
            "arrange_presets_yaml_loaded",
            {"path": str(path), "count": len(ARRANGE_PRESETS)},
        )
    except FileNotFoundError:
        log_structured(
            logging.WARNING,
            "arrange_presets_yaml_missing",
            {"path": str(path)},
        )
        ARRANGE_PRESETS = deepcopy(DEFAULT_ARRANGE_PRESETS)
    except Exception as error:
        log_structured(
            logging.ERROR,
            "arrange_presets_yaml_error",
            {"path": str(path), "error": str(error)},
        )
        ARRANGE_PRESETS = deepcopy(DEFAULT_ARRANGE_PRESETS)


def _normalize_tail_presets(raw_presets: dict) -> dict:
    """YAML から読んだ末尾プリセット定義を内部表現に正規化する。

    - キー: メディア種別（image / movie など）
    - 値: {"description_ja": str, "prompt": str} の配列
    """

    if not isinstance(raw_presets, dict):
        return deepcopy(DEFAULT_TAIL_PRESETS)

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

    # 1つも正規化できなければデフォルトへフォールバック
    if not normalized:
        return deepcopy(DEFAULT_TAIL_PRESETS)
    return normalized


def load_tail_presets_from_yaml() -> None:
    """末尾プリセット YAML を読み込み、グローバルな TAIL_PRESETS を更新する。

    YAML が欠損・パースエラー・スキーマ不正の場合は、DEFAULT_TAIL_PRESETS へフォールバックする。
    """

    global TAIL_PRESETS

    path = Path(TAIL_PRESETS_YAML)
    if not path.exists():
        log_structured(
            logging.WARNING,
            "tail_presets_yaml_missing",
            {"path": str(path)},
        )
        TAIL_PRESETS = deepcopy(DEFAULT_TAIL_PRESETS)
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
        TAIL_PRESETS = deepcopy(DEFAULT_TAIL_PRESETS)
        return
    except OSError as error:
        log_structured(
            logging.ERROR,
            "tail_presets_yaml_io_error",
            {"path": str(path), "error": str(error)},
        )
        TAIL_PRESETS = deepcopy(DEFAULT_TAIL_PRESETS)
        return

    tails = data.get("tails")
    if not isinstance(tails, dict):
        log_structured(
            logging.WARNING,
            "tail_presets_yaml_invalid_schema",
            {"path": str(path), "reason": "missing_or_non_mapping_tails"},
        )
        TAIL_PRESETS = deepcopy(DEFAULT_TAIL_PRESETS)
        return

    TAIL_PRESETS = _normalize_tail_presets(tails)
    log_structured(
        logging.INFO,
        "tail_presets_yaml_loaded",
        {
            "path": str(path),
            "media_types": list(TAIL_PRESETS.keys()),
        },
    )


def _should_use_responses_api(model_name: str) -> bool:
    if not model_name:
        return False
    target = model_name.strip().lower()
    return any(target.startswith(prefix) for prefix in RESPONSES_MODEL_PREFIXES)


def _build_responses_input(system_prompt: str, user_prompt: str):
    def build_block(role: str, text: str):
        return {
            "role": role,
            "content": [
                {
                    "type": "input_text",
                    "text": text or "",
                }
            ],
        }

    blocks = []
    if system_prompt is not None:
        blocks.append(build_block("system", system_prompt))
    blocks.append(build_block("user", user_prompt or ""))
    return blocks


def _temperature_hint_for_responses(model_name: str, temperature: float) -> str:
    if temperature is None:
        return ""
    if not _should_use_responses_api(model_name):
        return ""
    level = "balanced"
    if temperature <= 0.35:
        level = "precision / low randomness"
    elif temperature >= 0.75:
        level = "bold / high creativity"
    hint = (
        "\n\n[Legacy temperature emulation]\n"
        f"- Treat creativity strength as {level} (legacy temperature {temperature:.2f}).\n"
        "- Mirror the randomness level implied above even though the API ignores `temperature`.\n"
        "- Lower values mean deterministic phrasing; higher values allow freer rewording and bolder stylistic exploration."
    )
    return hint


def _append_temperature_hint(prompt_text: str, model_name: str, temperature: float) -> str:
    hint = _temperature_hint_for_responses(model_name, temperature)
    if hint:
        return f"{prompt_text}{hint}"
    return prompt_text


def _compose_openai_payload(system_prompt: str, user_prompt: str, temperature: float, max_tokens: int, include_temperature: bool, model_name: str):
    model = model_name or LLM_MODEL
    use_responses = _should_use_responses_api(model)
    payload = {"model": model}
    if use_responses:
        payload["input"] = _build_responses_input(system_prompt, user_prompt)
        if max_tokens is not None:
            payload["max_output_tokens"] = max_tokens
        endpoint = RESPONSES_API_URL
        response_kind = "responses"
    else:
        payload["messages"] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        if max_tokens is not None:
            payload["max_completion_tokens"] = max_tokens
        endpoint = CHAT_COMPLETIONS_URL
        response_kind = "chat"
    send_temperature = include_temperature and (temperature is not None) and not use_responses
    if send_temperature:
        payload["temperature"] = temperature
    return endpoint, payload, response_kind


def _parse_openai_response(response_kind: str, data: dict):
    if response_kind == "responses":
        output = data.get("output", [])
        texts: List[str] = []
        finish_reason = ""
        for item in output or []:
            finish_reason = finish_reason or item.get("stop_reason", "")
            if item.get("type") != "message":
                continue
            for content in item.get("content", []):
                if content.get("type") in ("text", "output_text"):
                    texts.append(content.get("text", ""))
        if not texts:
            output_text = data.get("output_text")
            if isinstance(output_text, list):
                texts.append("".join(output_text))
            elif isinstance(output_text, str):
                texts.append(output_text)
        return "".join(texts).strip(), finish_reason or data.get("status", "")
    choices = data.get("choices", [])
    if not choices:
        return "", ""
    message = choices[0].get("message", {}) or {}
    text = (message.get("content") or "").strip()
    finish_reason = choices[0].get("finish_reason", "")
    return text, finish_reason


def _summarize_http_error_response(resp: requests.Response) -> str:
    """OpenAI HTTPエラーの概要を抽出し、リトライ判定やUI表示に使いやすい形にまとめる。"""
    if resp is None:
        return ""
    try:
        data = resp.json()
    except ValueError:
        data = None
    request_id = resp.headers.get("x-request-id") or resp.headers.get("x-requestid")
    summary = ""
    if isinstance(data, dict):
        err = data.get("error") or data
        if isinstance(err, dict):
            parts = []
            if err.get("message"):
                parts.append(f"message='{err['message']}'")
            if err.get("code"):
                parts.append(f"code={err['code']}")
            if err.get("type"):
                parts.append(f"type={err['type']}")
            summary = ", ".join(parts) or str(err)
        else:
            summary = str(err)
    else:
        raw_text = (resp.text or "").strip()
        if len(raw_text) > 600:
            raw_text = raw_text[:600] + "...(truncated)"
        summary = raw_text
    if request_id:
        return f"{summary} (request_id={request_id})"
    return summary


def _build_user_error_message(status_code, summary: str) -> str:
    """ユーザー通知用のLLMエラーメッセージを生成する。"""
    base = f"LLMリクエストに失敗しました (ステータス: {status_code})"
    if summary:
        return f"{base}: {summary}"
    return base


def _log_llm_failure(model_name: str, endpoint: str, status, message: str, retry_count: int):
    """サポート調査しやすいよう、構造化したエントリで失敗ログを残す。"""
    logging.error(
        "event=llm_request_failed model=%s endpoint=%s status=%s retries=%s message=\"%s\"",
        model_name or LLM_MODEL,
        endpoint,
        status,
        retry_count,
        message,
    )


def send_llm_request(api_key: str, system_prompt: str, user_prompt: str, temperature: float, max_tokens: int, timeout: int, model_name: str, include_temperature: bool = True):
    """OpenAI呼び出しを共通化し、限定的リトライとUI向けのエラー情報を併せて返す。"""
    endpoint, payload, response_kind = _compose_openai_payload(system_prompt, user_prompt, temperature, max_tokens, include_temperature, model_name)
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    retry_count = 0
    backoff = 1.0
    max_retries = 2
    while True:
        try:
            resp = requests.post(endpoint, headers=headers, json=payload, timeout=timeout)
            status = resp.status_code
            if (status == 429 or status >= 500) and retry_count < max_retries:
                summary = _summarize_http_error_response(resp)
                user_message = _build_user_error_message(status, summary)
                _log_llm_failure(model_name, endpoint, status, user_message, retry_count)
                retry_count += 1
                time.sleep(backoff)
                backoff *= 2
                continue
            resp.raise_for_status()
            data = resp.json()
            text, finish_reason = _parse_openai_response(response_kind, data)
            return text, finish_reason, data, retry_count, "", status
        except requests.exceptions.HTTPError as http_err:
            resp = getattr(http_err, "response", None)
            status = resp.status_code if resp is not None else "unknown"
            summary = _summarize_http_error_response(resp)
            user_message = _build_user_error_message(status, summary)
            _log_llm_failure(model_name, endpoint, status, user_message, retry_count)
            if isinstance(status, int) and (status == 429 or status >= 500) and retry_count < max_retries:
                retry_count += 1
                time.sleep(backoff)
                backoff *= 2
                continue
            return "", "", None, retry_count, user_message, status
        except requests.exceptions.RequestException as req_err:
            status = getattr(getattr(req_err, "response", None), "status_code", "network_error")
            user_message = _build_user_error_message(status, str(req_err))
            _log_llm_failure(model_name, endpoint, status, user_message, retry_count)
            if retry_count < max_retries:
                retry_count += 1
                time.sleep(backoff)
                backoff *= 2
                continue
            return "", "", None, retry_count, user_message, status


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


class LLMWorker(QtCore.QObject):
    """LLM 呼び出しをバックグラウンドで実行するワーカー。UI スレッドをブロックしない。"""

    finished = QtCore.Signal(str)
    failed = QtCore.Signal(str)

    def __init__(self, text: str, model: str, length_hint: str, length_limit: int = 0, output_language: str = "en"):
        super().__init__()
        self.text = text
        self.model = model
        self.length_hint = length_hint
        self.length_limit = length_limit
        self.output_language = _normalize_language_code(output_language)

    @QtCore.Slot()
    def run(self):
        try:
            api_key = os.getenv(OPENAI_API_KEY_ENV)
            if not api_key:
                self.failed.emit(f"{OPENAI_API_KEY_ENV} が未設定です。環境変数にAPIキーを設定してください。")
                return
            
            limit_instruction = ""
            if self.length_limit > 0:
                limit_instruction = f"\nIMPORTANT: Strictly limit the output to under {self.length_limit} characters."
            _, language_label, language_sentence = _language_directives(self.output_language)

            user_prompt = (
                f"Length adjustment request (target: {self.length_hint})\n"
                f"Instruction: Adjust length ONLY. Preserve meaning, style, and technical parameters.\n"
                f"{language_sentence}\n"
                f"Text: {self.text}"
            )
            system_prompt = _append_temperature_hint(
                "You are a text length adjustment specialist. Keep style but meet length hint."
                + limit_instruction
                + f"\nRespond strictly in {language_label}.",
                self.model,
                LLM_TEMPERATURE,
            )
            content, finish_reason, _, retry_count, error_message, status_code = send_llm_request(
                api_key=api_key,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=LLM_TEMPERATURE,
                max_tokens=LLM_MAX_COMPLETION_TOKENS,
                timeout=LLM_TIMEOUT,
                model_name=self.model,
                include_temperature=LLM_INCLUDE_TEMPERATURE,
            )
            if error_message:
                self.failed.emit(f"{error_message} (リトライ回数: {retry_count}, ステータス: {status_code})")
                return
            if retry_count:
                logging.info("LLM length adjustment succeeded after retries=%s", retry_count)
            if finish_reason in LENGTH_LIMIT_REASONS:
                self.failed.emit("LLM応答がトークン制限に達しました。短くして再試行してください。")
                return
            self.finished.emit(content)
        except Exception:
            self.failed.emit(get_exception_trace())


class MovieLLMWorker(QtCore.QObject):
    """動画用整形のためにメインテキストをLLMで改良するワーカー。"""

    finished = QtCore.Signal(str)
    failed = QtCore.Signal(str)

    def __init__(
        self,
        text: str,
        model: str,
        mode: str,
        details: List[str],
        video_style: str = "",
        length_limit: int = 0,
        output_language: str = "en",
    ):
        super().__init__()
        self.text = text
        self.model = model
        self.mode = mode
        self.details = details or []
        self.video_style = video_style
        self.length_limit = length_limit
        self.output_language = _normalize_language_code(output_language)

    @QtCore.Slot()
    def run(self):
        try:
            api_key = os.getenv(OPENAI_API_KEY_ENV)
            if not api_key:
                self.failed.emit(f"{OPENAI_API_KEY_ENV} が未設定です。環境変数にAPIキーを設定してください。")
                return
            system_prompt, user_prompt = self._build_prompts()
            content, finish_reason, _, retry_count, error_message, status_code = send_llm_request(
                api_key=api_key,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=LLM_TEMPERATURE,
                max_tokens=LLM_MAX_COMPLETION_TOKENS,
                timeout=LLM_TIMEOUT,
                model_name=self.model,
                include_temperature=LLM_INCLUDE_TEMPERATURE,
            )
            if error_message:
                self.failed.emit(f"{error_message} (リトライ回数: {retry_count}, ステータス: {status_code})")
                return
            if retry_count:
                logging.info("Movie prompt transformation succeeded after retries=%s", retry_count)
            if finish_reason in LENGTH_LIMIT_REASONS:
                self.failed.emit("LLM応答がトークン制限に達しました。短くして再試行してください。")
                return
            self.finished.emit((content or "").strip())
        except Exception:
            self.failed.emit(get_exception_trace())

    def _build_prompts(self) -> Tuple[str, str]:
        detail_lines = "\n".join(f"- {d}" for d in self.details)
        
        style_instruction = ""
        if self.video_style:
            style_instruction = (
                f"\n\n[Target Video Style]\n{self.video_style}\n"
                "IMPORTANT: Adapt the visual description (lighting, camera movement, atmosphere) "
                "to strictly match the parameters defined in the Target Video Style above."
            )

        limit_instruction = ""
        if self.length_limit > 0:
            limit_instruction = f"\nIMPORTANT: Strictly limit the output summary to under {self.length_limit} characters."
        _, language_label, language_sentence = _language_directives(self.output_language)

        if self.mode == "world":
            system_prompt = _append_temperature_hint(
                "You refine disjoint visual fragments into one coherent world description for a single 10-second cinematic clip. "
                "Focus on the most impactful visual elements and atmosphere to fit the short duration. "
                f"Do not narrate events in sequence; describe one continuous world in natural {language_label}."
                f"{limit_instruction}\n{language_sentence}",
                self.model,
                LLM_TEMPERATURE,
            )
            user_prompt = (
                "Convert the following fragments into a single connected world description that fits a 10-second video.\n"
                "Omit minor details to keep it concise and impactful.\n"
                f"{style_instruction}\n"
                f"Source summary: {self.text}\n"
                f"Fragments:\n{detail_lines}\n"
                f"{language_sentence}\n"
                f"Output one concise paragraph that links every fragment into one world.{limit_instruction}"
            )
            return system_prompt, user_prompt

        system_prompt = _append_temperature_hint(
            "You craft a single continuous storyboard beat for a 10-second shot. "
            "Ensure actions and camera moves are simple enough to complete within 10 seconds, even if the pace is slightly fast. "
            f"Blend all elements into a flowing moment without hard scene cuts while writing in natural {language_label}."
            f"{limit_instruction}\n{language_sentence}",
            self.model,
            LLM_TEMPERATURE,
        )
        user_prompt = (
            "Turn the fragments into a 10-second single-shot storyboard.\n"
            "Condense the sequence to fit the time limit, merging or simplifying transitions where necessary.\n"
            f"{style_instruction}\n"
            f"Source summary: {self.text}\n"
            f"Fragments:\n{detail_lines}\n"
            f"{language_sentence}\n"
            f"Describe a vivid, fast-paced but coherent sequence in one paragraph, focusing on visual continuity.{limit_instruction}"
        )
        return system_prompt, user_prompt


class ChaosMixLLMWorker(QtCore.QObject):
    """断片化したメインプロンプトを単一シーンへ強制結合するワーカー。"""

    finished = QtCore.Signal(str)
    failed = QtCore.Signal(str)

    def __init__(
        self,
        text: str,
        fragments: List[str],
        model: str,
        video_style: str = "",
        length_limit: int = 0,
        output_language: str = "en",
    ):
        super().__init__()
        self.text = text
        self.fragments = fragments or []
        self.model = model
        self.video_style = video_style
        self.length_limit = length_limit
        self.output_language = _normalize_language_code(output_language)

    @QtCore.Slot()
    def run(self):
        try:
            api_key = os.getenv(OPENAI_API_KEY_ENV)
            if not api_key:
                self.failed.emit(f"{OPENAI_API_KEY_ENV} が未設定です。環境変数にAPIキーを設定してください。")
                return
            system_prompt, user_prompt = self._build_prompts()
            content, finish_reason, _, retry_count, error_message, status_code = send_llm_request(
                api_key=api_key,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=LLM_TEMPERATURE,
                max_tokens=LLM_MAX_COMPLETION_TOKENS,
                timeout=LLM_TIMEOUT,
                model_name=self.model,
                include_temperature=LLM_INCLUDE_TEMPERATURE,
            )
            if error_message:
                self.failed.emit(f"{error_message} (リトライ回数: {retry_count}, ステータス: {status_code})")
                return
            if retry_count:
                logging.info("Chaos mix succeeded after retries=%s", retry_count)
            if finish_reason in LENGTH_LIMIT_REASONS:
                self.failed.emit("LLM応答がトークン制限に達しました。短くして再試行してください。")
                return
            self.finished.emit((content or "").strip())
        except Exception:
            self.failed.emit(get_exception_trace())

    def _build_prompts(self) -> Tuple[str, str]:
        import uuid

        limit_instruction = ""
        if self.length_limit > 0:
            limit_instruction = f"\nIMPORTANT: Keep the final description under {self.length_limit} characters."
        _, language_label, language_sentence = _language_directives(self.output_language)
        language_block = f"\n{language_sentence}"

        detail_lines = "\n".join(f"- {sanitize_to_english(fragment)}" for fragment in self.fragments if fragment)
        if not detail_lines:
            detail_lines = "- (no sentence split detected)"

        anchor_terms = _extract_anchor_terms(self.text, max_terms=8)
        anchor_line = ", ".join(anchor_terms) if anchor_terms else "(none)"
        nonce = uuid.uuid4().hex[:8]

        style_instruction = ""
        if self.video_style:
            style_instruction = (
                f"\n\n[Target Video Style]\n{self.video_style}\n"
                "IMPORTANT: Even though this is a chaotic blended scene, camera work, lighting and atmosphere\n"
                "must still follow the Target Video Style above."
            )

        system_prompt = _append_temperature_hint(
            "You are a chaotic scene blender. Force every fragment from a Midjourney prompt to coexist in the same physical location and the same moment. "
            "Describe the result as one vivid, continuous tableau packed with overlapping motifs, lighting, and props. "
            f"Keep syntax clean, keep it in {language_label}, and never drop the essential nouns from the source."
            f"{limit_instruction}{language_block}",
            self.model,
            LLM_TEMPERATURE,
        )
        user_prompt = (
            "Task: Smash all fragments into a single overwhelming scene. Every subject must appear simultaneously; do NOT split into multiple shots.\n"
            "- Mention the collisions and impossible overlaps explicitly.\n"
            "- Keep anchor terms verbatim where possible.\n"
            "- Treat lighting/atmosphere cues as happening together.\n"
            f"- Output exactly one paragraph in {language_label}.\n"
            f"{limit_instruction}\n"
            f"{language_sentence}\n"
            f"Nonce: {nonce}\n"
            f"{style_instruction}\n"
            f"Original prompt body:\n{sanitize_to_english(self.text)}\n\n"
            f"Sentence fragments:\n{detail_lines}\n"
            f"Anchor terms: {anchor_line}\n"
            "Output:"
        )
        return system_prompt, user_prompt


def sanitize_to_english(text: str) -> str:
    """基本的に英語出力を維持するための軽いサニタイズ。"""
    replacements = {
        "和風": "Japanese style",
        "浮世絵": "ukiyo-e",
        "侍": "samurai",
        "忍者": "ninja",
        "アール・デコ": "Art Deco",
        "アール・ヌーヴォー": "Art Nouveau",
        "水彩画": "watercolor",
        "漫画": "manga",
        "アニメ": "anime",
        "ノワール": "noir",
        "ヴェイパーウェーブ": "vaporwave",
    }
    out = text
    for k, v in replacements.items():
        out = out.replace(k, v)
    return out


def _extract_anchor_terms(text: str, max_terms: int = 8) -> List[str]:
    """原文から保持すべきアンカー語句（名詞・象徴語）を抽出する。"""
    try:
        cleaned = re.sub(r"[^A-Za-z0-9\-\s]", " ", text)
        tokens = [t.strip('-') for t in cleaned.split()]
        tokens = [t for t in tokens if len(t) >= 3]
        priority = {
            'cherry', 'blossom', 'blossoms', 'lantern', 'lanterns', 'temple', 'shrine', 'garden',
            'tea', 'bamboo', 'maple', 'zen', 'wabi', 'sabi', 'imperfection', 'architecture', 'wood', 'paper',
            'stone', 'bridge', 'pond', 'kimono', 'tatami', 'shoji', 'bonsai'
        }
        scored = []
        for t in tokens:
            score = 1
            lt = t.lower()
            if lt in priority:
                score += 3
            if any(k in lt for k in ['garden', 'temple', 'shrine', 'lantern', 'blossom', 'bamboo', 'maple', 'tea', 'zen']):
                score += 1
            scored.append((score, t))
        scored.sort(reverse=True)
        anchors = []
        seen = set()
        for _, w in scored:
            lw = w.lower()
            if lw not in seen:
                anchors.append(w)
                seen.add(lw)
            if len(anchors) >= max_terms:
                break
        return anchors
    except Exception:
        return []


def _generate_hybrid_cues(anchors: List[str], preset: str, guidance: str, max_items: int = 5) -> List[str]:
    """アンカー語をスタイル語彙と合成し、ハイブリッド化を促すサジェストを生成する。"""
    try:
        if not anchors:
            return []
        preset_l = (preset or "").lower()
        guidance_l = (guidance or "").lower()
        
        keys = [preset_l, guidance_l]
        style = "generic"
        if any("cyber" in k for k in keys):
            style = "cyberpunk"
        elif any("noir" in k for k in keys):
            style = "noir"
        elif any(k in ("sci-fi", "scifi", "science fiction") for k in keys):
            style = "scifi"
        elif any("vapor" in k for k in keys):
            style = "vaporwave"
            
        vocab = {
            "cyberpunk": {
                "materials": ["brushed metal", "titanium inlays", "carbon-fiber", "chromed edges", "micro-etched steel", "polymer plates"],
                "lighting": ["neon rim-light", "cyan underglow", "magenta accent light", "dynamic LED seams", "HUD glow", "soft holographic glow"],
                "vfx": ["holographic flicker", "pixel shimmer", "AR overlay", "scanline sheen", "glitch speckles", "volumetric haze"],
                "detail": ["micro-circuit veins", "fiber-optic threads", "embedded sensors", "heat vents", "panel seams", "thin cabling"]
            },
            "noir": {
                "materials": ["matte enamel", "lacquered wood", "worn steel", "velvet texture"],
                "lighting": ["hard rim-light", "moody backlight", "rain-soaked reflections", "venetian blind shadows"],
                "vfx": ["film grain", "soft bloom", "cigarette smoke wisps"],
                "detail": ["sleek rivets", "aged patina", "subtle scratches"]
            },
            "scifi": {
                "materials": ["brushed alloy", "ceramic composite", "graphene panels", "satin titanium"],
                "lighting": ["cool rim-light", "ambient panel glow", "bioluminescent accents"],
                "vfx": ["force-field shimmer", "ionized haze", "specular flares"],
                "detail": ["hex-mesh patterns", "micro-actuators", "servo joints"]
            },
            "vaporwave": {
                "materials": ["pastel plastic", "glossy acrylic", "pearlescent enamel"],
                "lighting": ["pink-cyan gradient glow", "retro grid light", "soft bloom"],
                "vfx": ["CRT scanlines", "pixel dust", "checkerboard reflections"],
                "detail": ["chrome trims", "90s decals", "retro stickers"]
            },
            "generic": {
                "materials": ["brushed metal", "ceramic-metal composite", "polished steel"],
                "lighting": ["edge underglow", "accent rim-light", "soft backlight"],
                "vfx": ["subtle holographic shimmer", "fine grain", "soft bloom"],
                "detail": ["micro-engraving", "thin inlays", "fiber threads"]
            }
        }
        lex = vocab.get(style, vocab["generic"])
        templates = [
            "{a} with {materials} accents and {lighting}",
            "{a} featuring {detail} and a hint of {vfx}",
            "part of the {a} converted to {materials} with {lighting}",
            "{a} showing {detail} beneath the surface and subtle {vfx}",
            "{a} integrating {materials} inlays and {lighting}"
        ]
        cues = []
        for i, a in enumerate(anchors):
            if len(cues) >= max_items:
                break
            t = templates[i % len(templates)]
            cue = t.format(
                a=a,
                materials=lex["materials"][i % len(lex["materials"])],
                lighting=lex["lighting"][i % len(lex["lighting"])],
                vfx=lex["vfx"][i % len(lex["vfx"])],
                detail=lex["detail"][i % len(lex["detail"])],
            )
            cues.append(cue)
        return cues
    except Exception:
        return []


class ArrangeLLMWorker(QtCore.QObject):
    """画像プロンプトのアレンジ・リファインを実行するワーカー。"""

    finished = QtCore.Signal(str)
    failed = QtCore.Signal(str)

    def __init__(
        self,
        text: str,
        model: str,
        preset_label: str,
        strength: int,
        guidance: str,
        length_adjust: str,
        length_limit: int,
        output_language: str,
    ):
        super().__init__()
        self.text = text
        self.model = model
        self.preset_label = preset_label
        self.strength = strength
        self.guidance = guidance
        self.length_adjust = length_adjust
        self.length_limit = length_limit
        self.output_language = _normalize_language_code(output_language)

    @QtCore.Slot()
    def run(self):
        try:
            api_key = os.getenv(OPENAI_API_KEY_ENV)
            if not api_key:
                self.failed.emit(f"{OPENAI_API_KEY_ENV} が未設定です。環境変数にAPIキーを設定してください。")
                return

            # 文字数目標の計算
            original_length = len(self.text)
            length_multipliers = {
                "半分": 0.5,
                "2割減": 0.8,
                "同程度": 1.0,
                "2割増": 1.2,
                "倍": 2.0
            }
            multiplier = length_multipliers.get(self.length_adjust, 1.0)
            target_length = int(original_length * multiplier)

            # ブレンド・アンカー・ハイブリッド
            blend_weight_map = {0: 20, 1: 35, 2: 65, 3: 80}
            blend_weight = blend_weight_map.get(self.strength, 55)
            anchor_terms = _extract_anchor_terms(self.text, max_terms=8)
            hybrid_cues = _generate_hybrid_cues(anchor_terms, self.preset_label, self.guidance, max_items=5)
            must_keep_count = 3 if self.strength <= 2 else 2

            strength_descriptions = {
                0: "Apply very subtle, minimal changes. Keep almost everything the same, just minor word improvements.",
                1: "Apply gentle, tasteful variations. Improve wording and style while keeping the core concept intact.",
                2: "Apply moderate creative variations. Enhance style, add vivid descriptors, and improve composition.",
                3: "Apply bold, creative transformations. Enhance style and add dramatic descriptors while preserving the original subject and key elements."
            }
            strength_instruction = strength_descriptions.get(self.strength, strength_descriptions[2])

            system_prompt = ""
            user_prompt = ""
            
            import uuid
            nonce = uuid.uuid4().hex[:8]

            limit_instruction = ""
            if self.length_limit > 0:
                limit_instruction = f"\nIMPORTANT: Strictly limit the output to under {self.length_limit} characters."
            _, _, language_sentence = _language_directives(self.output_language)
            language_block = f"\n{language_sentence}"

            # 強度3用のプロンプト
            if self.strength == 3:
                system_prompt = (
                    f"You are a creative prompt artist. Transform this Midjourney prompt with {strength_instruction}. "
                    f"If guidance is provided, it SHOULD influence style but MUST BLEND with the original content. "
                    f"Do NOT eliminate original cultural/subject elements; preserve and merge them with the guidance. "
                    f"Be BOLD and CREATIVE - enhance the visual style with dramatic effects and vivid cinematic language. "
                    f"Output only the transformed prompt.{limit_instruction}{language_block}"
                )
                user_prompt = (
                    f"Preset: {self.preset_label}, Strength: {self.strength} (MAXIMUM CREATIVITY)\n"
                    f"Nonce: {nonce}\n"
                    + (f"Guidance: {self.guidance}\n" if self.guidance else "") +
                    f"Blend weight target: ~{blend_weight}% guidance / ~{100 - blend_weight}% original\n"
                    + (f"Anchor terms (verbatim): {', '.join(anchor_terms)}\n" if anchor_terms else "") +
                    f"CRITICAL: Include at least {must_keep_count} of the anchor terms verbatim. Keep the original subject and cultural motifs.\n"
                    + ("Hybridization suggestions: " + "; ".join(hybrid_cues) + "\n" if hybrid_cues else "") +
                    f"Length adjustment: {self.length_adjust} (target: ~{target_length} chars, original: {original_length} chars)\n"
                    f"CRITICAL: Make the output {'shorter' if target_length < original_length else 'longer' if target_length > original_length else 'similar'} than the original\n"
                    f"{language_sentence}\n"
                    f"Prompt: {self.text}{limit_instruction}"
                )
            else:
                # 通常(0-2)用のプロンプト
                guidance_instruction = ""
                if self.strength == 0:
                    guidance_instruction = "Apply guidance very subtly if at all. Focus on minimal improvements."
                elif self.strength == 1:
                    guidance_instruction = "Apply guidance gently. Blend it subtly with the original content."
                elif self.strength == 2:
                    guidance_instruction = "Apply guidance moderately. Enhance the style while keeping core elements."
                
                system_prompt = (
                    f"Rewrite Midjourney prompts with {strength_instruction}. "
                    f"{guidance_instruction} "
                    f"Keep core content. Output only the prompt.{limit_instruction}{language_block}"
                )
                user_prompt = (
                    f"Preset: {self.preset_label}, Strength: {self.strength} (0=minimal, 3=bold)\n"
                    f"Nonce: {nonce}\n"
                    + (f"Guidance: {self.guidance}\n" if self.guidance else "") +
                    f"Guidance instruction: {guidance_instruction}\n"
                    f"Blend weight target: ~{blend_weight}% guidance / ~{100 - blend_weight}% original\n"
                    + (f"Anchor terms (verbatim): {', '.join(anchor_terms)}\n" if anchor_terms else "") +
                    f"CRITICAL: Include at least {must_keep_count} of the anchor terms verbatim. Keep the original subject and cultural motifs.\n"
                    + ("Hybridization suggestions: " + "; ".join(hybrid_cues) + "\n" if hybrid_cues else "") +
                    f"Length adjustment: {self.length_adjust} (target: ~{target_length} chars, original: {original_length} chars)\n"
                    f"CRITICAL: Make the output {'shorter' if target_length < original_length else 'longer' if target_length > original_length else 'similar'} than the original\n"
                    f"{language_sentence}\n"
                    f"Prompt: {self.text}{limit_instruction}"
                )

            system_prompt = _append_temperature_hint(system_prompt, self.model, LLM_TEMPERATURE)

            content, finish_reason, _, retry_count, error_message, status_code = send_llm_request(
                api_key=api_key,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=LLM_TEMPERATURE,
                max_tokens=LLM_MAX_COMPLETION_TOKENS,
                timeout=LLM_TIMEOUT,
                model_name=self.model,
                include_temperature=LLM_INCLUDE_TEMPERATURE,
            )

            if error_message:
                self.failed.emit(f"{error_message} (リトライ回数: {retry_count}, ステータス: {status_code})")
                return
            
            if finish_reason in LENGTH_LIMIT_REASONS:
                self.failed.emit("LLM応答がトークン制限に達しました。短くして再試行してください。")
                return

            self.finished.emit((content or "").strip())

        except Exception:
            self.failed.emit(get_exception_trace())



class GeneratePromptLLMWorker(QtCore.QObject):
    """通常生成をLLMでまとめて行うワーカー。行数と属性条件からプロンプト群を生成する。"""

    finished = QtCore.Signal(str)
    failed = QtCore.Signal(str)

    def __init__(
        self,
        model: str,
        total_lines: int,
        attribute_conditions: List[dict],
        exclusion_words: List[str],
        chaos_level: int,
        output_language: str = "en",
    ):
        super().__init__()
        self.model = model
        self.total_lines = max(1, int(total_lines) if total_lines else 1)
        self.attribute_conditions = attribute_conditions or []
        self.exclusion_words = exclusion_words or []
        # LLM生成時の出力言語（en: 英語, ja: 日本語）。想定外の値は英語にフォールバックする。
        self.output_language = output_language if output_language in ("en", "ja") else "en"
        # カオス度スライダーの値（1〜10）を安全に正規化して保持する
        try:
            level = int(chaos_level)
        except Exception:
            level = 1
        self.chaos_level = max(1, min(10, level))

    def _effective_temperature(self) -> float:
        """カオス度から、このワーカー専用の実効temperatureを算出する。"""

        base = LLM_TEMPERATURE if LLM_TEMPERATURE is not None else 0.7
        center_level = 5.0  # レベル5付近で base と同程度の温度
        span = 0.6          # レベル差による最大±0.3程度の揺らぎ
        delta = (self.chaos_level - center_level) / 9.0
        temp = base + delta * span
        return max(0.1, min(1.5, temp))

    @QtCore.Slot()
    def run(self):
        try:
            api_key = os.getenv(OPENAI_API_KEY_ENV)
            if not api_key:
                self.failed.emit(f"{OPENAI_API_KEY_ENV} が未設定です。環境変数にAPIキーを設定してください。")
                return
            effective_temp = self._effective_temperature()
            system_prompt, user_prompt = self._build_prompts(effective_temp)
            content, finish_reason, _, retry_count, error_message, status_code = send_llm_request(
                api_key=api_key,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=effective_temp,
                max_tokens=LLM_MAX_COMPLETION_TOKENS,
                timeout=LLM_TIMEOUT,
                model_name=self.model,
                include_temperature=LLM_INCLUDE_TEMPERATURE,
            )
            if error_message:
                self.failed.emit(f"{error_message} (リトライ回数: {retry_count}, ステータス: {status_code})")
                return
            if retry_count:
                logging.info(
                    "Prompt LLM generation succeeded after retries=%s (chaos_level=%s, effective_temp=%.3f)",
                    retry_count,
                    self.chaos_level,
                    effective_temp,
                )
            if finish_reason in LENGTH_LIMIT_REASONS:
                self.failed.emit("LLM応答がトークン制限に達しました。行数を減らすかプロンプトを短くして再試行してください。")
                return
            self.finished.emit((content or "").strip())
        except Exception:
            self.failed.emit(get_exception_trace())

    def _build_prompts(self, temperature: float) -> Tuple[str, str]:
        """通常生成用の属性条件と除外語句から、LLMへのプロンプトを構築する。"""

        attr_lines: List[str] = []
        for cond in self.attribute_conditions:
            name = str(cond.get("attribute_name", "") or "")
            detail = str(cond.get("detail", "") or "")
            requested = cond.get("requested_count", 0) or 0
            if requested > 0:
                line = f"- {detail} (attribute: {name}, approx {requested} fragments)"
            else:
                line = f"- {detail} (attribute: {name})"
            attr_lines.append(line)

        if attr_lines:
            attr_block = "\n".join(attr_lines)
        else:
            attr_block = "- (no specific attribute constraints; freely mix subjects, environments, materials and styles)"

        if self.exclusion_words:
            excl_block = ", ".join(sorted({w for w in self.exclusion_words if w}))
        else:
            excl_block = "(none)"

        # カオス度に応じた説明テキスト（LLM側の挙動を人間が直感しやすいようにする）
        if self.chaos_level <= 2:
            chaos_desc = "very stable, low randomness"
        elif self.chaos_level <= 4:
            chaos_desc = "mild variation with mostly stable structure"
        elif self.chaos_level <= 6:
            chaos_desc = "noticeable creative variation without losing overall coherence"
        elif self.chaos_level <= 8:
            chaos_desc = "strongly varied, experimental compositions"
        else:
            chaos_desc = "maximum chaos: wild, highly unexpected compositions and mixtures"

        is_japanese = self.output_language == "ja"
        if is_japanese:
            language_label = "Japanese"
            language_sentence = (
                "Output language: Japanese. Return only Japanese text in each fragment; "
                "do not append English translations."
            )
        else:
            language_label = "English"
            language_sentence = (
                "Output language: English. Return only English text in each fragment; "
                "do not append Japanese translations."
            )

        system_prompt = _append_temperature_hint(
            "You generate diverse, high-quality prompt fragments for image generation models like Midjourney. "
            "Follow the requested attribute mix and avoid forbidden words while keeping outputs concise and visual. "
            + language_sentence,
            self.model,
            temperature,
        )
        user_prompt = (
            f"Generate {self.total_lines} distinct prompt fragments for image generation in {language_label}.\n"
            "Formatting rules:\n"
            "- Output exactly one fragment per line.\n"
            "- Do NOT prepend numbers, bullets, or labels.\n"
            "- Each fragment should be a single concise sentence, compatible with Midjourney-style prompts.\n"
            "- Avoid producing identical fragments.\n\n"
            "Chaos control:\n"
            f"- Chaos level: {self.chaos_level} ({chaos_desc}).\n"
            "- Lower levels (1-3) should keep structure and style relatively consistent across fragments.\n"
            "- Medium levels (4-6) may change composition and style moderately, but keep subjects readable and not absurd.\n"
            "- Higher levels (7-10) may aggressively remix subjects, environments and materials; allow unusual angles and combinations.\n"
            "- At level 5 or above, ensure fragments feel clearly distinct and non-repetitive.\n\n"
            "Attribute preferences (approximate distribution across the fragments):\n"
            f"{attr_block}\n\n"
            "Words or themes to avoid (if these substrings appear, treat it as a hard prohibition): "
            f"{excl_block}\n\n"
            "If no attributes are given, create a varied but coherent mix of subjects, environments, materials, and visual styles."
        )
        return system_prompt, user_prompt


class PromptGeneratorWindow(QtWidgets.QMainWindow):
    """PySide6 版のメインウィンドウ。UIとイベントを集約。"""

    _worker_success = QtCore.Signal(object, object, object, object)
    _worker_failure = QtCore.Signal(object, object, object, object)

    def __init__(self):
        super().__init__()
        self.setWindowTitle(WINDOW_TITLE)
        self.setMinimumSize(1100, 680)
        self.attribute_types: List[AttributeType] = []
        self.attribute_details: List[AttributeDetail] = []
        self.main_prompt: str = ""
        self.tail_free_texts: str = ""
        self.option_prompt: str = ""
        self.available_model_choices = list(AVAILABLE_LLM_MODELS)
        self._thread: Optional[QtCore.QThread] = None
        self._movie_llm_context: Optional[dict] = None
        self._chaos_mix_context: Optional[dict] = None
        self._llm_generate_context: Optional[dict] = None
        self._tail_presets_watcher: Optional[QtCore.QFileSystemWatcher] = None
        self._arrange_presets_watcher: Optional[QtCore.QFileSystemWatcher] = None
        self.font_scale_level = 0
        self._ui_font_family = self.font().family()
        self.button_font_scale: Optional[QtWidgets.QPushButton] = None
        
        # 末尾プリセット・アレンジプリセットのロード（設定ファイル反映後のパスを使用）
        load_tail_presets_from_yaml()
        load_arrange_presets_from_yaml()

        # UI構築
        self._build_ui()
        self._apply_font_scale()
        
        # データロード
        self.load_attribute_data()
        self.update_attribute_ui_choices()
        self._update_tail_free_text_choices(reset_selection=True)
        self._setup_tail_presets_watcher()
        self._setup_arrange_presets_watcher()
        
        # シグナル接続
        self._worker_success.connect(self._invoke_worker_success, QtCore.Qt.QueuedConnection)
        self._worker_failure.connect(self._invoke_worker_failure, QtCore.Qt.QueuedConnection)
        
        log_structured(
            logging.INFO,
            "window_initialized",
            {
                "font_family": self._ui_font_family,
                "font_scale_level": self.font_scale_level,
                "llm_model": LLM_MODEL,
                "db_path": DEFAULT_DB_PATH,
            },
        )

    def _ensure_model_choice_alignment(self) -> None:
        """設定値とコンボボックスの候補がズレた場合に警告し、UIを有効モデルへ合わせる。"""

        global LLM_MODEL
        if not self.available_model_choices:
            return

        if LLM_MODEL not in self.available_model_choices:
            fallback_model = self.available_model_choices[0]
            SETTINGS_LOAD_NOTES.append(
                f"UI候補に存在しないLLMモデル '{LLM_MODEL}' を検出したため '{fallback_model}' に切り替えました。"
            )
            log_structured(
                logging.WARNING,
                "llm_model_ui_mismatch",
                {"configured_model": LLM_MODEL, "fallback_model": fallback_model},
            )
            target_model = fallback_model
        else:
            target_model = LLM_MODEL

        index = self.combo_llm_model.findText(target_model)
        if index < 0:
            index = 0
        self.combo_llm_model.setCurrentIndex(index)
        LLM_MODEL = self.combo_llm_model.currentText()
        self.label_current_model.setText(f"選択中: {LLM_MODEL}")

    # =============================
    # UI 構築
    # =============================
    def _build_ui(self):
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)

        # モダンなスタイリング（初期適用は _apply_font_scale に任せるため、ここでは構造のみ）
        # _apply_font_scale() が後で呼ばれてスタイルシートを設定する
        
        main_layout = QtWidgets.QVBoxLayout(central)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)

        # 1. Header
        self._build_header(main_layout)

        # 2. Main Splitter (Left / Right)
        splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        main_layout.addWidget(splitter, 1)

        # Left Pane Container
        left_widget = QtWidgets.QWidget()
        left_layout = QtWidgets.QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 5, 0)
        left_layout.setSpacing(10)
        self._build_left_pane_content(left_layout)
        splitter.addWidget(left_widget)

        # Right Pane Container
        right_widget = QtWidgets.QWidget()
        right_layout = QtWidgets.QVBoxLayout(right_widget)
        right_layout.setContentsMargins(5, 0, 0, 0)
        right_layout.setSpacing(10)
        self._build_right_pane_content(right_layout)
        splitter.addWidget(right_widget)

        # Splitter Initial Ratio (Approx 4:6)
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 6)

        # Status Bar (Loading Indicator)
        self.status_bar = self.statusBar()
        self.loading_progress = QtWidgets.QProgressBar()
        self.loading_progress.setRange(0, 0)  # Indeterminate (Marquee)
        self.loading_progress.setTextVisible(False)
        self.loading_progress.setFixedWidth(200)
        self.loading_progress.setMaximumHeight(15)
        self.loading_progress.setVisible(False)
        self.status_bar.addPermanentWidget(self.loading_progress)

    def _set_loading_state(self, is_loading: bool, message: str = ""):
        """LLM処理中のローディング表示を制御する。"""
        if is_loading:
            self.loading_progress.setVisible(True)
            self.status_bar.showMessage(message)
        else:
            self.loading_progress.setVisible(False)
            self.status_bar.clearMessage()

    def _build_header(self, parent_layout):
        header_layout = QtWidgets.QHBoxLayout()
        parent_layout.addLayout(header_layout)

        # LLMモデル選択
        header_layout.addWidget(QtWidgets.QLabel("LLMモデル:"))
        self.combo_llm_model = QtWidgets.QComboBox()
        self.combo_llm_model.addItems(self.available_model_choices)
        header_layout.addWidget(self.combo_llm_model)
        self.label_current_model = QtWidgets.QLabel(f"選択中: {self.combo_llm_model.currentText()}")
        header_layout.addWidget(self.label_current_model)
        self.combo_llm_model.currentTextChanged.connect(self._on_model_change)
        self._ensure_model_choice_alignment()

        header_layout.addStretch(1)

        # フォント切替
        self.button_font_scale = QtWidgets.QPushButton("フォント: 標準")
        self.button_font_scale.setToolTip("UI全体のフォントサイズを段階的に切り替えます。")
        self.button_font_scale.clicked.connect(self.cycle_font_scale)
        header_layout.addWidget(self.button_font_scale)

    def _build_left_pane_content(self, layout):
        # --- 1. Basic Settings (Compact Grid) ---
        basic_group = QtWidgets.QGroupBox("基本設定")
        basic_grid = QtWidgets.QGridLayout(basic_group)
        
        basic_grid.addWidget(QtWidgets.QLabel("行数:"), 0, 0)
        self.spin_row_num = QtWidgets.QSpinBox()
        self.spin_row_num.setMinimum(1)
        self.spin_row_num.setMaximum(999)
        self.spin_row_num.setValue(DEFAULT_ROW_NUM)
        basic_grid.addWidget(self.spin_row_num, 0, 1)

        self.check_autofix = QtWidgets.QCheckBox("自動反映")
        basic_grid.addWidget(self.check_autofix, 0, 2)

        self.check_dedup = QtWidgets.QCheckBox("重複除外")
        self.check_dedup.setChecked(bool(DEDUPLICATE_PROMPTS))
        self.check_dedup.stateChanged.connect(self.auto_update)
        basic_grid.addWidget(self.check_dedup, 1, 0, 1, 2)

        basic_grid.addWidget(QtWidgets.QLabel("生成方法:"), 2, 0)
        mode_container = QtWidgets.QWidget()
        mode_layout = QtWidgets.QHBoxLayout(mode_container)
        mode_layout.setContentsMargins(0, 0, 0, 0)
        self.radio_mode_db = QtWidgets.QRadioButton("DB生成")
        self.radio_mode_llm = QtWidgets.QRadioButton("LLM生成")
        self.radio_mode_db.setChecked(True)
        mode_layout.addWidget(self.radio_mode_db)
        mode_layout.addWidget(self.radio_mode_llm)
        mode_layout.addStretch(1)
        basic_grid.addWidget(mode_container, 2, 1, 1, 2)

        if not LLM_ENABLED:
            self.radio_mode_llm.setEnabled(False)
            self.radio_mode_llm.setToolTip("LLM生成を利用するには desktop_gui_settings.yaml の LLM_ENABLED を true に設定してください。")

        # LLM生成時のみ有効になるカオス度スライダー（1〜10）
        basic_grid.addWidget(QtWidgets.QLabel("カオス度(LLM):"), 3, 0)
        self._llm_chaos_container = QtWidgets.QWidget()
        chaos_layout = QtWidgets.QHBoxLayout(self._llm_chaos_container)
        chaos_layout.setContentsMargins(0, 0, 0, 0)
        self.slider_llm_chaos = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.slider_llm_chaos.setRange(1, 10)
        self.slider_llm_chaos.setTickPosition(QtWidgets.QSlider.TicksBelow)
        self.slider_llm_chaos.setTickInterval(1)
        self.slider_llm_chaos.setValue(1)
        self.slider_llm_chaos.setToolTip("LLM生成時の創造性（カオス度）を1〜10で指定します。1は安定寄り、5で十分強い変化、10で最大限カオスなバリエーションを許容します。")
        self.label_llm_chaos_val = QtWidgets.QLabel("1 (安定)")
        self.slider_llm_chaos.valueChanged.connect(self._on_llm_chaos_change)
        chaos_layout.addWidget(self.slider_llm_chaos, 1)
        chaos_layout.addWidget(self.label_llm_chaos_val)
        self._llm_chaos_container.setVisible(False)
        basic_grid.addWidget(self._llm_chaos_container, 3, 1, 1, 2)

        # LLM生成時の出力言語選択（英語 / 日本語）
        basic_grid.addWidget(QtWidgets.QLabel("LLM生成言語:"), 4, 0)
        self.combo_llm_output_lang = QtWidgets.QComboBox()
        self.combo_llm_output_lang.addItem("英語", userData="en")
        self.combo_llm_output_lang.addItem("日本語", userData="ja")
        self.combo_llm_output_lang.setCurrentIndex(0)
        self.combo_llm_output_lang.setToolTip(
            "通常生成の LLMモードで生成されるフラグメント（1行ごとの短文）の言語を指定します。"
        )
        basic_grid.addWidget(self.combo_llm_output_lang, 4, 1, 1, 2)

        # モード切替時にカオス度バーの表示/非表示を更新
        self.radio_mode_db.toggled.connect(self._update_generate_mode_ui)
        self.radio_mode_llm.toggled.connect(self._update_generate_mode_ui)
        self._update_generate_mode_ui()

        layout.addWidget(basic_group)

        # --- 2. Attributes Selection (Main Scroll Area) ---
        attr_group = QtWidgets.QGroupBox("属性選択")
        attr_layout = QtWidgets.QVBoxLayout(attr_group)
        self.attribute_area = QtWidgets.QScrollArea()
        self.attribute_area.setWidgetResizable(True)
        self.attribute_container = QtWidgets.QWidget()
        self.attribute_layout = QtWidgets.QFormLayout(self.attribute_container)
        self.attribute_area.setWidget(self.attribute_container)
        attr_layout.addWidget(self.attribute_area)
        layout.addWidget(attr_group, 1)  # Stretch to fill available vertical space

        # --- 3. Options Tab (Bottom of Left Pane) ---
        tabs = QtWidgets.QTabWidget()
        layout.addWidget(tabs)

        # Tab 1: Style & Presets
        style_tab = QtWidgets.QWidget()
        style_layout = QtWidgets.QVBoxLayout(style_tab)
        style_layout.setContentsMargins(5, 5, 5, 5)

        # Tail Settings
        tail_form = QtWidgets.QFormLayout()
        self.combo_tail_media_type = QtWidgets.QComboBox()
        self.combo_tail_media_type.addItems(list(TAIL_PRESETS.keys()))
        self.combo_tail_media_type.currentTextChanged.connect(self._on_tail_media_type_change)
        tail_form.addRow("末尾プリセット用途:", self.combo_tail_media_type)

        tail_row = QtWidgets.QHBoxLayout()
        self.check_tail_free = QtWidgets.QCheckBox("末尾1:")
        self.combo_tail_free = QtWidgets.QComboBox()
        self.combo_tail_free.setEditable(True)
        self.combo_tail_free.setToolTip("末尾固定文を選択または編集できます。")
        tail_row.addWidget(self.check_tail_free)
        tail_row.addWidget(self.combo_tail_free, 1)
        tail_form.addRow(tail_row)

        # Tail JSON Flags (末尾2)
        tail2_group = QtWidgets.QGroupBox("末尾2 (JSONフラグ)")
        tail2_layout = QtWidgets.QVBoxLayout(tail2_group)

        # 末尾2を出力に反映するかどうかのマスターチェック
        self.check_tail_flags_enabled = QtWidgets.QCheckBox("末尾2を反映")
        self.check_tail_flags_enabled.setToolTip(
            "ONにすると content_flags JSON を末尾に付与します。すべてのフラグが OFF でも JSON 自体が付きます。"
        )
        self.check_tail_flags_enabled.stateChanged.connect(self.auto_update)
        tail2_layout.addWidget(self.check_tail_flags_enabled)

        # 音声・人物・字幕/テロップ系フラグ
        flags_row = QtWidgets.QHBoxLayout()
        self.check_tail_flag_narration = QtWidgets.QCheckBox("ナレーション")
        self.check_tail_flag_character = QtWidgets.QCheckBox("人物")
        self.check_tail_flag_character.setToolTip("映像内に人物（人間）が映っているかどうかを指定します。")
        self.check_tail_flag_bgm = QtWidgets.QCheckBox("BGM")
        self.check_tail_flag_ambient = QtWidgets.QCheckBox("環境音")
        self.check_tail_flag_ambient.setToolTip("風・水・街並み・機械音など、環境そのものから発生する音があるかどうかを指定します。")
        self.check_tail_flag_dialogue = QtWidgets.QCheckBox("人物のセリフ")
        self.check_tail_flag_dialogue_subtitle = QtWidgets.QCheckBox("セリフ字幕")
        self.check_tail_flag_dialogue_subtitle.setToolTip(
            "ONにすると、人物が話しているセリフそのものを文字として表示する字幕（セリフ字幕）があるシーンとして扱います。"
        )
        self.check_tail_flag_telop = QtWidgets.QCheckBox("テロップ/テキスト")
        self.check_tail_flag_telop.setToolTip(
            "ONにすると、ツッコミテロップや解説テキスト、効果音文字など、セリフとは異なる編集用テキストオーバーレイが画面上に存在するシーンとして扱います。"
        )
        for chk in (
            self.check_tail_flag_narration,
            self.check_tail_flag_character,
            self.check_tail_flag_bgm,
            self.check_tail_flag_ambient,
            self.check_tail_flag_dialogue,
            self.check_tail_flag_dialogue_subtitle,
            self.check_tail_flag_telop,
        ):
            chk.stateChanged.connect(self.auto_update)
            flags_row.addWidget(chk)
        tail2_layout.addLayout(flags_row)

        # 構成カット数 (Auto / 1-6)
        cuts_row = QtWidgets.QHBoxLayout()
        cuts_row.addWidget(QtWidgets.QLabel("構成カット数:"))
        self.combo_tail_cut_count = QtWidgets.QComboBox()
        self.combo_tail_cut_count.addItems(["(Auto)", "1", "2", "3", "4", "5", "6"])
        self.combo_tail_cut_count.setToolTip("動画全体を何カット程度で構成するかの目安です。(Auto) はモデル任せ。")
        self.combo_tail_cut_count.currentTextChanged.connect(self.auto_update)
        cuts_row.addWidget(self.combo_tail_cut_count)
        cuts_row.addStretch(1)
        tail2_layout.addLayout(cuts_row)

        # 動画中の主な言語 (Auto / 日本語 / 英語)
        lang_row = QtWidgets.QHBoxLayout()
        lang_row.addWidget(QtWidgets.QLabel("動画中の言語:"))
        self.combo_tail_language = QtWidgets.QComboBox()
        self.combo_tail_language.addItem("(Auto)", userData="")
        self.combo_tail_language.addItem("日本語", userData="ja")
        self.combo_tail_language.addItem("英語", userData="en")
        self.combo_tail_language.setToolTip(
            "動画内で想定される主な話し言葉の言語を指定します。(Auto) の場合は JSON に言語フィールドを含めません。"
        )
        self.combo_tail_language.currentIndexChanged.connect(self.auto_update)
        lang_row.addWidget(self.combo_tail_language)
        lang_row.addStretch(1)
        tail2_layout.addLayout(lang_row)

        tail_form.addRow(tail2_group)
        style_layout.addLayout(tail_form)

        # MJ Options Grid
        mj_group = QtWidgets.QGroupBox("オプション")
        mj_grid = QtWidgets.QGridLayout(mj_group)
        self.combo_tail_ar = self._add_option_cell(mj_grid, 0, "ar オプション:", AR_OPTIONS)
        self.combo_tail_s = self._add_option_cell(mj_grid, 1, "s オプション:", S_OPTIONS)
        self.combo_tail_chaos = self._add_option_cell(mj_grid, 2, "chaos オプション:", CHAOS_OPTIONS)
        self.combo_tail_q = self._add_option_cell(mj_grid, 3, "q オプション:", Q_OPTIONS)
        self.combo_tail_weird = self._add_option_cell(mj_grid, 4, "weird オプション:", WEIRD_OPTIONS)
        style_layout.addWidget(mj_group)
        
        style_layout.addStretch(1)
        tabs.addTab(style_tab, "スタイル・オプション")

        # Tab 2: Data Management
        data_tab = QtWidgets.QWidget()
        data_layout = QtWidgets.QVBoxLayout(data_tab)
        data_layout.setContentsMargins(5, 5, 5, 5)
        
        # Exclusion
        excl_group = QtWidgets.QGroupBox("除外設定")
        excl_layout = QtWidgets.QVBoxLayout(excl_group)
        excl_row = QtWidgets.QHBoxLayout()
        excl_row.addWidget(QtWidgets.QLabel(LABEL_EXCLUSION_WORDS))
        self.check_exclusion = QtWidgets.QCheckBox()
        excl_row.addWidget(self.check_exclusion)
        self.combo_exclusion = QtWidgets.QComboBox()
        self.combo_exclusion.setEditable(True)
        self.combo_exclusion.addItems(load_exclusion_words())
        excl_row.addWidget(self.combo_exclusion, 1)
        excl_layout.addLayout(excl_row)
        
        open_exclusion_btn = QtWidgets.QPushButton("除外語句CSVを開く")
        open_exclusion_btn.clicked.connect(self._open_exclusion_csv)
        excl_layout.addWidget(open_exclusion_btn)
        data_layout.addWidget(excl_group)

        # CSV DB
        db_group = QtWidgets.QGroupBox("DB管理")
        db_layout = QtWidgets.QHBoxLayout(db_group)
        csv_import_btn = QtWidgets.QPushButton("CSVをDBに投入")
        csv_import_btn.clicked.connect(self._open_csv_import_dialog)
        db_layout.addWidget(csv_import_btn)
        csv_export_btn = QtWidgets.QPushButton("(DB確認用CSV出力)")
        csv_export_btn.clicked.connect(self._export_csv)
        db_layout.addWidget(csv_export_btn)
        data_layout.addWidget(db_group)

        data_layout.addStretch(1)
        tabs.addTab(data_tab, "データ管理")

    def _add_option_cell(self, grid: QtWidgets.QGridLayout, row: int, label: str, values: Iterable[str]) -> QtWidgets.QComboBox:
        """グリッドレイアウトにオプション項目を追加するヘルパー"""
        grid.addWidget(QtWidgets.QLabel(label), row, 0)
        checkbox = QtWidgets.QCheckBox()
        grid.addWidget(checkbox, row, 1)
        combo = QtWidgets.QComboBox()
        combo.addItems([str(v) for v in values])
        combo.setEditable(True)
        combo.setProperty("toggle", checkbox)
        grid.addWidget(combo, row, 2)
        
        combo.currentTextChanged.connect(self.auto_update)
        checkbox.stateChanged.connect(self.auto_update)
        return combo

    def _build_right_pane_content(self, layout):
        # 1. Output Area (Top)
        self.text_output = QtWidgets.QTextEdit()
        self.text_output.setPlaceholderText("ここに生成結果が表示されます")
        layout.addWidget(self.text_output, 1)  # Stretch factor 1

        # 2. Primary Actions (Prominent)
        action_layout = QtWidgets.QHBoxLayout()
        
        generate_btn = QtWidgets.QPushButton("生成")
        generate_btn.setObjectName("BigAction")
        generate_btn.setMinimumHeight(45)
        generate_btn.clicked.connect(self.generate_text)
        action_layout.addWidget(generate_btn, 1)

        generate_copy_btn = QtWidgets.QPushButton("生成とコピー（全文）")
        generate_copy_btn.setObjectName("BigAction")
        generate_copy_btn.setMinimumHeight(45)
        generate_copy_btn.clicked.connect(self.generate_and_copy)
        action_layout.addWidget(generate_copy_btn, 1)
        
        layout.addLayout(action_layout)

        # 3. Secondary Actions
        sub_action_layout = QtWidgets.QHBoxLayout()
        
        copy_btn = QtWidgets.QPushButton("クリップボードにコピー(全文)")
        copy_btn.clicked.connect(self.copy_all_to_clipboard)
        sub_action_layout.addWidget(copy_btn)

        update_tail_btn = QtWidgets.QPushButton("末尾固定部のみ更新")
        update_tail_btn.clicked.connect(self.update_tail_free_texts)
        sub_action_layout.addWidget(update_tail_btn)

        update_option_btn = QtWidgets.QPushButton("オプションのみ更新")
        update_option_btn.clicked.connect(self.update_option)
        sub_action_layout.addWidget(update_option_btn)

        layout.addLayout(sub_action_layout)

        # 4. Advanced Tools (Tabs)
        tools_tabs = QtWidgets.QTabWidget()
        # 高さを現在の2倍程度（320px）かつ可変（Maximum制限なし）に変更
        tools_tabs.setMinimumHeight(320)
        layout.addWidget(tools_tabs)

        # Movie Tool Tab
        movie_tab = QtWidgets.QWidget()
        movie_layout = QtWidgets.QVBoxLayout(movie_tab)
        
        simple_row = QtWidgets.QHBoxLayout()
        simple_row.addWidget(QtWidgets.QLabel("簡易整形(LLMなし):"))
        format_movie_btn = QtWidgets.QPushButton("JSONデータ化")
        format_movie_btn.clicked.connect(self.handle_format_for_movie_json)
        simple_row.addWidget(format_movie_btn)
        movie_layout.addLayout(simple_row)

        llm_row = QtWidgets.QHBoxLayout()
        llm_row.addWidget(QtWidgets.QLabel("LLM改良:"))
        
        self.check_use_video_style = QtWidgets.QCheckBox("スタイル反映")
        self.check_use_video_style.setToolTip("ONにすると、末尾の video_style 定義(カメラ・照明・雰囲気など)をLLMへ伝え、それに沿った描写になるよう補正します。")
        # デフォルトはOFFにしておく（ユーザーが意図的に選べるように）
        llm_row.addWidget(self.check_use_video_style)

        llm_row.addWidget(QtWidgets.QLabel("出力言語:"))
        self.combo_movie_output_lang = _create_language_combo()
        self.combo_movie_output_lang.setToolTip(
            "動画用LLM整形（世界観/ストーリー/カオスミックス）で生成される文章の言語を指定します。"
        )
        llm_row.addWidget(self.combo_movie_output_lang)

        llm_row.addWidget(QtWidgets.QLabel("上限:"))
        self.combo_movie_length_limit = QtWidgets.QComboBox()
        self.combo_movie_length_limit.addItems(["(制限なし)", "250", "500", "750", "1000", "1250"])
        self.combo_movie_length_limit.setToolTip("出力される summary の文字数上限を指定します。\nLLMへの指示として扱われるため、厳密な保証ではありません。")
        llm_row.addWidget(self.combo_movie_length_limit)

        world_btn = QtWidgets.QPushButton("世界観整形")
        world_btn.clicked.connect(self.handle_movie_worldbuilding)
        llm_row.addWidget(world_btn)
        story_btn = QtWidgets.QPushButton("ストーリー構築")
        story_btn.clicked.connect(self.handle_movie_storyboard)
        llm_row.addWidget(story_btn)
        chaos_mix_btn = QtWidgets.QPushButton("カオスミックス")
        chaos_mix_btn.setToolTip("メインプロンプト断片を1つの場面に無理やり押し込み、全文をコピーします。")
        chaos_mix_btn.clicked.connect(self.handle_chaos_mix_and_copy)
        llm_row.addWidget(chaos_mix_btn)
        movie_layout.addLayout(llm_row)
        movie_layout.addStretch(1)
        
        tools_tabs.addTab(movie_tab, "動画用に整形(JSON)")

        # LLM Adjust Tab
        adjust_tab = QtWidgets.QWidget()
        adjust_layout = QtWidgets.QVBoxLayout(adjust_tab)
        adjust_layout.setContentsMargins(5, 5, 5, 5)

        # 1. 文字数設定 (簡易・アレンジ共通)
        length_group = QtWidgets.QHBoxLayout()
        length_group.addWidget(QtWidgets.QLabel("文字数目標:"))
        self.combo_length_adjust = QtWidgets.QComboBox()
        self.combo_length_adjust.addItems(["半分", "2割減", "同程度", "2割増", "倍"])
        self.combo_length_adjust.setCurrentText("同程度")
        length_group.addWidget(self.combo_length_adjust)

        length_group.addWidget(QtWidgets.QLabel("出力言語:"))
        self.combo_arrange_output_lang = _create_language_combo()
        self.combo_arrange_output_lang.setToolTip("LLMアレンジや文字数調整で生成されるプロンプトの言語を指定します。")
        length_group.addWidget(self.combo_arrange_output_lang)

        length_group.addWidget(QtWidgets.QLabel("上限:"))
        self.combo_length_limit_arrange = QtWidgets.QComboBox()
        self.combo_length_limit_arrange.addItems(["(制限なし)", "250", "500", "750", "1000", "1250"])
        length_group.addWidget(self.combo_length_limit_arrange)
        
        simple_adjust_btn = QtWidgets.QPushButton("文字数のみ調整")
        simple_adjust_btn.setToolTip("スタイル変更を行わず、現在のプロンプトの長さを調整します。")
        simple_adjust_btn.clicked.connect(self.handle_length_adjust_and_copy)
        length_group.addWidget(simple_adjust_btn)
        adjust_layout.addLayout(length_group)

        # 2. アレンジ設定
        arrange_form = QtWidgets.QFormLayout()
        
        self.combo_arrange_preset = QtWidgets.QComboBox()
        self._update_arrange_preset_choices()
        self.combo_arrange_preset.currentTextChanged.connect(self._on_arrange_preset_change)
        arrange_form.addRow("プリセット:", self.combo_arrange_preset)
        
        strength_row = QtWidgets.QHBoxLayout()
        self.slider_strength = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.slider_strength.setRange(0, 3)
        self.slider_strength.setValue(2)
        self.slider_strength.setTickPosition(QtWidgets.QSlider.TicksBelow)
        self.slider_strength.setTickInterval(1)
        self.slider_strength.setFixedWidth(150)
        self.label_strength_val = QtWidgets.QLabel("2 (標準)")
        self.slider_strength.valueChanged.connect(self._on_strength_change)
        strength_row.addWidget(self.slider_strength)
        strength_row.addWidget(self.label_strength_val)
        strength_row.addStretch(1)
        arrange_form.addRow("強度:", strength_row)
        
        self.entry_arrange_guidance = QtWidgets.QLineEdit()
        self.entry_arrange_guidance.setPlaceholderText("追加ガイダンス (任意)")
        arrange_form.addRow("ガイダンス:", self.entry_arrange_guidance)
        
        adjust_layout.addLayout(arrange_form)
        
        arrange_btn = QtWidgets.QPushButton("アレンジしてコピー")
        arrange_btn.setToolTip("選択したプリセットと強度でプロンプトを再構築し、結果をコピーします。")
        arrange_btn.clicked.connect(self.handle_arrange_llm_and_copy)
        adjust_layout.addWidget(arrange_btn)
        
        adjust_layout.addStretch(1)

        tools_tabs.addTab(adjust_tab, "LLM アレンジ")

    def _get_db_path_or_warn(self) -> Optional[Path]:
        """DBパスの存在をチェックし、欠損時はセットアップ手順を案内する。"""

        db_path = Path(DEFAULT_DB_PATH)
        log_structured(logging.INFO, "db_path_check", {"db_path": str(db_path)})
        if db_path.exists():
            return db_path
        self._show_db_missing_dialog(db_path)
        return None

    def _connect_with_foreign_keys(self, db_path: Path) -> sqlite3.Connection:
        """外部キー制約を確実に有効化した SQLite 接続を返す。"""

        log_structured(logging.INFO, "sqlite_connect_attempt", {"db_path": str(db_path)})
        conn = sqlite3.connect(db_path)
        # 参照整合性を SQLite 側で強制し、欠損 ID の混入を初期段階で防ぐ。
        conn.execute("PRAGMA foreign_keys = ON;")
        log_structured(logging.INFO, "sqlite_connect_ready", {"db_path": str(db_path)})
        return conn

    def _build_db_missing_message(self, db_path: Path) -> str:
        """初回セットアップを明示した案内文を生成する。"""

        return (
            "データベースファイルが見つかりませんでした。\n"
            f"想定パス: {db_path}\n\n"
            "セットアップ例:\n"
            "1) `python export_prompts_to_csv.py` を実行して初期DBを生成する\n"
            "2) アプリ内の『CSVをDBに投入』からCSVを登録する\n"
            "3) ファイルを配置後、アプリを再起動する"
        )

    def _show_db_missing_dialog(self, db_path: Path) -> None:
        """DB欠損時のダイアログ表示をまとめ、利用者に具体的な復旧手順を提示する。"""

        log_structured(logging.ERROR, "db_missing", {"db_path": str(db_path)})
        QtWidgets.QMessageBox.critical(self, "DB未検出", self._build_db_missing_message(db_path))

    # =============================
    # データロード
    # =============================
    def load_attribute_data(self):
        self.attribute_types.clear()
        self.attribute_details.clear()
        db_path = self._get_db_path_or_warn()
        if not db_path:
            log_structured(
                logging.WARNING,
                "db_attribute_load_skipped",
                {"reason": "db_path_missing"},
            )
            return

        try:
            with closing(self._connect_with_foreign_keys(db_path)) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT id, attribute_name, description FROM attribute_types")
                for row in cursor.fetchall():
                    self.attribute_types.append(AttributeType(*row))
                cursor.execute(
                    """
                    SELECT ad.id, ad.attribute_type_id, ad.description, ad.value, COUNT(DISTINCT pad.prompt_id) as content_count
                    FROM attribute_details ad
                    LEFT JOIN prompt_attribute_details pad ON ad.id = pad.attribute_detail_id
                    GROUP BY ad.id
                    """
                )
                for row in cursor.fetchall():
                    self.attribute_details.append(AttributeDetail(*row))
        except sqlite3.Error as exc:
            log_structured(
                logging.ERROR,
                "db_connection_failed",
                {"db_path": str(db_path), "error": str(exc), "caller": "load_attribute_data"},
            )
            QtWidgets.QMessageBox.critical(self, "DB接続エラー", f"データベースに接続できませんでした。\n{exc}")
            return
        log_structured(
            logging.INFO,
            "db_attribute_load_success",
            {
                "attribute_type_count": len(self.attribute_types),
                "attribute_detail_count": len(self.attribute_details),
            },
        )

    def update_attribute_ui_choices(self):
        # 既存フォームをクリア
        while self.attribute_layout.count():
            item = self.attribute_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        self.attribute_combo_map = {}
        self.attribute_count_map = {}
        for attr in self.attribute_types:
            detail_combo = QtWidgets.QComboBox()
            detail_combo.addItem("-", userData=None)
            for detail in self.attribute_details:
                if detail.attribute_type_id != attr.id or detail.content_count <= 0:
                    continue
                # 同一説明文があっても attribute_detail.id で一意に識別できるよう、ID を userData に格納する。
                display_text = f"{detail.description} ({detail.content_count})"
                detail_combo.addItem(display_text, userData=detail.id)
            detail_combo.setCurrentIndex(0)
            detail_combo.currentTextChanged.connect(self.auto_update)

            count_combo = QtWidgets.QComboBox()
            count_combo.addItems(["-"] + [str(i) for i in range(11)])
            count_combo.setCurrentText("0")
            count_combo.currentTextChanged.connect(self.auto_update)

            line_widget = QtWidgets.QWidget()
            line_layout = QtWidgets.QHBoxLayout(line_widget)
            line_layout.setContentsMargins(0, 0, 0, 0)
            line_layout.addWidget(detail_combo, 8)
            line_layout.addWidget(count_combo, 2)
            self.attribute_layout.addRow(QtWidgets.QLabel(attr.description), line_widget)

            self.attribute_combo_map[attr.id] = detail_combo
            self.attribute_count_map[attr.id] = count_combo

    # =============================
    # UI イベント
    # =============================
    def _on_model_change(self, value: str):
        self.label_current_model.setText(f"選択中: {value}")
        print(f"[LLM] 現在のモデル: {value} (changed via UI)")

    def _on_tail_media_type_change(self, value: str):
        self._update_tail_free_text_choices(reset_selection=True)
        self.auto_update()

    def _update_tail_free_text_choices(self, reset_selection: bool):
        """メディア種別に応じた末尾プリセット候補をコンボボックスへ反映する。

        UI には日本語 description を表示し、実際のプロンプト文字列は userData に保持する。
        """

        media_type = self.combo_tail_media_type.currentText() or DEFAULT_TAIL_MEDIA_TYPE
        presets = TAIL_PRESETS.get(media_type, TAIL_PRESETS.get(DEFAULT_TAIL_MEDIA_TYPE, []))

        # 以前の選択肢をプロンプト文字列として記憶し、可能であれば再選択する。
        previous_prompt = self._resolve_tail_free_prompt()

        self.combo_tail_free.blockSignals(True)
        self.combo_tail_free.clear()
        for preset in presets:
            description = str(preset.get("description_ja", ""))
            prompt = str(preset.get("prompt", ""))
            self.combo_tail_free.addItem(description, userData=prompt)

        target_index = 0
        if not reset_selection and previous_prompt:
            for i in range(self.combo_tail_free.count()):
                data = self.combo_tail_free.itemData(i)
                if isinstance(data, str) and data == previous_prompt:
                    target_index = i
                    break
        self.combo_tail_free.setCurrentIndex(target_index)
        self.combo_tail_free.blockSignals(False)

    def auto_update(self):
        if self.check_autofix.isChecked() and self.main_prompt:
            # 自動反映時は、現在の出力欄テキストを基準に main_prompt 等を同期してから末尾を再構成する。
            self.update_option(sync_from_text=True)

    def _open_csv_import_dialog(self):
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("CSV Import")
        layout = QtWidgets.QVBoxLayout(dialog)
        layout.addWidget(QtWidgets.QLabel("CSV データを貼り付けてください"))
        text_edit = QtWidgets.QTextEdit()
        layout.addWidget(text_edit)
        button_row = QtWidgets.QHBoxLayout()
        layout.addLayout(button_row)

        sample_button = QtWidgets.QPushButton("サンプル行を貼り付け")
        sample_button.setToolTip("attribute_details テーブルから拾った ID を用いて、投入例となるCSV行を自動生成します。")
        button_row.addWidget(sample_button)

        button = QtWidgets.QPushButton("投入")
        button_row.addWidget(button)

        def handle_import():
            content = text_edit.toPlainText().strip()
            if not content:
                QtWidgets.QMessageBox.critical(self, "エラー", "CSVデータを入力してください。")
                return
            try:
                inserted, failed_rows, export_path = self._process_csv(content)
                if failed_rows:
                    failure_lines = "\n".join(
                        f"{row_number}: {reason} | {raw}" for row_number, raw, reason in failed_rows
                    )
                    detail_message = (
                        f"有効行: {inserted} 件、失敗: {len(failed_rows)} 件\n"
                        f"詳細:\n{failure_lines}"
                    )
                    if export_path:
                        detail_message += f"\n失敗行を書き出しました: {export_path}"
                    QtWidgets.QMessageBox.warning(
                        self,
                        "一部パースに失敗しました",
                        detail_message,
                    )
                else:
                    QtWidgets.QMessageBox.information(
                        self, "成功", f"CSVデータを処理しました（{inserted} 件）。"
                    )
                self.load_attribute_data()
                self.update_attribute_ui_choices()
                dialog.accept()
            except Exception:
                QtWidgets.QMessageBox.critical(self, "エラー", f"CSVの処理中にエラーが発生しました: {get_exception_trace()}")

        button.clicked.connect(handle_import)
        sample_button.clicked.connect(lambda: self._populate_sample_csv_rows(text_edit))
        dialog.exec()

    def _populate_sample_csv_rows(self, text_edit: QtWidgets.QTextEdit) -> None:
        """attribute_details から取得した ID を使って、投入用のサンプル行を挿入する。"""

        db_path = self._get_db_path_or_warn()
        if not db_path:
            return

        try:
            with closing(self._connect_with_foreign_keys(db_path)) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT id, description FROM attribute_details ORDER BY id LIMIT 5"
                )
                samples = cursor.fetchall()
        except sqlite3.Error as exc:
            log_structured(
                logging.ERROR,
                "sample_csv_fetch_failed",
                {"db_path": str(db_path), "error": str(exc)},
            )
            QtWidgets.QMessageBox.warning(
                self, "サンプル取得失敗", f"attribute_details の読み込みに失敗しました。\n{exc}"
            )
            return

        if not samples:
            QtWidgets.QMessageBox.warning(
                self,
                "サンプル取得失敗",
                "attribute_details が空です。CSVを投入してから再試行してください。",
            )
            return

        attribute_ids = [str(row[0]) for row in samples]
        attribute_labels = [row[1].replace("\"", "'") if row[1] else "attribute" for row in samples]
        sample_lines = [
            f'"{attribute_labels[0]} / vivid detail","{attribute_ids[0]}"'
        ]
        if len(attribute_ids) >= 2:
            sample_lines.append(
                f'"Layered mix: {attribute_labels[0]} + {attribute_labels[1]}","{attribute_ids[0]},{attribute_ids[1]}"'
            )
        if len(attribute_ids) >= 3:
            sample_lines.append(
                f'"Cinematic trio featuring {attribute_labels[0]} / {attribute_labels[1]} / {attribute_labels[2]}","{attribute_ids[0]},{attribute_ids[1]},{attribute_ids[2]}"'
            )

        text_edit.setPlainText("\n".join(sample_lines))
        log_structured(
            logging.INFO,
            "sample_csv_inserted",
            {"attribute_ids": attribute_ids[:3], "caller": "_open_csv_import_dialog"},
        )
        QtWidgets.QMessageBox.information(
            self,
            "サンプルを挿入しました",
            "attribute_details のIDを使ったサンプル行を入力欄に貼り付けました。必要に応じて編集してから投入してください。",
        )

    def _process_csv(self, csv_content: str) -> Tuple[int, List[Tuple[int, str, str]], Optional[Path]]:
        """CSV文字列をパースし、DBへ投入する。失敗行はユーザーに見せるため返却・エクスポートする。"""

        db_path = self._get_db_path_or_warn()
        if not db_path:
            return 0, [], None

        failed_rows: List[Tuple[int, str, str]] = []
        cleaned_lines: List[Tuple[int, str]] = []

        for line_number, raw_line in enumerate(csv_content.splitlines(), start=1):
            if "citation[oaicite" in raw_line or "```" in raw_line:
                continue
            normalized = raw_line.replace('"""', '"').strip()
            if not normalized:
                continue
            cleaned_lines.append((line_number, normalized))

        if not cleaned_lines:
            raise ValueError("有効なCSV行が見つかりませんでした。空行や不要な記法を除去して再試行してください。")

        inserted = 0
        failed_export_path: Optional[Path] = None

        try:
            with closing(self._connect_with_foreign_keys(db_path)) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS prompts (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        content TEXT
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS prompt_attribute_details (
                        prompt_id INTEGER,
                        attribute_detail_id INTEGER,
                        FOREIGN KEY (prompt_id) REFERENCES prompts (id),
                        FOREIGN KEY (attribute_detail_id) REFERENCES attribute_details (id)
                    )
                    """
                )

                # with conn: により例外発生時は自動ロールバック。成功時のみコミットされる。
                with conn:
                    csv_rows = [row for _, row in cleaned_lines]
                    for (line_number, raw_line), row in zip(cleaned_lines, csv.reader(csv_rows)):
                        if len(row) != 2:
                            failed_rows.append((line_number, raw_line, "列数が2列ではありません"))
                            continue

                        content, id_column = row
                        content = content.strip()
                        id_tokens = [token.strip() for token in id_column.split(",") if token.strip()]

                        if not content:
                            failed_rows.append((line_number, raw_line, "content が空です"))
                            continue

                        if not id_tokens:
                            failed_rows.append((line_number, raw_line, "attribute_detail_id が空です"))
                            continue

                        try:
                            attribute_detail_ids = [int(token) for token in id_tokens]
                        except ValueError:
                            failed_rows.append((line_number, raw_line, "attribute_detail_id は数値で入力してください"))
                            continue

                        # attribute_detail_id がDBに存在するかを事前検証し、不整合行は即座に弾く。
                        missing_ids: List[int] = []
                        for attribute_detail_id in attribute_detail_ids:
                            cursor.execute(
                                "SELECT 1 FROM attribute_details WHERE id = ?", (attribute_detail_id,)
                            )
                            if cursor.fetchone() is None:
                                missing_ids.append(attribute_detail_id)

                        if missing_ids:
                            missing_summary = ", ".join(str(id_) for id_ in missing_ids)
                            log_structured(
                                logging.WARNING,
                                "csv_row_missing_attribute_detail",
                                {
                                    "line_number": line_number,
                                    "missing_attribute_detail_ids": missing_ids,
                                    "caller": "_process_csv",
                                },
                            )
                            failed_rows.append(
                                (
                                    line_number,
                                    raw_line,
                                    f"存在しない attribute_detail_id: {missing_summary}",
                                )
                            )
                            continue

                        cursor.execute('INSERT INTO prompts (content) VALUES (?)', (content,))
                        prompt_id = cursor.lastrowid
                        for attribute_detail_id in attribute_detail_ids:
                            cursor.execute(
                                'INSERT INTO prompt_attribute_details (prompt_id, attribute_detail_id) VALUES (?, ?)',
                                (prompt_id, attribute_detail_id),
                            )
                        inserted += 1

            if failed_rows:
                failed_export_path = self._export_failed_rows(failed_rows)
                log_structured(
                    logging.WARNING,
                    "csv_rows_failed_to_parse",
                    {
                        "db_path": str(db_path),
                        "failed_count": len(failed_rows),
                        "export_path": str(failed_export_path) if failed_export_path else None,
                    },
                )
        except sqlite3.Error as exc:
            log_structured(
                logging.ERROR,
                "db_connection_failed",
                {"db_path": str(db_path), "error": str(exc), "caller": "_process_csv"},
            )
            QtWidgets.QMessageBox.critical(self, "DB接続エラー", f"CSV投入用DB処理に失敗しました。\n{exc}")
            return 0, failed_rows, failed_export_path

        return inserted, failed_rows, failed_export_path

    def _export_failed_rows(self, failed_rows: List[Tuple[int, str, str]]) -> Path:
        """パース失敗した行をCSVで書き出し、再投入しやすくする。"""

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        export_path = SCRIPT_DIR / f"failed_csv_rows_{timestamp}.csv"
        with export_path.open("w", encoding="utf-8", newline="") as fp:
            writer = csv.writer(fp)
            writer.writerow(["line_number", "original", "error"])
            for line_number, raw_line, reason in failed_rows:
                writer.writerow([line_number, raw_line, reason])
        return export_path

    def _export_csv(self):
        MJImage().run()

    def _open_exclusion_csv(self):
        try:
            if os.name == "nt":
                subprocess.Popen(["notepad.exe", EXCLUSION_CSV])
            elif sys.platform == "darwin":
                subprocess.call(["open", "-a", "TextEdit", EXCLUSION_CSV])
            else:
                subprocess.call(["xdg-open", EXCLUSION_CSV])
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "エラー", f"CSVファイルを開けませんでした: {e}")

    def _setup_tail_presets_watcher(self) -> None:
        """末尾プリセット YAML の変更を監視し、プルダウン候補へ自動反映する。"""

        path = Path(TAIL_PRESETS_YAML)
        if not path.exists():
            return

        watcher = QtCore.QFileSystemWatcher(self)
        watcher.addPath(str(path))
        watcher.fileChanged.connect(self._on_tail_presets_file_changed)
        self._tail_presets_watcher = watcher

    @QtCore.Slot(str)
    def _on_tail_presets_file_changed(self, changed_path: str) -> None:
        """YAML 編集完了後にプリセットを再読込し、現在のコンボボックスに反映する。"""

        # 一部エディタは一時ファイルの差し替えを行うため、少し待ってから読みに行く。
        QtCore.QTimer.singleShot(300, self._reload_tail_presets_and_refresh_ui)

    def _reload_tail_presets_and_refresh_ui(self) -> None:
        """tail_presets.yaml を再読込し、media_type / tail_free 両コンボを最新状態に更新する。"""

        previous_media_type = self.combo_tail_media_type.currentText() or DEFAULT_TAIL_MEDIA_TYPE
        previous_prompt = self._resolve_tail_free_prompt()

        load_tail_presets_from_yaml()

        media_types = list(TAIL_PRESETS.keys())
        if not media_types:
            return

        self.combo_tail_media_type.blockSignals(True)
        self.combo_tail_media_type.clear()
        self.combo_tail_media_type.addItems(media_types)

        # 可能なら以前のメディア種別を維持し、なければデフォルトへフォールバック
        if previous_media_type in media_types:
            self.combo_tail_media_type.setCurrentText(previous_media_type)
        elif DEFAULT_TAIL_MEDIA_TYPE in media_types:
            self.combo_tail_media_type.setCurrentText(DEFAULT_TAIL_MEDIA_TYPE)
        else:
            self.combo_tail_media_type.setCurrentIndex(0)
        self.combo_tail_media_type.blockSignals(False)

        # メディア種別に応じて末尾プリセットを更新し、同じ prompt があれば再選択を試みる
        self._update_tail_free_text_choices(reset_selection=True)
        if previous_prompt:
            for i in range(self.combo_tail_free.count()):
                data = self.combo_tail_free.itemData(i)
                if isinstance(data, str) and data == previous_prompt:
                    self.combo_tail_free.setCurrentIndex(i)
                    break

    def _setup_arrange_presets_watcher(self) -> None:
        """アレンジプリセット YAML の変更を監視し、内部定義を自動更新する。"""

        path = Path(ARRANGE_PRESETS_YAML)
        if not path.exists():
            return

        watcher = QtCore.QFileSystemWatcher(self)
        watcher.addPath(str(path))
        watcher.fileChanged.connect(self._on_arrange_presets_file_changed)
        self._arrange_presets_watcher = watcher

    @QtCore.Slot(str)
    def _on_arrange_presets_file_changed(self, changed_path: str) -> None:
        """アレンジプリセット YAML 編集完了後に再読込を行う。"""

        QtCore.QTimer.singleShot(300, self._reload_arrange_presets)

    def _reload_arrange_presets(self) -> None:
        """arrange_presets.yaml を再読込し、ARRANGE_PRESETS を最新状態に更新する。"""

        load_arrange_presets_from_yaml()
        self._update_arrange_preset_choices()

    def _update_arrange_preset_choices(self):
        """アレンジプリセットの選択肢を更新する。"""
        current = self.combo_arrange_preset.currentText()
        self.combo_arrange_preset.blockSignals(True)
        self.combo_arrange_preset.clear()
        for p in ARRANGE_PRESETS:
            self.combo_arrange_preset.addItem(p["label"], userData=p)
        
        if current:
            index = self.combo_arrange_preset.findText(current)
            if index >= 0:
                self.combo_arrange_preset.setCurrentIndex(index)
        self.combo_arrange_preset.blockSignals(False)
        self._on_arrange_preset_change(self.combo_arrange_preset.currentText())

    def _on_arrange_preset_change(self, text):
        """プリセット変更時にガイダンスのプレースホルダーなどを更新する（必要に応じて実装）。"""
        pass

    def _on_strength_change(self, value):
        labels = {0: "0 (微細)", 1: "1 (弱)", 2: "2 (標準)", 3: "3 (強)"}
        self.label_strength_val.setText(labels.get(value, str(value)))

    def _on_llm_chaos_change(self, value: int):
        """LLM生成用カオス度スライダーの表示ラベルを更新する。"""
        if value <= 2:
            label = f"{value} (安定寄り)"
        elif value <= 4:
            label = f"{value} (控えめ)"
        elif value == 5:
            label = "5 (強め)"
        elif value <= 7:
            label = f"{value} (かなりカオス)"
        elif value <= 9:
            label = f"{value} (高カオス)"
        else:
            label = "10 (最大)"
        self.label_llm_chaos_val.setText(label)

    def _update_generate_mode_ui(self):
        """DB生成/LLM生成モード切替に応じてUIの表示を更新する。"""
        is_llm = self._is_llm_generation_mode()
        container = getattr(self, "_llm_chaos_container", None)
        if container is not None:
            container.setVisible(is_llm)
        lang_combo = getattr(self, "combo_llm_output_lang", None)
        if lang_combo is not None:
            lang_combo.setEnabled(is_llm)

    def handle_arrange_llm_and_copy(self):
        """アレンジ機能を実行し、結果をコピーする。"""
        src = self.text_output.toPlainText().strip()
        if not src:
            QtWidgets.QMessageBox.warning(self, "注意", "まずプロンプトを生成してください。")
            return

        preset_label = self.combo_arrange_preset.currentText()
        strength = self.slider_strength.value()
        guidance = self.entry_arrange_guidance.text().strip()
        length_adjust = self.combo_length_adjust.currentText()
        
        limit_text = self.combo_length_limit_arrange.currentText()
        length_limit = int(limit_text) if limit_text.isdigit() else 0
        output_language = _combo_language_code(getattr(self, "combo_arrange_output_lang", None))
        
        self._start_arrange_llm_worker(
            src,
            preset_label,
            strength,
            guidance,
            length_adjust,
            length_limit,
            output_language=output_language,
        )

    def handle_chaos_mix_and_copy(self):
        """断片的なメインプロンプトを一つのカオスシーンへ結合する。"""
        prepared = self._prepare_movie_prompt_parts()
        if not prepared:
            return
        main_text, options_tail, movie_tail = prepared
        if not main_text.strip():
            QtWidgets.QMessageBox.warning(self, "注意", "メインテキストが見つかりません。")
            return
        fragments = self._extract_sentence_details(main_text)
        video_style_arg = movie_tail if self.check_use_video_style.isChecked() else ""
        length_limit = self._get_selected_movie_length_limit()
        output_language = _combo_language_code(getattr(self, "combo_movie_output_lang", None))
        self._start_chaos_mix_llm_worker(
            main_text=main_text,
            fragments=fragments,
            movie_tail=movie_tail,
            options_tail=options_tail,
            video_style_context=video_style_arg,
            length_limit=length_limit,
            output_language=output_language,
        )

    def _start_arrange_llm_worker(
        self,
        text,
        preset_label,
        strength,
        guidance,
        length_adjust,
        length_limit,
        output_language: str,
    ):
        if not LLM_ENABLED:
            QtWidgets.QMessageBox.warning(self, "注意", "LLMが無効化されています。YAMLで LLM_ENABLED を true にしてください。")
            return
        
        worker = ArrangeLLMWorker(
            text=text,
            model=self.combo_llm_model.currentText(),
            preset_label=preset_label,
            strength=strength,
            guidance=guidance,
            length_adjust=length_adjust,
            length_limit=length_limit,
            output_language=output_language,
        )
        self._start_background_worker(worker, self._handle_arrange_llm_success, self._handle_arrange_llm_failure)

    def _handle_arrange_llm_success(self, thread: QtCore.QThread, worker: ArrangeLLMWorker, result: str):
        self._set_loading_state(False)
        thread.quit()
        thread.wait()
        worker.deleteLater()
        self._thread = None
        
        if not result:
            QtWidgets.QMessageBox.warning(self, "注意", "LLM から空のレスポンスが返されました。")
            return
        # オプション継承処理 + 末尾2(content_flags)の再付与
        merged = self._inherit_options_if_present(self.text_output.toPlainText(), result)
        base_without_flags, _ = self._detach_content_flags_tail(merged)
        flags_tail = self._make_tail_flags_json()
        clean = (base_without_flags or "").rstrip() + flags_tail

        # アレンジ後の全文を内部状態の最新版として反映し、後続操作でメイン部が巻き戻らないようにする。
        self._update_internal_prompt_from_text(clean)
        self.text_output.setPlainText(clean)
        QtGui.QGuiApplication.clipboard().setText(clean)
        QtWidgets.QMessageBox.information(self, "コピー完了", "アレンジ済みプロンプトをコピーしました。")

    def _handle_arrange_llm_failure(self, thread: QtCore.QThread, worker: ArrangeLLMWorker, error: str):
        self._set_loading_state(False)
        thread.quit()
        thread.wait()
        worker.deleteLater()
        self._thread = None
        QtWidgets.QMessageBox.critical(self, "エラー", f"アレンジ処理でエラーが発生しました:\n{error}")

    def _start_chaos_mix_llm_worker(
        self,
        main_text: str,
        fragments: List[str],
        movie_tail: str,
        options_tail: str,
        video_style_context: str,
        length_limit: int,
        output_language: str,
    ):
        if not LLM_ENABLED:
            QtWidgets.QMessageBox.warning(self, "注意", "LLMが無効化されています。YAMLで LLM_ENABLED を true にしてください。")
            return
        worker = ChaosMixLLMWorker(
            text=main_text,
            fragments=fragments,
            model=self.combo_llm_model.currentText(),
            video_style=video_style_context,
            length_limit=length_limit,
            output_language=output_language,
        )
        context = {
            "movie_tail": movie_tail,
            "options_tail": options_tail,
        }
        if self._start_background_worker(worker, self._handle_chaos_mix_success, self._handle_chaos_mix_failure):
            self._chaos_mix_context = context

    def _handle_chaos_mix_success(self, thread: QtCore.QThread, worker: ChaosMixLLMWorker, result: str):
        self._set_loading_state(False)
        thread.quit()
        thread.wait()
        worker.deleteLater()
        self._thread = None
        context = self._chaos_mix_context or {}
        self._chaos_mix_context = None
        if not result:
            QtWidgets.QMessageBox.warning(self, "注意", "LLM から空のレスポンスが返されました。")
            return
        movie_tail = (context.get("movie_tail") or "").strip()
        options_tail = (context.get("options_tail") or "").strip()
        flags_tail = self._make_tail_flags_json()

        # カオスミックス結果も world_description JSON としてデータ化する
        details = self._extract_sentence_details(result)
        chaos_json = self._build_movie_json_payload(
            summary=result.strip(),
            details=details,
            scope="single_chaotic_scene",
            key="world_description",
        )
        combined = self._compose_movie_prompt(chaos_json, movie_tail, flags_tail, options_tail)

        self.text_output.setPlainText(combined)
        self._update_internal_prompt_from_text(combined)
        QtGui.QGuiApplication.clipboard().setText(combined)
        QtWidgets.QMessageBox.information(self, "コピー完了", "カオスミックス結果(JSON)をコピーしました。")

    def _handle_chaos_mix_failure(self, thread: QtCore.QThread, worker: ChaosMixLLMWorker, error: str):
        self._set_loading_state(False)
        thread.quit()
        thread.wait()
        worker.deleteLater()
        self._thread = None
        self._chaos_mix_context = None
        QtWidgets.QMessageBox.critical(self, "エラー", f"カオスミックス処理でエラーが発生しました:\n{error}")


    # =============================
    # プロンプト生成ロジック
    # =============================
    def _make_option_prompt(self) -> str:
        def segment(combo: QtWidgets.QComboBox, flag: QtWidgets.QCheckBox, key: str) -> str:
            return f" --{key} {combo.currentText()}" if flag.isChecked() and combo.currentText().strip() else ""

        tail_ar = segment(self.combo_tail_ar, self.combo_tail_ar.property("toggle"), "ar")
        tail_s = segment(self.combo_tail_s, self.combo_tail_s.property("toggle"), "s")
        tail_chaos = segment(self.combo_tail_chaos, self.combo_tail_chaos.property("toggle"), "chaos")
        tail_q = segment(self.combo_tail_q, self.combo_tail_q.property("toggle"), "q")
        tail_weird = segment(self.combo_tail_weird, self.combo_tail_weird.property("toggle"), "weird")
        return f"{tail_ar}{tail_s}{tail_chaos}{tail_q}{tail_weird}"

    def _make_tail_text(self) -> str:
        if not self.check_tail_free.isChecked():
            return ""

        prompt = self._resolve_tail_free_prompt()
        if prompt:
            return " " + prompt
        return ""

    def _make_tail_flags_json(self) -> str:
        """末尾2(JSONフラグ)の現在値からJSON文字列を生成する。

        出力例:
        {
            "content_flags": {
                "narration": true,
                "person_present": false,
                "bgm": true,
                "ambient_sound": true,
                "dialogue": false,
                "on_screen_spoken_dialogue_subtitles": "On-screen subtitles display the spoken dialogue in this video.",
                "on_screen_non_dialogue_text_overlays": "There are on-screen non-dialogue text overlays such as commentary captions, labels, or sound-effect text rendered as part of the image.",
                "planned_cuts": 3,
                "spoken_language": "ja"
            }
        }
        
        narration / bgm / ambient_sound / dialogue は音声要素、
        person_present は「映像内に人物が映っているかどうか」を表す視覚要素フラグです。
        on_screen_spoken_dialogue_subtitles は「人物が話しているセリフそのものの字幕（セリフ字幕）が画面に表示されている」ことを、英語の説明文として明示します。
        on_screen_non_dialogue_text_overlays は「ツッコミテロップや解説テキスト、効果音文字など、セリフとは異なる編集用テキストオーバーレイが存在する」ことを、英語の説明文として明示します。
        planned_cuts は「作品全体をおおよそ何カットで構成するか」の目安（1〜6）を表します。
        spoken_language は「動画内で想定される主な話し言葉の言語」を表し、"ja" または "en" を取ります。
        (Auto) 選択時や未指定時は planned_cuts / spoken_language フィールド自体を省略します。
        """

        # マスターチェックがOFFなら、フラグの値に関わらず JSON は付与しない
        if not getattr(self, "check_tail_flags_enabled", None) or not self.check_tail_flags_enabled.isChecked():
            return ""

        flags = {
            "narration": bool(self.check_tail_flag_narration.isChecked()),
            # 「人物」は「映像内に人物が映っているかどうか」の真偽値を表す
            "person_present": bool(self.check_tail_flag_character.isChecked()),
            "bgm": bool(self.check_tail_flag_bgm.isChecked()),
            "ambient_sound": bool(self.check_tail_flag_ambient.isChecked()),
            "dialogue": bool(self.check_tail_flag_dialogue.isChecked()),
        }

        # セリフそのものに対応した字幕（セリフ字幕）が画面に出ている場合は、
        # true/false ではなく、動画モデルに直接伝わる英文の説明文を value として埋め込む。
        if self.check_tail_flag_dialogue_subtitle.isChecked():
            flags["on_screen_spoken_dialogue_subtitles"] = (
                "On-screen subtitles display the spoken dialogue in this video. "
                "Subtitles are clearly visible and synchronized with the spoken voice."
            )

        # セリフとは異なる編集用テロップ/テキスト（ツッコミ・解説・効果音文字など）が映っている場合も、
        # true/false ではなく、その存在を明示する英文の説明文を value として埋め込む。
        if self.check_tail_flag_telop.isChecked():
            flags["on_screen_non_dialogue_text_overlays"] = (
                "There are on-screen non-dialogue text overlays such as commentary captions, "
                "labels, or sound-effect text rendered as part of the image."
            )
        # 構成カット数 (1〜6) を planned_cuts として追加 (Auto の場合は省略)
        cut_combo = getattr(self, "combo_tail_cut_count", None)
        if isinstance(cut_combo, QtWidgets.QComboBox):
            text = (cut_combo.currentText() or "").strip()
            if text and text != "(Auto)" and text.isdigit():
                try:
                    cuts = int(text)
                    if 1 <= cuts <= 6:
                        flags["planned_cuts"] = cuts
                except ValueError:
                    pass
        # 動画中の主な話し言葉の言語 ("ja" / "en") を spoken_language として追加 (Auto の場合は省略)
        lang_combo = getattr(self, "combo_tail_language", None)
        if isinstance(lang_combo, QtWidgets.QComboBox):
            lang_code = lang_combo.currentData()
            if isinstance(lang_code, str) and lang_code in ("ja", "en"):
                flags["spoken_language"] = lang_code
        try:
            json_text = json.dumps({"content_flags": flags}, ensure_ascii=False)
        except Exception:
            return ""
        return " " + json_text

    def _resolve_tail_free_prompt(self) -> str:
        """末尾プリセットの現在値を「出力用プロンプト文字列」として解決する。

        - YAML 由来のプリセット選択時: 日本語 description ではなく、対応する英語/JSON の prompt を返す
        - ユーザーがコンボボックスを手入力変更した場合: 入力文字列そのものを返す
        """

        text = self.combo_tail_free.currentText().strip()
        if not text:
            return ""

        index = self.combo_tail_free.currentIndex()
        if 0 <= index < self.combo_tail_free.count():
            preset_prompt = self.combo_tail_free.itemData(index)
            # itemText と UI 上のテキストが一致している場合のみ「プリセット選択」とみなし、
            # 実プロンプト文字列を優先して返す。
            if isinstance(preset_prompt, str) and preset_prompt and text == self.combo_tail_free.itemText(index):
                return preset_prompt

        # 上記条件を満たさない場合は、ユーザーの自由入力をそのまま利用する。
        return text

    def _normalize_sentences(self, texts: Iterable[str]) -> List[str]:
        """文末の句読点を軽く整形し、Midjourney向けの短文として扱いやすい形に揃える。"""
        processed: List[str] = []
        for raw in texts:
            if raw is None:
                continue
            text = str(raw).strip()
            if not text:
                continue
            if text.endswith((",", "、", ";", ":", "；", "：", "!", "?", "\n")):
                text = text[:-1] + "."
            elif not text.endswith("."):
                text += "."
            processed.append(text)
        return processed

    def _is_llm_generation_mode(self) -> bool:
        """現在の通常生成モードが LLM生成 かどうかを判定する。"""
        radio = getattr(self, "radio_mode_llm", None)
        return bool(radio and radio.isChecked())

    def generate_text(self):
        """通常生成ボタンのエントリポイント。DB生成/LLM生成をモードに応じて切り替える。"""
        if self._is_llm_generation_mode():
            self._generate_text_via_llm()
        else:
            self._generate_text_via_db()

    def _generate_text_via_db(self):
        db_path = self._get_db_path_or_warn()
        if not db_path:
            return

        try:
            with closing(self._connect_with_foreign_keys(db_path)) as conn:
                cursor = conn.cursor()
                total_lines = int(self.spin_row_num.value())
                exclusion_words = [w.strip() for w in self.combo_exclusion.currentText().split(',') if w.strip()]
                attribute_conditions: List[dict] = []
                selected_lines: List[Tuple[int, str]] = []
                selected_ids: Set[int] = set()
                dedup_removed = 0  # 重複排除で除外された件数を記録し、行数不足の診断に使う
                if self.check_exclusion.isChecked() and exclusion_words:
                    self._update_exclusion_words(exclusion_words)

                for attr in self.attribute_types:
                    detail_combo = self.attribute_combo_map[attr.id]
                    count_combo = self.attribute_count_map[attr.id]
                    selected_detail_id = detail_combo.currentData()
                    count = count_combo.currentText()
                    if selected_detail_id is None or count == "-":
                        continue

                    count_int = int(count)
                    if count_int <= 0:
                        continue

                    detail_obj = next((d for d in self.attribute_details if d.id == selected_detail_id), None)
                    if not detail_obj:
                        log_structured(
                            logging.WARNING,
                            "attribute_detail_missing_in_state",
                            {
                                "attribute_id": attr.id,
                                "selected_detail_id": selected_detail_id,
                                "caller": "generate_text_db",
                            },
                        )
                        continue

                    attr_condition = {
                        "attribute_id": attr.id,
                        "attribute_name": attr.attribute_name,
                        "detail": detail_obj.description,
                        "detail_id": selected_detail_id,
                        "requested_count": count_int,
                    }

                    base_query = (
                        "SELECT p.id, p.content FROM prompts p "
                        "JOIN prompt_attribute_details pad ON p.id = pad.prompt_id "
                        "WHERE pad.attribute_detail_id = ?"
                    )

                    if self.check_exclusion.isChecked() and exclusion_words:
                        exclusion_condition = " AND " + " AND ".join(
                            "p.content NOT LIKE ?" for _ in exclusion_words
                        )
                        query = f"{base_query}{exclusion_condition}"
                        params = [selected_detail_id] + [f"%{word}%" for word in exclusion_words]
                        cursor.execute(query, params)
                    else:
                        cursor.execute(base_query, (selected_detail_id,))

                    matching = cursor.fetchall()
                    attr_condition["matched_candidates"] = len(matching)
                    attribute_conditions.append(attr_condition)
                    sampled = random.sample(matching, min(count_int, len(matching)))
                    for record in sampled:
                        prompt_id = record[0]
                        if self.check_dedup.isChecked() and prompt_id in selected_ids:
                            dedup_removed += 1
                            continue
                        selected_lines.append(record)
                        selected_ids.add(prompt_id)

                remaining = total_lines - len(selected_lines)
                if remaining > 0:
                    if self.check_exclusion.isChecked() and exclusion_words:
                        exclusion_condition = " AND " + " AND ".join("content NOT LIKE ?" for _ in exclusion_words)
                        query = f"SELECT id, content FROM prompts WHERE 1=1 {exclusion_condition}"
                        cursor.execute(query, [f"%{w}%" for w in exclusion_words])
                    else:
                        cursor.execute("SELECT id, content FROM prompts")
                    all_prompts = cursor.fetchall()
                    if self.check_dedup.isChecked():
                        remaining_pool = [line for line in all_prompts if line[0] not in selected_ids]
                        dedup_removed += len(all_prompts) - len(remaining_pool)
                    else:
                        remaining_pool = all_prompts
                    sampled_remaining = random.sample(remaining_pool, min(len(remaining_pool), remaining))
                    selected_lines.extend(sampled_remaining)
                    if self.check_dedup.isChecked():
                        selected_ids.update(line[0] for line in sampled_remaining)

                if len(selected_lines) < total_lines:
                    log_structured(
                        logging.WARNING,
                        "prompt_generation_shortage",
                        {
                            "requested_total_lines": total_lines,
                            "selected_lines": len(selected_lines),
                            "deduplication_enabled": bool(self.check_dedup.isChecked()),
                            "deduplicated_rows": dedup_removed,
                            "exclusion_words": exclusion_words,
                            "attribute_conditions": attribute_conditions,
                        },
                    )

                if not selected_lines:
                    self.main_prompt = ""
                    self._show_no_result_warning(
                        attribute_conditions,
                        exclusion_words,
                        total_lines,
                        len(selected_lines),
                        0,
                        dedup_removed,
                    )
                    # 結果なしの場合も、内部状態を空にしたうえで末尾構成だけ再描画する
                    self.update_option(sync_from_text=False)
                    return

                random.shuffle(selected_lines)
                processed_lines = self._normalize_sentences((line[1] for line in selected_lines))

                if not processed_lines:
                    self.main_prompt = ""
                    self._show_no_result_warning(
                        attribute_conditions,
                        exclusion_words,
                        total_lines,
                        len(selected_lines),
                        len(processed_lines),
                        dedup_removed,
                    )
                    self.update_option(sync_from_text=False)
                    return

                self.main_prompt = " ".join(processed_lines)
                # DB生成で確定した main_prompt をそのまま採用し、末尾を再構成する
                self.update_option(sync_from_text=False)
        except sqlite3.Error as exc:
            log_structured(
                logging.ERROR,
                "db_connection_failed",
                {"db_path": str(db_path), "error": str(exc), "caller": "generate_text_db"},
            )
            QtWidgets.QMessageBox.critical(self, "DB接続エラー", f"データベースに接続できませんでした。\n{exc}")
        except Exception:
            QtWidgets.QMessageBox.critical(self, "エラー", f"エラーが発生しました: {get_exception_trace()}")

    def _generate_text_via_llm(self):
        """属性条件と行数に応じて、通常生成をLLMでまとめて実行する。

        - ユーザーが明示的に選んだ属性: そのまま attribute_conditions に反映
        - 「-」かつ数値のみ指定された属性: 対応するプルダウン候補からランダムに詳細を選定して数ぶん展開
        - 行数に対して合計requested_countが不足している場合: すべての属性プルダウン候補から不足分だけランダムに詳細を追加
        """
        if not LLM_ENABLED:
            QtWidgets.QMessageBox.warning(
                self,
                "注意",
                "LLMが無効化されています。YAMLで LLM_ENABLED を true にしてください。",
            )
            return

        total_lines = int(self.spin_row_num.value())
        exclusion_words = [w.strip() for w in self.combo_exclusion.currentText().split(",") if w.strip()]
        if self.check_exclusion.isChecked() and exclusion_words:
            self._update_exclusion_words(exclusion_words)

        attribute_conditions: List[dict] = []
        used_detail_ids: Set[int] = set()

        # 1) 明示選択された属性 / 「-」指定＋数値ありの属性を attribute_conditions に反映
        for attr in self.attribute_types:
            detail_combo = self.attribute_combo_map.get(attr.id)
            count_combo = self.attribute_count_map.get(attr.id)
            if not detail_combo or not count_combo:
                continue

            selected_detail_id = detail_combo.currentData()
            count_text = count_combo.currentText()
            if count_text == "-":
                continue

            try:
                count_int = int(count_text)
            except ValueError:
                continue
            if count_int <= 0:
                continue

            # ケース1: 特定の詳細が選ばれている場合（従来どおり）
            if selected_detail_id is not None:
                detail_obj = next((d for d in self.attribute_details if d.id == selected_detail_id), None)
                if not detail_obj:
                    continue
                attribute_conditions.append(
                    {
                        "attribute_name": attr.attribute_name,
                        "detail": detail_obj.description,
                        "requested_count": count_int,
                        "attribute_type_id": attr.id,
                        "detail_id": detail_obj.id,
                    }
                )
                used_detail_ids.add(detail_obj.id)
                continue

            # ケース2: 「-」で数値のみ指定された属性
            # → 対応するattribute_type_idの詳細候補から、指定数だけランダムに詳細を選定（重複は許容）
            candidates = [d for d in self.attribute_details if d.attribute_type_id == attr.id]
            if not candidates:
                continue
            for _ in range(count_int):
                chosen = random.choice(candidates)
                attribute_conditions.append(
                    {
                        "attribute_name": attr.attribute_name,
                        "detail": chosen.description,
                        "requested_count": 1,
                        "attribute_type_id": attr.id,
                        "detail_id": chosen.id,
                    }
                )
                used_detail_ids.add(chosen.id)

        # 2) 行数に対してrequested_countが不足している場合、全プルダウン候補からランダム補完
        total_requested = 0
        for cond in attribute_conditions:
            try:
                total_requested += int(cond.get("requested_count", 0) or 0)
            except (TypeError, ValueError):
                continue

        shortage = max(0, total_lines - total_requested)
        if shortage > 0 and self.attribute_details:
            # すべての属性詳細の中から「未使用」を優先して候補を作成し、足りなければ全件からも選ぶ
            by_type = {t.id: t for t in self.attribute_types}
            unused_details = [d for d in self.attribute_details if d.id not in used_detail_ids]
            base_pool = unused_details or list(self.attribute_details)
            for _ in range(shortage):
                chosen = random.choice(base_pool)
                attr_type = by_type.get(chosen.attribute_type_id)
                attr_name = attr_type.attribute_name if attr_type else ""
                attribute_conditions.append(
                    {
                        "attribute_name": attr_name,
                        "detail": chosen.description,
                        "requested_count": 1,
                        "attribute_type_id": chosen.attribute_type_id,
                        "detail_id": chosen.id,
                    }
                )

        chaos_slider = getattr(self, "slider_llm_chaos", None)
        if isinstance(chaos_slider, QtWidgets.QSlider):
            chaos_level = chaos_slider.value()
        else:
            chaos_level = 1

        output_language = "en"
        lang_combo = getattr(self, "combo_llm_output_lang", None)
        if isinstance(lang_combo, QtWidgets.QComboBox):
            data = lang_combo.currentData()
            if isinstance(data, str) and data in ("en", "ja"):
                output_language = data

        worker = GeneratePromptLLMWorker(
            model=self.combo_llm_model.currentText(),
            total_lines=total_lines,
            attribute_conditions=attribute_conditions,
            exclusion_words=exclusion_words if self.check_exclusion.isChecked() else [],
            chaos_level=chaos_level,
            output_language=output_language,
        )
        context = {
            "total_lines": total_lines,
            "deduplicate": bool(self.check_dedup.isChecked()),
            "exclusion_words": exclusion_words if self.check_exclusion.isChecked() else [],
            "attribute_conditions": attribute_conditions,
            "chaos_level": chaos_level,
            "output_language": output_language,
        }
        if self._start_background_worker(worker, self._handle_generate_llm_success, self._handle_generate_llm_failure):
            self._llm_generate_context = context

    def _handle_generate_llm_success(self, thread: QtCore.QThread, worker: GeneratePromptLLMWorker, result: str):
        self._set_loading_state(False)
        thread.quit()
        thread.wait()
        worker.deleteLater()
        self._thread = None
        context = self._llm_generate_context or {}
        self._llm_generate_context = None

        raw_output = (result or "").strip()
        if not raw_output:
            QtWidgets.QMessageBox.warning(self, "注意", "LLM から空のレスポンスが返されました。")
            return

        target_total = int(context.get("total_lines") or self.spin_row_num.value() or 1)
        dedup = bool(context.get("deduplicate"))
        exclusion_words: List[str] = context.get("exclusion_words") or []

        lines = [line.strip() for line in raw_output.splitlines() if line.strip()]
        cleaned_lines: List[str] = []
        for line in lines:
            m = re.match(r"^\s*(\d+[\.\):\-]|[-*])\s+(.*)$", line)
            if m:
                cleaned_lines.append(m.group(2).strip())
            else:
                cleaned_lines.append(line)

        if exclusion_words:
            cleaned_lines = [
                l for l in cleaned_lines
                if not any(word for word in exclusion_words if word and word in l)
            ]

        if dedup:
            seen: Set[str] = set()
            uniq: List[str] = []
            for l in cleaned_lines:
                key = l.lower()
                if key in seen:
                    continue
                seen.add(key)
                uniq.append(l)
            cleaned_lines = uniq

        if not cleaned_lines:
            if raw_output:
                cleaned_lines = [raw_output]
            else:
                QtWidgets.QMessageBox.warning(self, "注意", "LLM出力から有効な行を抽出できませんでした。")
                return

        if target_total > 0:
            cleaned_lines = cleaned_lines[:target_total]

        processed_lines = self._normalize_sentences(cleaned_lines)
        if not processed_lines:
            QtWidgets.QMessageBox.warning(self, "注意", "LLM出力の整形に失敗しました。再試行してください。")
            return

        self.main_prompt = " ".join(processed_lines)
        # LLM生成で確定した main_prompt をそのまま採用し、末尾を再構成する
        self.update_option(sync_from_text=False)
        chaos_level = int(context.get("chaos_level") or 1)
        attr_conditions = context.get("attribute_conditions") or []
        log_structured(
            logging.INFO,
            "llm_generation_success",
            {
                "requested_lines": target_total,
                "actual_fragments": len(processed_lines),
                "deduplicate": dedup,
                "exclusion_words": exclusion_words,
                "chaos_level": chaos_level,
                "output_language": context.get("output_language", "en"),
                "attribute_condition_count": len(attr_conditions),
            },
        )

        # 生成完了ダイアログに、LLMに渡した準備データセットをJSON形式で表示する
        # 生成完了ダイアログに、LLMに渡した準備データセットをJSON形式で常時表示する
        try:
            summary_lines: List[str] = []
            for cond in attr_conditions:
                line_obj = {
                    "attribute_name": str(cond.get("attribute_name", "") or ""),
                    "detail": str(cond.get("detail", "") or ""),
                    "requested_count": cond.get("requested_count", 0) or 0,
                }
                summary_lines.append(json.dumps(line_obj, ensure_ascii=False))

            preview = (
                "\n".join(summary_lines)
                if summary_lines
                else "（属性条件なし: LLMには自由生成として依頼しました）"
            )

            dialog = QtWidgets.QDialog(self)
            dialog.setWindowTitle("LLM生成 完了")
            dialog.setModal(True)
            dialog.setSizeGripEnabled(True)
            # 元のメッセージボックスよりも縦横ともおおよそ3倍程度の初期サイズ
            dialog.resize(1200, 900)

            layout = QtWidgets.QVBoxLayout(dialog)

            info_label = QtWidgets.QLabel(
                f"LLM生成が完了しました。\n\n"
                f"行数指定: {target_total}\n"
                f"実際のフラグメント数: {len(processed_lines)}\n"
                f"カオス度(LLM): {chaos_level}\n"
                f"除外語句: {', '.join(exclusion_words) if exclusion_words else 'なし'}\n\n"
                "下部にLLMへの準備データセット（属性条件）をJSON形式で表示します。"
            )
            info_label.setWordWrap(True)
            layout.addWidget(info_label)

            text_edit = QtWidgets.QPlainTextEdit()
            text_edit.setReadOnly(True)
            text_edit.setPlainText(preview)
            layout.addWidget(text_edit, 1)

            button_box = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok)
            button_box.accepted.connect(dialog.accept)
            layout.addWidget(button_box)

            dialog.exec()
        except Exception:
            # ダイアログ表示の失敗は致命的ではないため、ログに残すのみとする
            log_structured(
                logging.WARNING,
                "llm_generation_summary_dialog_failed",
                {"error": get_exception_trace()},
            )

    def _handle_generate_llm_failure(self, thread: QtCore.QThread, worker: GeneratePromptLLMWorker, error: str):
        self._set_loading_state(False)
        thread.quit()
        thread.wait()
        worker.deleteLater()
        self._thread = None
        self._llm_generate_context = None
        QtWidgets.QMessageBox.critical(self, "エラー", f"LLM生成処理でエラーが発生しました:\n{error}")

    def _show_no_result_warning(
        self,
        attribute_conditions: List[dict],
        exclusion_words: List[str],
        total_lines: int,
        selected_count: int,
        processed_count: int,
        dedup_removed: int,
    ) -> None:
        """抽出結果が空だった場合に、条件ログと再入力のヒントを提示する。"""

        exclusion_summary = ", ".join(exclusion_words) if exclusion_words else "なし"
        attribute_summary = (
            "、".join(
                f"{c.get('attribute_name', 'attr')} / {c.get('detail', '-')} x{c.get('requested_count', 0)}"
                f" (候補 {c.get('matched_candidates', 0)} 件)" for c in attribute_conditions
            )
            if attribute_conditions
            else "なし"
        )

        log_structured(
            logging.WARNING,
            "prompt_generation_no_results",
            {
                "requested_total_lines": total_lines,
                "selected_lines": selected_count,
                "processed_lines": processed_count,
                "deduplication_enabled": bool(self.check_dedup.isChecked()),
                "deduplicated_rows": dedup_removed,
                "exclusion_words": exclusion_words,
                "attribute_conditions": attribute_conditions,
            },
        )

        message = (
            "指定条件に一致する行が見つかりませんでした。\n"
            "CSVをDBに投入するか、除外語句や行数の指定を緩和して再試行してください。\n\n"
            f"行数指定: {total_lines}\n"
            f"除外語句: {exclusion_summary}\n"
            f"属性条件: {attribute_summary}"
        )
        QtWidgets.QMessageBox.warning(self, "データ不足", message)

    def update_option(self, sync_from_text: bool = True):
        """
        末尾固定部とMJオプションを再構成して出力欄へ反映する。

        - sync_from_text=True: 現在の出力欄テキストから main_prompt / option を逆算してから再構成
        - sync_from_text=False: 直前に確定した main_prompt / option をそのまま使用（通常生成直後など）
        """
        if sync_from_text:
            # 手動編集や他機能の結果を基準に、内部状態を最新テキストへ合わせてから再構成する。
            self._update_internal_prompt_from_text(self.text_output.toPlainText())

        self.option_prompt = self._make_option_prompt()
        self.tail_free_texts = self._make_tail_text()
        tail_flags = self._make_tail_flags_json()
        result = f"{self.main_prompt}{self.tail_free_texts}{tail_flags}{self.option_prompt}"
        self.text_output.setPlainText(result)

    def update_tail_free_texts(self):
        """
        「末尾固定部のみ更新」ボタンの処理。

        現在の出力欄テキストをまず内部状態に取り込み、その上で末尾固定文と末尾2(JSONフラグ)だけを更新する。
        これにより、LLMアレンジや手動編集の後でもメイン部が巻き戻らない。
        """
        self._update_internal_prompt_from_text(self.text_output.toPlainText())
        self.tail_free_texts = self._make_tail_text()
        tail_flags = self._make_tail_flags_json()
        result = f"{self.main_prompt}{self.tail_free_texts}{tail_flags}{self.option_prompt}"
        self.text_output.setPlainText(result)

    def generate_and_copy(self):
        self.generate_text()
        self.copy_all_to_clipboard()

    def copy_all_to_clipboard(self):
        text = self.text_output.toPlainText().strip()
        if not text:
            QtWidgets.QMessageBox.warning(self, "注意", "まずプロンプトを生成してください。")
            return
        QtGui.QGuiApplication.clipboard().setText(text)
        QtWidgets.QMessageBox.information(self, "コピー完了", "クリップボードにコピーしました。")

    def handle_format_for_movie_json(self):
        try:
            prepared = self._prepare_movie_prompt_parts()
            if not prepared:
                return
            main_text, options_tail, movie_tail = prepared
            details = self._extract_sentence_details(main_text)
            world_json = self._build_movie_json_payload(
                summary=main_text.strip(),
                details=details,
                scope="single_continuous_world",
                key="world_description",
            )
            flags_tail = self._make_tail_flags_json()
            result = self._compose_movie_prompt(world_json, movie_tail, flags_tail, options_tail)
            self.text_output.setPlainText(result)
            self._update_internal_prompt_from_text(result)
            QtGui.QGuiApplication.clipboard().setText(result)
            QtWidgets.QMessageBox.information(self, "整形完了", "動画用のJSONプロンプトに整形し、全文をコピーしました。")
        except Exception:
            QtWidgets.QMessageBox.critical(self, "エラー", f"動画用プロンプト整形中にエラーが発生しました:\n{get_exception_trace()}")

    def handle_movie_worldbuilding(self):
        prepared = self._prepare_movie_prompt_parts()
        if not prepared:
            return
        main_text, options_tail, movie_tail = prepared
        details = self._extract_sentence_details(main_text)
        
        video_style_arg = movie_tail if self.check_use_video_style.isChecked() else ""
        length_limit = self._get_selected_movie_length_limit()
        output_language = _combo_language_code(getattr(self, "combo_movie_output_lang", None))
        self._start_movie_llm_transformation(
            "world",
            main_text,
            details,
            movie_tail,
            options_tail,
            video_style_arg,
            length_limit,
            output_language=output_language,
        )

    def handle_movie_storyboard(self):
        prepared = self._prepare_movie_prompt_parts()
        if not prepared:
            return
        main_text, options_tail, movie_tail = prepared
        details = self._extract_sentence_details(main_text)
        
        video_style_arg = movie_tail if self.check_use_video_style.isChecked() else ""
        length_limit = self._get_selected_movie_length_limit()
        output_language = _combo_language_code(getattr(self, "combo_movie_output_lang", None))
        self._start_movie_llm_transformation(
            "storyboard",
            main_text,
            details,
            movie_tail,
            options_tail,
            video_style_arg,
            length_limit,
            output_language=output_language,
        )

    def _get_selected_movie_length_limit(self) -> int:
        text = self.combo_movie_length_limit.currentText()
        if text.isdigit():
            return int(text)
        return 0

    def handle_length_adjust_and_copy(self):
        src = self.text_output.toPlainText().strip()
        if not src:
            QtWidgets.QMessageBox.warning(self, "注意", "まずプロンプトを生成してください。")
            return
        target = self.combo_length_adjust.currentText()
        
        limit_text = self.combo_length_limit_arrange.currentText()
        length_limit = int(limit_text) if limit_text.isdigit() else 0
        
        output_language = _combo_language_code(getattr(self, "combo_arrange_output_lang", None))
        self._start_llm_worker(src, target, length_limit, output_language)

    def _start_background_worker(self, worker: QtCore.QObject, success_handler, failure_handler):
        if self._thread and self._thread.isRunning():
            QtWidgets.QMessageBox.information(self, "実行中", "LLM 呼び出しが進行中です。完了までお待ちください。")
            return False
        
        self._set_loading_state(True, "LLM 処理中...")
        
        thread = QtCore.QThread()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(
            lambda result, _handler=success_handler, _thread=thread, _worker=worker: self._worker_success.emit(
                _handler, _thread, _worker, result
            )
        )
        worker.failed.connect(
            lambda err, _handler=failure_handler, _thread=thread, _worker=worker: self._worker_failure.emit(
                _handler, _thread, _worker, err
            )
        )
        thread.start()
        self._thread = thread
        return True

    def _start_llm_worker(self, text: str, length_hint: str, length_limit: int = 0, output_language: str = "en"):
        if not LLM_ENABLED:
            QtWidgets.QMessageBox.warning(self, "注意", "LLMが無効化されています。YAMLで LLM_ENABLED を true にしてください。")
            return
        worker = LLMWorker(
            text=text,
            model=self.combo_llm_model.currentText(),
            length_hint=length_hint,
            length_limit=length_limit,
            output_language=output_language,
        )
        self._start_background_worker(worker, self._handle_llm_success, self._handle_llm_failure)

    def _start_movie_llm_transformation(
        self,
        mode: str,
        main_text: str,
        details: List[str],
        movie_tail: str,
        options_tail: str,
        video_style_context: str = "",
        length_limit: int = 0,
        output_language: str = "en",
    ):
        if not LLM_ENABLED:
            QtWidgets.QMessageBox.warning(self, "注意", "LLMが無効化されています。YAMLで LLM_ENABLED を true にしてください。")
            return
        worker = MovieLLMWorker(
            text=main_text,
            model=self.combo_llm_model.currentText(),
            mode=mode,
            details=details,
            video_style=video_style_context,
            length_limit=length_limit,
            output_language=output_language,
        )
        context = {
            "mode": mode,
            "movie_tail": movie_tail,
            "options_tail": options_tail,
        }
        if self._start_background_worker(worker, self._handle_movie_llm_success, self._handle_movie_llm_failure):
            self._movie_llm_context = context

    def _handle_llm_success(self, thread: QtCore.QThread, worker: LLMWorker, result: str):
        self._set_loading_state(False)
        thread.quit()
        thread.wait()
        worker.deleteLater()
        self._thread = None
        if not result:
            QtWidgets.QMessageBox.warning(self, "注意", "LLM から空のレスポンスが返されました。")
            return
        merged = self._inherit_options_if_present(self.text_output.toPlainText(), result)
        base_without_flags, _ = self._detach_content_flags_tail(merged)
        flags_tail = self._make_tail_flags_json()
        clean = (base_without_flags or "").rstrip() + flags_tail
        # 文字数調整の結果も内部状態へ反映し、後続操作で旧テキストへ巻き戻らないようにする。
        self._update_internal_prompt_from_text(clean)
        self.text_output.setPlainText(clean)
        QtGui.QGuiApplication.clipboard().setText(clean)
        QtWidgets.QMessageBox.information(self, "コピー完了", "LLMで調整したプロンプトをコピーしました。")

    def _handle_movie_llm_success(self, thread: QtCore.QThread, worker: MovieLLMWorker, result: str):
        self._set_loading_state(False)
        thread.quit()
        thread.wait()
        worker.deleteLater()
        self._thread = None
        context = self._movie_llm_context or {}
        self._movie_llm_context = None
        if not result:
            QtWidgets.QMessageBox.warning(self, "注意", "LLM から空のレスポンスが返されました。")
            return
        mode = context.get("mode", "world")
        movie_tail = context.get("movie_tail", "")
        options_tail = context.get("options_tail", "")
        scope = "single_continuous_world" if mode == "world" else "single_shot_storyboard"
        json_key = "world_description" if mode == "world" else "storyboard"
        details = self._extract_sentence_details(result)
        world_json = self._build_movie_json_payload(result, details, scope=scope, key=json_key)
        flags_tail = self._make_tail_flags_json()
        combined = self._compose_movie_prompt(world_json, movie_tail, flags_tail, options_tail)
        self.text_output.setPlainText(combined)
        self._update_internal_prompt_from_text(combined)
        QtGui.QGuiApplication.clipboard().setText(combined)
        label = "世界観整形" if mode == "world" else "ストーリー構築"
        QtWidgets.QMessageBox.information(self, "コピー完了", f"{label}をLLMで実行し、全文をコピーしました。")

    def _handle_llm_failure(self, thread: QtCore.QThread, worker: LLMWorker, error: str):
        self._set_loading_state(False)
        thread.quit()
        thread.wait()
        worker.deleteLater()
        self._thread = None
        QtWidgets.QMessageBox.critical(self, "エラー", f"LLM 呼び出しでエラーが発生しました:\n{error}")

    def _handle_movie_llm_failure(self, thread: QtCore.QThread, worker: MovieLLMWorker, error: str):
        self._set_loading_state(False)
        thread.quit()
        thread.wait()
        worker.deleteLater()
        self._thread = None
        self._movie_llm_context = None
        QtWidgets.QMessageBox.critical(self, "エラー", f"動画用整形のLLM処理でエラーが発生しました:\n{error}")

    @QtCore.Slot(object, object, object, object)
    def _invoke_worker_success(self, handler, thread, worker, payload):
        handler(thread, worker, payload)

    @QtCore.Slot(object, object, object, object)
    def _invoke_worker_failure(self, handler, thread, worker, payload):
        handler(thread, worker, payload)

    def _update_exclusion_words(self, new_words: List[str]):
        new_words = sorted([w for w in new_words if w])
        new_phrase = ", ".join(new_words)
        current_words = load_exclusion_words()
        if new_phrase and new_phrase not in current_words:
            with open(EXCLUSION_CSV, "a", encoding="utf-8", newline="") as file:
                writer = csv.writer(file, quotechar='"', quoting=csv.QUOTE_ALL)
                writer.writerow([new_phrase])
            updated = load_exclusion_words()
            self.combo_exclusion.clear()
            self.combo_exclusion.addItems(updated)
            self.combo_exclusion.setCurrentText(new_phrase)

    # =============================
    # オプション整形系ヘルパー
    # =============================
    def _prepare_movie_prompt_parts(self) -> Optional[Tuple[str, str, str]]:
        """動画用整形で共通となる入力分解を行い、メインテキストと末尾要素を返す。"""
        src = self.text_output.toPlainText().strip()
        if not src:
            QtWidgets.QMessageBox.warning(self, "注意", "まずプロンプトを生成してください。")
            return None
        # 末尾2(JSONフラグ)はLLM用のメインテキストからは除外する
        core_without_flags, _ = self._detach_content_flags_tail(src)
        core_without_movie, movie_tail = self._detach_movie_tail_for_llm(core_without_flags)
        main_text, options_tail, _ = self._split_prompt_and_options(core_without_movie)
        if not main_text:
            QtWidgets.QMessageBox.warning(self, "注意", "メインテキストが見つかりません。")
            return None
        return main_text, options_tail, movie_tail

    def _extract_sentence_details(self, text: str) -> List[str]:
        """文末の句読点で区切り、世界観説明に使う細部の配列を作る。"""
        sentence_candidates = re.split(r"[。\.]\s*", text or "")
        details = [s.strip(" .　") for s in sentence_candidates if s.strip(" .　")]
        return details or [text.strip()]

    def _build_movie_json_payload(self, summary: str, details: List[str], scope: str, key: str) -> str:
        """world_description もしくは storyboard としてJSON文字列を生成する。"""
        payload = {
            key: {
                "scope": scope,
                "summary": (summary or "").strip()
            }
        }
        return json.dumps(payload, ensure_ascii=False)

    def _compose_movie_prompt(self, core_json: str, movie_tail: str, flags_tail: str, options_tail: str) -> str:
        """生成したJSONと末尾要素（動画スタイル・末尾2フラグ・MJオプション）を安全に連結する。"""
        parts = [core_json]
        if movie_tail:
            parts.append(movie_tail.strip())
        if flags_tail:
            parts.append(flags_tail.strip())
        if options_tail:
            parts.append(options_tail.strip())
        return " ".join(p for p in parts if p)

    def _detach_content_flags_tail(self, text: str) -> Tuple[str, str]:
        """
        テキスト末尾付近から content_flags を含む JSON ブロック({...})を抽出する。
        例: {"content_flags":{"narration":true,"person_present":false,"bgm":true,"dialogue":false}}
        """
        text = (text or "").strip()
        search_end = len(text) - 1

        while search_end >= 0:
            end_idx = text.rfind("}", 0, search_end + 1)
            if end_idx == -1:
                break

            depth = 0
            start_idx = -1
            for i in range(end_idx, -1, -1):
                char = text[i]
                if char == "}":
                    depth += 1
                elif char == "{":
                    depth -= 1
                    if depth == 0:
                        start_idx = i
                        break

            if start_idx != -1:
                candidate = text[start_idx : end_idx + 1]
                if '"content_flags"' in candidate or "'content_flags'" in candidate:
                    flags_tail = candidate
                    remaining = (text[:start_idx] + " " + text[end_idx + 1 :]).strip()
                    remaining = " ".join(remaining.split())
                    return remaining, flags_tail
                else:
                    search_end = start_idx - 1
            else:
                search_end = end_idx - 1

        return text, ""

    def _detach_movie_tail_for_llm(self, text: str) -> Tuple[str, str]:
        """
        テキスト内から video_style を含む JSON ブロック({...}) を抽出する。
        単純な split() では JSON 内のスペースで分割されてしまうため、括弧の対応関係を用いて抽出する。
        """
        text = (text or "").strip()
        search_end = len(text) - 1
        
        while search_end >= 0:
            # 後ろから '}' を探す
            end_idx = text.rfind("}", 0, search_end + 1)
            if end_idx == -1:
                break
            
            # 対応する '{' を探す
            depth = 0
            start_idx = -1
            for i in range(end_idx, -1, -1):
                char = text[i]
                if char == '}':
                    depth += 1
                elif char == '{':
                    depth -= 1
                    if depth == 0:
                        start_idx = i
                        break
            
            if start_idx != -1:
                candidate = text[start_idx : end_idx + 1]
                # video_style を含むかチェック (簡易的な文字列判定)
                if '"video_style"' in candidate or "'video_style'" in candidate:
                    movie_tail = candidate
                    # 抽出して残りを結合
                    remaining = (text[:start_idx] + " " + text[end_idx + 1:]).strip()
                    # 連続空白の正規化
                    remaining = " ".join(remaining.split())
                    return remaining, movie_tail
                else:
                    # video_style ではないブロックだった場合、これより前から再検索
                    search_end = start_idx - 1
            else:
                # 対応する '{' が見つからない場合、この '}' は無視して前へ
                search_end = end_idx - 1
                
        return text, ""

    def _split_prompt_and_options(self, text: str):
        try:
            tokens = (text or "").strip().split()
            if not tokens:
                return "", "", False
            allowed = {"--ar", "--s", "--chaos", "--q", "--weird"}
            start_idx = None
            i = len(tokens) - 1
            while i >= 0:
                if tokens[i] in allowed:
                    start_idx = i
                    i -= 1
                    if i >= 0 and tokens[i] not in allowed and not tokens[i].startswith("--"):
                        i -= 1
                    while i >= 0:
                        if tokens[i] in allowed:
                            i -= 1
                            if i >= 0 and tokens[i] not in allowed and not tokens[i].startswith("--"):
                                i -= 1
                        else:
                            break
                    start_idx = i + 1
                    break
                else:
                    i -= 1
            if start_idx is not None and 0 <= start_idx < len(tokens):
                j = start_idx
                ok = True
                while j < len(tokens):
                    if tokens[j] in allowed:
                        j += 1
                        if j < len(tokens) and not tokens[j].startswith("--"):
                            j += 1
                    else:
                        ok = False
                        break
                if ok:
                    main_text = " ".join(tokens[:start_idx]).rstrip()
                    options_tail = (" " + " ".join(tokens[start_idx:])) if start_idx < len(tokens) else ""
                    return main_text, options_tail, True
            return (text or "").strip(), "", False
        except Exception:
            return (text or "").strip(), "", False

    def _inherit_options_if_present(self, original_text: str, new_text: str) -> str:
        orig_main, orig_opts, has_opts = self._split_prompt_and_options(original_text)
        if has_opts:
            new_main, _, _ = self._split_prompt_and_options(new_text)
            return new_main + orig_opts
        return self._strip_all_options(new_text)

    def _strip_all_options(self, text: str) -> str:
        try:
            pattern = r"(?:(?<=\s)|^)--(?:ar|s|chaos|q|weird)(?:\s+(?!-)[^\s]+)?"
            cleaned = re.sub(pattern, "", text)
            cleaned = re.sub(r"\s+", " ", cleaned).strip()
            return cleaned
        except Exception:
            return (text or "").strip()

    def _update_internal_prompt_from_text(self, full_text: str):
        normalized = (full_text or "").strip()
        if not normalized:
            return
        main_text, options_tail, _ = self._split_prompt_and_options(normalized)
        # 末尾2(JSONフラグ)は内部状態の main_prompt からは外す
        core_without_flags, _ = self._detach_content_flags_tail(main_text)
        core, movie_tail = self._detach_movie_tail_for_llm(core_without_flags)
        self.main_prompt = core
        self.tail_free_texts = f" {movie_tail}" if movie_tail else ""
        self.option_prompt = options_tail

    # =============================
    # フォント制御
    # =============================
    def cycle_font_scale(self):
        """UI全体のフォントプリセットを巡回させる。"""
        if not FONT_SCALE_PRESETS:
            return
        self.font_scale_level = (self.font_scale_level + 1) % len(FONT_SCALE_PRESETS)
        self._apply_font_scale()

    def _apply_font_scale(self):
        """現在のプリセットを QApplication とウィンドウ自身へ適用する。"""
        if not FONT_SCALE_PRESETS:
            return
        preset = FONT_SCALE_PRESETS[self.font_scale_level]
        base_size = preset["pt"]
        base_family = self._ui_font_family or self.font().family()
        new_font = QtGui.QFont(base_family, base_size)
        
        app = QtWidgets.QApplication.instance()
        if app is not None:
            app.setFont(new_font)
        self.setFont(new_font)
        
        # text_output エリアは常に +2pt 大きくする（可読性向上のため）
        if hasattr(self, 'text_output') and self.text_output is not None:
            output_font = QtGui.QFont(base_family, base_size + 2)
            self.text_output.setFont(output_font)
        
        # スタイルシートの動的更新 (BigActionボタンなどを強調するため)
        # QGroupBox のタイトルサイズなどをベース+1程度に調整
        big_action_size = base_size + 2
        group_title_size = base_size
        
        self.centralWidget().setStyleSheet(f"""
            QGroupBox {{
                font-weight: bold;
                font-size: {group_title_size}pt;
                border: 1px solid #ccc;
                border-radius: 6px;
                margin-top: 12px;
                padding-top: 10px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 3px;
            }}
            QPushButton {{
                padding: 5px 10px;
            }}
            QPushButton#BigAction {{
                font-weight: bold;
                font-size: {big_action_size}pt;
                padding: 8px 16px;
                background-color: #0078d4;
                color: white;
                border-radius: 4px;
            }}
            QPushButton#BigAction:hover {{
                background-color: #2b88d8;
            }}
        """)
        
        self._update_font_button_label(preset["label"])

    def _update_font_button_label(self, label: str):
        """フォント切替ボタンのラベルを最新状態に揃える。"""
        if self.button_font_scale:
            self.button_font_scale.setText(f"フォント: {label}")


def main():
    install_global_exception_logger()
    log_startup_environment()
    app = QtWidgets.QApplication(sys.argv)
    # 設定読み込みをここで実行し、エラー時のダイアログ表示を可能にする。
    initialize_settings()
    window = PromptGeneratorWindow()
    show_deferred_settings_notes(window)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
