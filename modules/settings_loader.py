"""YAML設定の読み込みと適用を担当するモジュール。"""

from __future__ import annotations

import logging
from copy import deepcopy
from pathlib import Path
from typing import Optional

import yaml
from PySide6 import QtWidgets

from . import config
from .logging_utils import log_structured


def resolve_path(path_value, base_dir: Path = config.SCRIPT_DIR) -> Path:
    """基準ディレクトリからの相対パスを絶対化する。"""

    if path_value is None:
        return base_dir
    if isinstance(path_value, Path):
        path = path_value
    else:
        path = Path(str(path_value))
    if path.is_absolute():
        return path
    return base_dir / path


yaml_settings_path = resolve_path("desktop_gui_settings.yaml")


def _prompt_settings_path(parent: Optional[QtWidgets.QWidget], resolved_path: Path) -> Optional[Path]:
    """設定ファイル欠損時に、ユーザーへパス確認/再指定を促すダイアログを表示。"""

    app = QtWidgets.QApplication.instance()
    if app is None:
        config.SETTINGS_LOAD_NOTES.append(
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
        config.SETTINGS_LOAD_NOTES.append(
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
    config.SETTINGS_LOAD_NOTES.append(message)

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

    resolved_path = resolve_path(file_path)
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
    return deepcopy({"app_image_prompt_creator": config.DEFAULT_APP_SETTINGS})


def _merge_app_settings(raw_settings: dict) -> dict:
    """読み込んだ設定をデフォルトにマージして欠損値を補完する。"""

    merged = {"app_image_prompt_creator": deepcopy(config.DEFAULT_APP_SETTINGS)}
    if isinstance(raw_settings, dict):
        merged_app = raw_settings.get("app_image_prompt_creator") or {}
        merged["app_image_prompt_creator"].update(merged_app)
    return merged


def _normalize_llm_model(model_name: Optional[str]) -> str:
    """設定値のモデル名を検証し、無効なら最初の有効モデルへフォールバックする。"""

    if model_name in config.AVAILABLE_LLM_MODELS:
        return model_name

    fallback_model = config.AVAILABLE_LLM_MODELS[0]
    config.SETTINGS_LOAD_NOTES.append(
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

    config.settings = {"app_image_prompt_creator": deepcopy(app_settings)}
    config.BASE_FOLDER = str(resolve_path(app_settings.get("BASE_FOLDER", config.DEFAULT_APP_SETTINGS["BASE_FOLDER"])))
    config.DEFAULT_TXT_PATH = str(resolve_path(app_settings.get("DEFAULT_TXT_PATH", config.DEFAULT_APP_SETTINGS["DEFAULT_TXT_PATH"])))
    config.DEFAULT_DB_PATH = str(resolve_path(app_settings.get("DEFAULT_DB_PATH", config.DEFAULT_APP_SETTINGS["DEFAULT_DB_PATH"])))
    config.POSITION_FILE = str(resolve_path(app_settings.get("POSITION_FILE", config.DEFAULT_APP_SETTINGS["POSITION_FILE"])))
    config.EXCLUSION_CSV = str(resolve_path(app_settings.get("EXCLUSION_CSV", config.DEFAULT_APP_SETTINGS["EXCLUSION_CSV"])))
    config.DEDUPLICATE_PROMPTS = app_settings.get("DEDUPLICATE_PROMPTS", config.DEFAULT_APP_SETTINGS["DEDUPLICATE_PROMPTS"])
    config.LLM_ENABLED = app_settings.get("LLM_ENABLED", config.DEFAULT_APP_SETTINGS["LLM_ENABLED"])
    config.LLM_MODEL = _normalize_llm_model(app_settings.get("LLM_MODEL", config.DEFAULT_APP_SETTINGS["LLM_MODEL"]))
    config.LLM_TEMPERATURE = app_settings.get("LLM_TEMPERATURE", config.DEFAULT_APP_SETTINGS["LLM_TEMPERATURE"])
    config.LLM_MAX_COMPLETION_TOKENS = app_settings.get(
        "LLM_MAX_COMPLETION_TOKENS", config.DEFAULT_APP_SETTINGS["LLM_MAX_COMPLETION_TOKENS"]
    )
    config.LLM_TIMEOUT = app_settings.get("LLM_TIMEOUT", config.DEFAULT_APP_SETTINGS["LLM_TIMEOUT"])
    config.OPENAI_API_KEY_ENV = app_settings.get("OPENAI_API_KEY_ENV", config.DEFAULT_APP_SETTINGS["OPENAI_API_KEY_ENV"])
    config.ARRANGE_PRESETS_YAML = str(
        resolve_path(app_settings.get("ARRANGE_PRESETS_YAML", config.DEFAULT_APP_SETTINGS["ARRANGE_PRESETS_YAML"]))
    )
    config.TAIL_PRESETS_YAML = str(
        resolve_path(app_settings.get("TAIL_PRESETS_YAML", config.DEFAULT_APP_SETTINGS["TAIL_PRESETS_YAML"]))
    )
    config.SORA_CHARACTERS_YAML = str(
        resolve_path(app_settings.get("SORA_CHARACTERS_YAML", config.DEFAULT_APP_SETTINGS["SORA_CHARACTERS_YAML"]))
    )
    config.LLM_INCLUDE_TEMPERATURE = app_settings.get(
        "LLM_INCLUDE_TEMPERATURE", config.DEFAULT_APP_SETTINGS["LLM_INCLUDE_TEMPERATURE"]
    )
    config.settings["app_image_prompt_creator"]["LLM_MODEL"] = config.LLM_MODEL
    snapshot = {k.lower(): app_settings.get(k) for k in config.SETTINGS_SNAPSHOT_KEYS if k in app_settings}
    log_structured(logging.INFO, "app_settings_applied", snapshot)


def initialize_settings(parent: Optional[QtWidgets.QWidget] = None):
    """設定ファイルを読み込み、フォールバック結果を反映する初期化関数。"""

    raw_settings = load_yaml_settings(yaml_settings_path, parent)
    merged_settings = _merge_app_settings(raw_settings)
    _apply_app_settings(merged_settings["app_image_prompt_creator"])


def show_deferred_settings_notes(parent: Optional[QtWidgets.QWidget]):
    """アプリ起動後にまとめて設定読み込み時の警告を表示する。"""

    if not config.SETTINGS_LOAD_NOTES:
        return
    QtWidgets.QMessageBox.information(
        parent,
        "設定ファイルの確認",
        "\n\n".join(config.SETTINGS_LOAD_NOTES),
    )
    config.SETTINGS_LOAD_NOTES.clear()
