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
import json
import os
import random
import re
import socket
import sqlite3
import subprocess
import sys
import traceback
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

import requests
from PySide6 import QtCore, QtGui, QtWidgets

from export_prompts_to_csv import MJImage

# =============================
# 設定・定数
# =============================
WINDOW_TITLE = "画像プロンプトランダム生成ツール (PySide6)"
DEFAULT_ROW_NUM = 10
DEFAULT_TAIL_MEDIA_TYPE = "image"
AVAILABLE_LLM_MODELS = [
    "gpt-5.1",
    "gpt-4o-mini",
    "gpt-4o",
]
TAIL_PRESET_CHOICES = {
    "image": [
        "",
        "A high resolution photograph. Very high resolution. 8K photo",
        "a Japanese ink painting. Zen painting",
        "a Medieval European painting.",
    ],
    "movie": [
        "",
        "{\"video_style\":{\"scope\":\"full_movie\",\"description\":\"sweeping cinematic sequence shot on 70mm film\",\"look\":\"dramatic lighting\"}}",
        "{\"video_style\":{\"scope\":\"full_movie\",\"description\":\"dynamic tracking shot captured as ultra high fidelity footage\",\"format\":\"4K HDR\"}}",
    ],
}
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

FONT_SCALE_PRESETS = [
    {"label": "標準", "pt": 11},
    {"label": "大", "pt": 13},
    {"label": "特大", "pt": 16},
    {"label": "4K", "pt": 20},
]

# 設定ファイルが欠損した場合も動かせるよう、サンプル相当のデフォルト値を持っておく。
DEFAULT_APP_SETTINGS = {
    "POSITION_FILE": "window_position_app_image_prompt_creator.txt",
    "BASE_FOLDER": "./app_image_prompt_creator",
    "DEFAULT_TXT_PATH": "./app_image_prompt_creator/image_prompt_parts.txt",
    "DEFAULT_DB_PATH": "./app_image_prompt_creator/image_prompt_parts.db",
    "EXCLUSION_CSV": "./app_image_prompt_creator/exclusion_targets.csv",
    "ARRANGE_PRESETS_YAML": "./app_image_prompt_creator/arrange_presets.yaml",
    "LLM_ENABLED": False,
    "LLM_MODEL": "gpt-5-mini",
    "LLM_MAX_COMPLETION_TOKENS": 4500,
    "LLM_TIMEOUT": 30,
    "OPENAI_API_KEY_ENV": "OPENAI_API_KEY",
    "LLM_INCLUDE_TEMPERATURE": False,
    "LLM_TEMPERATURE": 0.7,
}

# 設定読み込み中の警告やフォールバック内容を貯めて、ウィンドウ生成後にまとめて案内する。
SETTINGS_LOAD_NOTES: List[str] = []


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
    try:
        with open(resolved_path, "r", encoding="utf-8") as file:
            settings = yaml.safe_load(file) or {}
        return settings
    except FileNotFoundError:
        alternative = _prompt_settings_path(parent, resolved_path)
        if alternative:
            return load_yaml_settings(alternative, parent)
    except yaml.YAMLError as error:
        retry_target = _handle_yaml_error(parent, resolved_path, error)
        if retry_target:
            return load_yaml_settings(retry_target, parent)
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
LLM_ENABLED = DEFAULT_APP_SETTINGS["LLM_ENABLED"]
LLM_MODEL = DEFAULT_APP_SETTINGS["LLM_MODEL"]
LLM_TEMPERATURE = DEFAULT_APP_SETTINGS["LLM_TEMPERATURE"]
LLM_MAX_COMPLETION_TOKENS = DEFAULT_APP_SETTINGS["LLM_MAX_COMPLETION_TOKENS"]
LLM_TIMEOUT = DEFAULT_APP_SETTINGS["LLM_TIMEOUT"]
OPENAI_API_KEY_ENV = DEFAULT_APP_SETTINGS["OPENAI_API_KEY_ENV"]
ARRANGE_PRESETS_YAML = str(_resolve_path(DEFAULT_APP_SETTINGS["ARRANGE_PRESETS_YAML"]))
LLM_INCLUDE_TEMPERATURE = DEFAULT_APP_SETTINGS["LLM_INCLUDE_TEMPERATURE"]


def _merge_app_settings(raw_settings: dict) -> dict:
    """読み込んだ設定をデフォルトにマージして欠損値を補完する。"""

    merged = {"app_image_prompt_creator": deepcopy(DEFAULT_APP_SETTINGS)}
    if isinstance(raw_settings, dict):
        merged_app = raw_settings.get("app_image_prompt_creator") or {}
        merged["app_image_prompt_creator"].update(merged_app)
    return merged


def _apply_app_settings(app_settings: dict):
    """マージ済み設定をグローバル変数へ適用する。"""

    global BASE_FOLDER, DEFAULT_TXT_PATH, DEFAULT_DB_PATH, POSITION_FILE, EXCLUSION_CSV
    global LLM_ENABLED, LLM_MODEL, LLM_TEMPERATURE, LLM_MAX_COMPLETION_TOKENS
    global LLM_TIMEOUT, OPENAI_API_KEY_ENV, ARRANGE_PRESETS_YAML, LLM_INCLUDE_TEMPERATURE, settings

    settings = {"app_image_prompt_creator": deepcopy(app_settings)}
    BASE_FOLDER = app_settings.get("BASE_FOLDER", DEFAULT_APP_SETTINGS["BASE_FOLDER"])
    DEFAULT_TXT_PATH = app_settings.get("DEFAULT_TXT_PATH", DEFAULT_APP_SETTINGS["DEFAULT_TXT_PATH"])
    DEFAULT_DB_PATH = app_settings.get("DEFAULT_DB_PATH", DEFAULT_APP_SETTINGS["DEFAULT_DB_PATH"])
    POSITION_FILE = app_settings.get("POSITION_FILE", DEFAULT_APP_SETTINGS["POSITION_FILE"])
    EXCLUSION_CSV = app_settings.get("EXCLUSION_CSV", DEFAULT_APP_SETTINGS["EXCLUSION_CSV"])
    LLM_ENABLED = app_settings.get("LLM_ENABLED", DEFAULT_APP_SETTINGS["LLM_ENABLED"])
    LLM_MODEL = app_settings.get("LLM_MODEL", DEFAULT_APP_SETTINGS["LLM_MODEL"])
    LLM_TEMPERATURE = app_settings.get("LLM_TEMPERATURE", DEFAULT_APP_SETTINGS["LLM_TEMPERATURE"])
    LLM_MAX_COMPLETION_TOKENS = app_settings.get(
        "LLM_MAX_COMPLETION_TOKENS", DEFAULT_APP_SETTINGS["LLM_MAX_COMPLETION_TOKENS"]
    )
    LLM_TIMEOUT = app_settings.get("LLM_TIMEOUT", DEFAULT_APP_SETTINGS["LLM_TIMEOUT"])
    OPENAI_API_KEY_ENV = app_settings.get("OPENAI_API_KEY_ENV", DEFAULT_APP_SETTINGS["OPENAI_API_KEY_ENV"])
    ARRANGE_PRESETS_YAML = str(
        _resolve_path(app_settings.get("ARRANGE_PRESETS_YAML", DEFAULT_APP_SETTINGS["ARRANGE_PRESETS_YAML"]))
    )
    LLM_INCLUDE_TEMPERATURE = app_settings.get(
        "LLM_INCLUDE_TEMPERATURE", DEFAULT_APP_SETTINGS["LLM_INCLUDE_TEMPERATURE"]
    )


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


def send_llm_request(api_key: str, system_prompt: str, user_prompt: str, temperature: float, max_tokens: int, timeout: int, model_name: str, include_temperature: bool = True):
    endpoint, payload, response_kind = _compose_openai_payload(system_prompt, user_prompt, temperature, max_tokens, include_temperature, model_name)
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    resp = requests.post(endpoint, headers=headers, json=payload, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    text, finish_reason = _parse_openai_response(response_kind, data)
    return text, finish_reason, data


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

    def __init__(self, text: str, model: str, length_hint: str):
        super().__init__()
        self.text = text
        self.model = model
        self.length_hint = length_hint

    @QtCore.Slot()
    def run(self):
        try:
            api_key = os.getenv(OPENAI_API_KEY_ENV)
            if not api_key:
                self.failed.emit(f"{OPENAI_API_KEY_ENV} が未設定です。環境変数にAPIキーを設定してください。")
                return
            user_prompt = (
                f"Length adjustment request (target: {self.length_hint})\n"
                f"Instruction: Adjust length ONLY. Preserve meaning, style, and technical parameters.\n"
                f"Text: {self.text}"
            )
            system_prompt = _append_temperature_hint(
                "You are a text length adjustment specialist. Keep style but meet length hint.",
                self.model,
                LLM_TEMPERATURE,
            )
            content, finish_reason, _ = send_llm_request(
                api_key=api_key,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=LLM_TEMPERATURE,
                max_tokens=LLM_MAX_COMPLETION_TOKENS,
                timeout=LLM_TIMEOUT,
                model_name=self.model,
                include_temperature=LLM_INCLUDE_TEMPERATURE,
            )
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

    def __init__(self, text: str, model: str, mode: str, details: List[str]):
        super().__init__()
        self.text = text
        self.model = model
        self.mode = mode
        self.details = details or []

    @QtCore.Slot()
    def run(self):
        try:
            api_key = os.getenv(OPENAI_API_KEY_ENV)
            if not api_key:
                self.failed.emit(f"{OPENAI_API_KEY_ENV} が未設定です。環境変数にAPIキーを設定してください。")
                return
            system_prompt, user_prompt = self._build_prompts()
            content, finish_reason, _ = send_llm_request(
                api_key=api_key,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=LLM_TEMPERATURE,
                max_tokens=LLM_MAX_COMPLETION_TOKENS,
                timeout=LLM_TIMEOUT,
                model_name=self.model,
                include_temperature=LLM_INCLUDE_TEMPERATURE,
            )
            if finish_reason in LENGTH_LIMIT_REASONS:
                self.failed.emit("LLM応答がトークン制限に達しました。短くして再試行してください。")
                return
            self.finished.emit((content or "").strip())
        except Exception:
            self.failed.emit(get_exception_trace())

    def _build_prompts(self) -> Tuple[str, str]:
        detail_lines = "\n".join(f"- {d}" for d in self.details)
        if self.mode == "world":
            system_prompt = _append_temperature_hint(
                "You refine disjoint visual fragments into one coherent world description for a single cinematic environment. "
                "Do not narrate events in sequence; describe one continuous world in natural English.",
                self.model,
                LLM_TEMPERATURE,
            )
            user_prompt = (
                "Convert the following fragments into a single connected world that feels inhabitable.\n"
                f"Source summary: {self.text}\n"
                f"Fragments:\n{detail_lines}\n"
                "Output one concise paragraph that links every fragment into one world."
            )
            return system_prompt, user_prompt

        system_prompt = _append_temperature_hint(
            "You craft a single continuous storyboard beat that can be filmed as one shot. "
            "Blend all elements into a flowing moment without hard scene cuts.",
            self.model,
            LLM_TEMPERATURE,
        )
        user_prompt = (
            "Turn the fragments into a single-shot storyboard that can be captured in one camera move.\n"
            f"Source summary: {self.text}\n"
            f"Fragments:\n{detail_lines}\n"
            "Describe a vivid but single-cut sequence in one paragraph, focusing on visual continuity."
        )
        return system_prompt, user_prompt

class PromptGeneratorWindow(QtWidgets.QMainWindow):
    """PySide6 版のメインウィンドウ。UIとイベントを集約。"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle(WINDOW_TITLE)
        self.setMinimumSize(1100, 680)
        self.attribute_types: List[AttributeType] = []
        self.attribute_details: List[AttributeDetail] = []
        self.main_prompt: str = ""
        self.tail_free_texts: str = ""
        self.option_prompt: str = ""
        self.available_model_choices = list(dict.fromkeys([LLM_MODEL, *AVAILABLE_LLM_MODELS]))
        self._thread: Optional[QtCore.QThread] = None
        self._movie_llm_context: Optional[dict] = None
        self.font_scale_level = 0
        self._ui_font_family = self.font().family()
        self.button_font_scale: Optional[QtWidgets.QPushButton] = None
        self._build_ui()
        self._apply_font_scale()
        self.load_attribute_data()
        self.update_attribute_ui_choices()
        self._update_tail_free_text_choices(reset_selection=True)

    # =============================
    # UI 構築
    # =============================
    def _build_ui(self):
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        layout = QtWidgets.QHBoxLayout(central)

        self.left_panel = QtWidgets.QWidget()
        self.right_panel = QtWidgets.QWidget()
        layout.addWidget(self.left_panel, 2)
        layout.addWidget(self.right_panel, 3)

        self._build_left_panel()
        self._build_right_panel()

    def _build_left_panel(self):
        left_layout = QtWidgets.QVBoxLayout(self.left_panel)

        # LLMモデル選択
        model_layout = QtWidgets.QHBoxLayout()
        left_layout.addLayout(model_layout)
        model_layout.addWidget(QtWidgets.QLabel("LLMモデル:"))
        self.combo_llm_model = QtWidgets.QComboBox()
        self.combo_llm_model.addItems(self.available_model_choices)
        self.combo_llm_model.setCurrentIndex(0)
        model_layout.addWidget(self.combo_llm_model)
        self.label_current_model = QtWidgets.QLabel(f"選択中: {self.combo_llm_model.currentText()}")
        model_layout.addWidget(self.label_current_model)
        self.combo_llm_model.currentTextChanged.connect(self._on_model_change)

        self.button_font_scale = QtWidgets.QPushButton("フォント: 標準")
        self.button_font_scale.setToolTip("UI全体のフォントサイズを段階的に切り替えます。")
        self.button_font_scale.clicked.connect(self.cycle_font_scale)
        left_layout.addWidget(self.button_font_scale)

        # CSV 入出力
        csv_buttons = QtWidgets.QHBoxLayout()
        left_layout.addLayout(csv_buttons)
        csv_import_btn = QtWidgets.QPushButton("CSVをDBに投入")
        csv_import_btn.clicked.connect(self._open_csv_import_dialog)
        csv_buttons.addWidget(csv_import_btn)
        csv_export_btn = QtWidgets.QPushButton("(DB確認用CSV出力)")
        csv_export_btn.clicked.connect(self._export_csv)
        csv_buttons.addWidget(csv_export_btn)

        # 行数
        row_layout = QtWidgets.QHBoxLayout()
        left_layout.addLayout(row_layout)
        row_layout.addWidget(QtWidgets.QLabel("行数:"))
        self.spin_row_num = QtWidgets.QSpinBox()
        self.spin_row_num.setMinimum(1)
        self.spin_row_num.setMaximum(999)
        self.spin_row_num.setValue(DEFAULT_ROW_NUM)
        row_layout.addWidget(self.spin_row_num)

        # 属性選択（スクロール可能）
        self.attribute_area = QtWidgets.QScrollArea()
        self.attribute_area.setWidgetResizable(True)
        self.attribute_container = QtWidgets.QWidget()
        self.attribute_layout = QtWidgets.QFormLayout(self.attribute_container)
        self.attribute_area.setWidget(self.attribute_container)
        left_layout.addWidget(self.attribute_area, 1)

        # 自動反映チェック
        auto_layout = QtWidgets.QHBoxLayout()
        left_layout.addLayout(auto_layout)
        self.check_autofix = QtWidgets.QCheckBox()
        auto_layout.addWidget(QtWidgets.QLabel("自動反映:"))
        auto_layout.addWidget(self.check_autofix)

        # 末尾プリセット切替
        tail_media_layout = QtWidgets.QHBoxLayout()
        left_layout.addLayout(tail_media_layout)
        tail_media_layout.addWidget(QtWidgets.QLabel("末尾プリセット用途:"))
        self.combo_tail_media_type = QtWidgets.QComboBox()
        self.combo_tail_media_type.addItems(list(TAIL_PRESET_CHOICES.keys()))
        self.combo_tail_media_type.currentTextChanged.connect(self._on_tail_media_type_change)
        tail_media_layout.addWidget(self.combo_tail_media_type)

        # 末尾固定テキスト
        tail_layout = QtWidgets.QHBoxLayout()
        left_layout.addLayout(tail_layout)
        self.check_tail_free = QtWidgets.QCheckBox()
        tail_layout.addWidget(QtWidgets.QLabel("末尾1:"))
        tail_layout.addWidget(self.check_tail_free)
        self.combo_tail_free = QtWidgets.QComboBox()
        self.combo_tail_free.setEditable(True)
        tail_layout.addWidget(self.combo_tail_free)
        self.combo_tail_free.setToolTip("末尾固定文を選択または編集できます。")

        # オプションコンボ
        self.combo_tail_ar = self._add_option_row(left_layout, "ar オプション:", AR_OPTIONS)
        self.combo_tail_s = self._add_option_row(left_layout, "s オプション:", S_OPTIONS)
        self.combo_tail_chaos = self._add_option_row(left_layout, "chaos オプション:", CHAOS_OPTIONS)
        self.combo_tail_q = self._add_option_row(left_layout, "q オプション:", Q_OPTIONS)
        self.combo_tail_weird = self._add_option_row(left_layout, "weird オプション:", WEIRD_OPTIONS)

        # 除外語句
        exclusion_layout = QtWidgets.QHBoxLayout()
        left_layout.addLayout(exclusion_layout)
        exclusion_layout.addWidget(QtWidgets.QLabel(LABEL_EXCLUSION_WORDS))
        self.check_exclusion = QtWidgets.QCheckBox()
        exclusion_layout.addWidget(self.check_exclusion)
        self.combo_exclusion = QtWidgets.QComboBox()
        self.combo_exclusion.setEditable(True)
        exclusion_layout.addWidget(self.combo_exclusion)
        self.combo_exclusion.addItems(load_exclusion_words())
        open_exclusion_btn = QtWidgets.QPushButton("除外語句CSVを開く")
        open_exclusion_btn.clicked.connect(self._open_exclusion_csv)
        left_layout.addWidget(open_exclusion_btn)

        # ボタン群
        generate_btn = QtWidgets.QPushButton("生成")
        generate_btn.clicked.connect(self.generate_text)
        left_layout.addWidget(generate_btn)

        generate_copy_btn = QtWidgets.QPushButton("生成とコピー（全文）")
        generate_copy_btn.clicked.connect(self.generate_and_copy)
        left_layout.addWidget(generate_copy_btn)

        copy_btn = QtWidgets.QPushButton("クリップボードにコピー(全文)")
        copy_btn.clicked.connect(self.copy_all_to_clipboard)
        left_layout.addWidget(copy_btn)

        update_tail_btn = QtWidgets.QPushButton("末尾固定部のみ更新")
        update_tail_btn.clicked.connect(self.update_tail_free_texts)
        left_layout.addWidget(update_tail_btn)

        update_option_btn = QtWidgets.QPushButton("オプションのみ更新")
        update_option_btn.clicked.connect(self.update_option)
        left_layout.addWidget(update_option_btn)

        movie_box = QtWidgets.QGroupBox("動画用に整形(JSON)")
        movie_layout = QtWidgets.QVBoxLayout(movie_box)
        simple_row = QtWidgets.QHBoxLayout()
        simple_row.addWidget(QtWidgets.QLabel("簡易整形(LLMなし):"))
        format_movie_btn = QtWidgets.QPushButton("JSONデータ化")
        format_movie_btn.clicked.connect(self.handle_format_for_movie_json)
        simple_row.addWidget(format_movie_btn)
        movie_layout.addLayout(simple_row)

        llm_row = QtWidgets.QHBoxLayout()
        llm_row.addWidget(QtWidgets.QLabel("LLM改良:"))
        world_btn = QtWidgets.QPushButton("世界観整形")
        world_btn.clicked.connect(self.handle_movie_worldbuilding)
        llm_row.addWidget(world_btn)
        story_btn = QtWidgets.QPushButton("ストーリー構築")
        story_btn.clicked.connect(self.handle_movie_storyboard)
        llm_row.addWidget(story_btn)
        movie_layout.addLayout(llm_row)
        left_layout.addWidget(movie_box)

        # LLM アレンジ
        arrange_layout = QtWidgets.QHBoxLayout()
        left_layout.addLayout(arrange_layout)
        arrange_layout.addWidget(QtWidgets.QLabel("文字数調整:"))
        self.combo_length_adjust = QtWidgets.QComboBox()
        self.combo_length_adjust.addItems(["半分", "2割減", "同程度", "2割増", "倍"])
        arrange_layout.addWidget(self.combo_length_adjust)
        arrange_btn = QtWidgets.QPushButton("文字数調整してコピー")
        arrange_btn.clicked.connect(self.handle_length_adjust_and_copy)
        left_layout.addWidget(arrange_btn)

    def _build_right_panel(self):
        right_layout = QtWidgets.QVBoxLayout(self.right_panel)
        self.text_output = QtWidgets.QTextEdit()
        self.text_output.setPlaceholderText("ここに生成結果が表示されます")
        right_layout.addWidget(self.text_output, 1)

    def _add_option_row(self, parent_layout: QtWidgets.QVBoxLayout, label: str, values: Iterable[str]) -> QtWidgets.QComboBox:
        row = QtWidgets.QHBoxLayout()
        parent_layout.addLayout(row)
        row.addWidget(QtWidgets.QLabel(label))
        checkbox = QtWidgets.QCheckBox()
        row.addWidget(checkbox)
        combo = QtWidgets.QComboBox()
        combo.addItems([str(v) for v in values])
        combo.setEditable(True)
        combo.setProperty("toggle", checkbox)
        row.addWidget(combo)
        combo.currentTextChanged.connect(self.auto_update)
        checkbox.stateChanged.connect(self.auto_update)
        return combo

    # =============================
    # データロード
    # =============================
    def load_attribute_data(self):
        self.attribute_types.clear()
        self.attribute_details.clear()
        conn = sqlite3.connect(DEFAULT_DB_PATH)
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
        conn.close()

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
            detail_values = ["-"] + [
                f"{detail.description} ({detail.content_count})"
                for detail in self.attribute_details
                if detail.attribute_type_id == attr.id and detail.content_count > 0
            ]
            detail_combo = QtWidgets.QComboBox()
            detail_combo.addItems(detail_values)
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
        presets = TAIL_PRESET_CHOICES.get(self.combo_tail_media_type.currentText(), TAIL_PRESET_CHOICES[DEFAULT_TAIL_MEDIA_TYPE])
        current = self.combo_tail_free.currentText()
        self.combo_tail_free.clear()
        self.combo_tail_free.addItems(presets)
        if not reset_selection and current in presets:
            self.combo_tail_free.setCurrentText(current)
        else:
            self.combo_tail_free.setCurrentIndex(0)

    def auto_update(self):
        if self.check_autofix.isChecked() and self.main_prompt:
            self.update_option()

    def _open_csv_import_dialog(self):
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("CSV Import")
        layout = QtWidgets.QVBoxLayout(dialog)
        layout.addWidget(QtWidgets.QLabel("CSV データを貼り付けてください"))
        text_edit = QtWidgets.QTextEdit()
        layout.addWidget(text_edit)
        button = QtWidgets.QPushButton("投入")
        layout.addWidget(button)

        def handle_import():
            content = text_edit.toPlainText().strip()
            if not content:
                QtWidgets.QMessageBox.critical(self, "エラー", "CSVデータを入力してください。")
                return
            try:
                self._process_csv(content)
                QtWidgets.QMessageBox.information(self, "成功", "CSVデータが正常に処理されました。")
                self.load_attribute_data()
                self.update_attribute_ui_choices()
                dialog.accept()
            except Exception:
                QtWidgets.QMessageBox.critical(self, "エラー", f"CSVの処理中にエラーが発生しました: {get_exception_trace()}")

        button.clicked.connect(handle_import)
        dialog.exec()

    def _process_csv(self, csv_content: str):
        conn = sqlite3.connect(DEFAULT_DB_PATH)
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
        for line in csv_content.splitlines():
            if "citation[oaicite" in line or "```" in line:
                continue
            if line.strip() and len(line) > 10 and [line[0], line[-1]] == ['"', '"']:
                line = line.replace('"""', '"')
                try:
                    content, attribute_detail_ids = line.strip('"').split('","')
                except Exception:
                    content, attribute_detail_ids = line.strip('"').split('", "')
                cursor.execute('INSERT INTO prompts (content) VALUES (?)', (content,))
                prompt_id = cursor.lastrowid
                for attribute_detail_id in attribute_detail_ids.split(','):
                    cursor.execute(
                        'INSERT INTO prompt_attribute_details (prompt_id, attribute_detail_id) VALUES (?, ?)',
                        (prompt_id, int(attribute_detail_id)),
                    )
        conn.commit()
        conn.close()

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
        if self.check_tail_free.isChecked() and self.combo_tail_free.currentText().strip():
            return " " + self.combo_tail_free.currentText().strip()
        return ""

    def generate_text(self):
        try:
            conn = sqlite3.connect(DEFAULT_DB_PATH)
            cursor = conn.cursor()
            total_lines = int(self.spin_row_num.value())
            exclusion_words = [w.strip() for w in self.combo_exclusion.currentText().split(',') if w.strip()]
            selected_lines = []
            if self.check_exclusion.isChecked() and exclusion_words:
                self._update_exclusion_words(exclusion_words)

            for attr in self.attribute_types:
                detail_combo = self.attribute_combo_map[attr.id]
                count_combo = self.attribute_count_map[attr.id]
                detail = detail_combo.currentText()
                count = count_combo.currentText()
                if detail != "-" and count != "-":
                    count_int = int(count)
                    if count_int > 0:
                        detail_description = detail.split(" (")[0]
                        detail_value = next((d.value for d in self.attribute_details if d.description == detail_description), None)
                        if detail_value:
                            if self.check_exclusion.isChecked() and exclusion_words:
                                exclusion_condition = " AND " + " AND ".join("p.content NOT LIKE ?" for _ in exclusion_words)
                                query = (
                                    "SELECT p.content FROM prompts p "
                                    "JOIN prompt_attribute_details pad ON p.id = pad.prompt_id "
                                    "JOIN attribute_details ad ON pad.attribute_detail_id = ad.id "
                                    "WHERE ad.value = ? "
                                    f"{exclusion_condition}"
                                )
                                params = [detail_value] + [f"%{word}%" for word in exclusion_words]
                                cursor.execute(query, params)
                            else:
                                cursor.execute(
                                    "SELECT p.content FROM prompts p "
                                    "JOIN prompt_attribute_details pad ON p.id = pad.prompt_id "
                                    "JOIN attribute_details ad ON pad.attribute_detail_id = ad.id "
                                    "WHERE ad.value = ?",
                                    (detail_value,),
                                )
                            matching = cursor.fetchall()
                            selected_lines.extend(random.sample(matching, min(count_int, len(matching))))

            remaining = total_lines - len(selected_lines)
            if remaining > 0:
                if self.check_exclusion.isChecked() and exclusion_words:
                    exclusion_condition = " AND " + " AND ".join("content NOT LIKE ?" for _ in exclusion_words)
                    query = f"SELECT content FROM prompts WHERE 1=1 {exclusion_condition}"
                    cursor.execute(query, [f"%{w}%" for w in exclusion_words])
                else:
                    cursor.execute("SELECT content FROM prompts")
                all_prompts = cursor.fetchall()
                remaining_pool = [line for line in all_prompts if line not in selected_lines]
                selected_lines.extend(random.sample(remaining_pool, min(len(remaining_pool), remaining)))
            conn.close()

            random.shuffle(selected_lines)
            processed_lines = []
            for line in selected_lines:
                text = line[0].strip()
                if text.endswith((",", "、", ";", ":", "；", "：", "!", "?", "\n")):
                    text = text[:-1] + "."
                elif not text.endswith("."):
                    text += "."
                processed_lines.append(text)
            self.main_prompt = " ".join(processed_lines)
            self.update_option()
        except Exception:
            QtWidgets.QMessageBox.critical(self, "エラー", f"エラーが発生しました: {get_exception_trace()}")

    def update_option(self):
        self.option_prompt = self._make_option_prompt()
        self.tail_free_texts = self._make_tail_text()
        result = f"{self.main_prompt}{self.tail_free_texts}{self.option_prompt}"
        self.text_output.setPlainText(result)

    def update_tail_free_texts(self):
        self.tail_free_texts = self._make_tail_text()
        result = f"{self.main_prompt}{self.tail_free_texts}{self.option_prompt}"
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
            result = self._compose_movie_prompt(world_json, movie_tail, options_tail)
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
        self._start_movie_llm_transformation("world", main_text, details, movie_tail, options_tail)

    def handle_movie_storyboard(self):
        prepared = self._prepare_movie_prompt_parts()
        if not prepared:
            return
        main_text, options_tail, movie_tail = prepared
        details = self._extract_sentence_details(main_text)
        self._start_movie_llm_transformation("storyboard", main_text, details, movie_tail, options_tail)

    def handle_length_adjust_and_copy(self):
        src = self.text_output.toPlainText().strip()
        if not src:
            QtWidgets.QMessageBox.warning(self, "注意", "まずプロンプトを生成してください。")
            return
        target = self.combo_length_adjust.currentText()
        self._start_llm_worker(src, target)

    def _start_background_worker(self, worker: QtCore.QObject, success_handler, failure_handler):
        if self._thread and self._thread.isRunning():
            QtWidgets.QMessageBox.information(self, "実行中", "LLM 呼び出しが進行中です。完了までお待ちください。")
            return False
        thread = QtCore.QThread()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(lambda result: success_handler(thread, worker, result))
        worker.failed.connect(lambda err: failure_handler(thread, worker, err))
        thread.start()
        self._thread = thread
        return True

    def _start_llm_worker(self, text: str, length_hint: str):
        if not LLM_ENABLED:
            QtWidgets.QMessageBox.warning(self, "注意", "LLMが無効化されています。YAMLで LLM_ENABLED を true にしてください。")
            return
        worker = LLMWorker(text=text, model=self.combo_llm_model.currentText(), length_hint=length_hint)
        self._start_background_worker(worker, self._handle_llm_success, self._handle_llm_failure)

    def _start_movie_llm_transformation(
        self, mode: str, main_text: str, details: List[str], movie_tail: str, options_tail: str
    ):
        if not LLM_ENABLED:
            QtWidgets.QMessageBox.warning(self, "注意", "LLMが無効化されています。YAMLで LLM_ENABLED を true にしてください。")
            return
        worker = MovieLLMWorker(text=main_text, model=self.combo_llm_model.currentText(), mode=mode, details=details)
        context = {
            "mode": mode,
            "movie_tail": movie_tail,
            "options_tail": options_tail,
        }
        if self._start_background_worker(worker, self._handle_movie_llm_success, self._handle_movie_llm_failure):
            self._movie_llm_context = context

    def _handle_llm_success(self, thread: QtCore.QThread, worker: LLMWorker, result: str):
        thread.quit()
        thread.wait()
        worker.deleteLater()
        self._thread = None
        if not result:
            QtWidgets.QMessageBox.warning(self, "注意", "LLM から空のレスポンスが返されました。")
            return
        clean = self._inherit_options_if_present(self.text_output.toPlainText(), result)
        self.text_output.setPlainText(clean)
        QtGui.QGuiApplication.clipboard().setText(clean)
        QtWidgets.QMessageBox.information(self, "コピー完了", "LLMで調整したプロンプトをコピーしました。")

    def _handle_movie_llm_success(self, thread: QtCore.QThread, worker: MovieLLMWorker, result: str):
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
        combined = self._compose_movie_prompt(world_json, movie_tail, options_tail)
        self.text_output.setPlainText(combined)
        self._update_internal_prompt_from_text(combined)
        QtGui.QGuiApplication.clipboard().setText(combined)
        label = "世界観整形" if mode == "world" else "ストーリー構築"
        QtWidgets.QMessageBox.information(self, "コピー完了", f"{label}をLLMで実行し、全文をコピーしました。")

    def _handle_llm_failure(self, thread: QtCore.QThread, worker: LLMWorker, error: str):
        thread.quit()
        thread.wait()
        worker.deleteLater()
        self._thread = None
        QtWidgets.QMessageBox.critical(self, "エラー", f"LLM 呼び出しでエラーが発生しました:\n{error}")

    def _handle_movie_llm_failure(self, thread: QtCore.QThread, worker: MovieLLMWorker, error: str):
        thread.quit()
        thread.wait()
        worker.deleteLater()
        self._thread = None
        self._movie_llm_context = None
        QtWidgets.QMessageBox.critical(self, "エラー", f"動画用整形のLLM処理でエラーが発生しました:\n{error}")

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
        core_without_movie, movie_tail = self._detach_movie_tail_for_llm(src)
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
                "summary": (summary or "").strip(),
                "details": details or [(summary or "").strip()],
            }
        }
        return json.dumps(payload, ensure_ascii=False)

    def _compose_movie_prompt(self, core_json: str, movie_tail: str, options_tail: str) -> str:
        """生成したJSONと末尾要素（動画スタイル・MJオプション）を安全に連結する。"""
        parts = [core_json]
        if movie_tail:
            parts.append(movie_tail.strip())
        if options_tail:
            parts.append(options_tail.strip())
        return " ".join(p for p in parts if p)

    def _detach_movie_tail_for_llm(self, text: str) -> Tuple[str, str]:
        tokens = (text or "").strip().split()
        if not tokens:
            return "", ""

        movie_tail = ""
        movie_idx = None
        for i in range(len(tokens) - 1, -1, -1):
            if tokens[i].startswith("{") and "video_style" in tokens[i]:
                movie_idx = i
                break

        if movie_idx is not None:
            movie_tail = tokens[movie_idx]
            tokens = tokens[:movie_idx] + tokens[movie_idx + 1 :]

        return " ".join(tokens).strip(), movie_tail

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
        core, movie_tail = self._detach_movie_tail_for_llm(main_text)
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
        base_family = self._ui_font_family or self.font().family()
        new_font = QtGui.QFont(base_family, preset["pt"])
        app = QtWidgets.QApplication.instance()
        if app is not None:
            app.setFont(new_font)
        self.setFont(new_font)
        self._update_font_button_label(preset["label"])

    def _update_font_button_label(self, label: str):
        """フォント切替ボタンのラベルを最新状態に揃える。"""
        if self.button_font_scale:
            self.button_font_scale.setText(f"フォント: {label}")


def main():
    app = QtWidgets.QApplication(sys.argv)
    # 設定読み込みをここで実行し、エラー時のダイアログ表示を可能にする。
    initialize_settings()
    window = PromptGeneratorWindow()
    show_deferred_settings_notes(window)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
