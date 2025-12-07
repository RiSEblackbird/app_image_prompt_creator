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
import logging
import os
import random
import re
import sqlite3
import subprocess
import sys
import time
from contextlib import closing
from copy import deepcopy
from pathlib import Path
from typing import Iterable, List, Optional, Set, Tuple

from PySide6 import QtCore, QtGui, QtWidgets

from modules import config
from modules.llm import (
    ArrangeLLMWorker,
    ChaosMixLLMWorker,
    GeneratePromptLLMWorker,
    LLMWorker,
    MovieLLMWorker,
)
from modules.logging_utils import (
    get_exception_trace,
    install_global_exception_logger,
    log_startup_environment,
    log_structured,
    setup_logging,
)
from modules.prompt_data import (
    AttributeDetail,
    AttributeType,
    load_arrange_presets_from_yaml,
    load_tail_presets_from_yaml,
)
from modules.prompt_data_mixins import PromptDataMixin
from modules.prompt_ui_mixins import PromptUIMixin
from modules.settings_loader import (
    initialize_settings,
    load_yaml_settings,
    resolve_path,
    show_deferred_settings_notes,
)
from modules.prompt_text_utils import (
    build_movie_json_payload,
    compose_movie_prompt,
    detach_content_flags_tail,
    detach_movie_tail_for_llm,
    extract_sentence_details,
    inherit_options_if_present,
    split_prompt_and_options,
    strip_all_options,
)
from modules.ui_helpers import combo_language_code

setup_logging()


def __getattr__(name: str):
    """設定・定数を modules.config から遅延取得するためのフォールバック。"""
    if hasattr(config, name):
        return getattr(config, name)
    raise AttributeError(f"{__name__} has no attribute {name}")


class PromptGeneratorWindow(QtWidgets.QMainWindow, PromptUIMixin, PromptDataMixin):
    """PySide6 版のメインウィンドウ。UIとイベントを集約。"""

    _worker_success = QtCore.Signal(object, object, object, object)
    _worker_failure = QtCore.Signal(object, object, object, object)

    def __init__(self):
        super().__init__()
        self.setWindowTitle(config.WINDOW_TITLE)
        self.setMinimumSize(1100, 680)
        self.attribute_types: List[AttributeType] = []
        self.attribute_details: List[AttributeDetail] = []
        self.main_prompt: str = ""
        self.tail_free_texts: str = ""
        self.option_prompt: str = ""
        self.available_model_choices = list(config.AVAILABLE_LLM_MODELS)
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
                "llm_model": config.LLM_MODEL,
                "db_path": config.DEFAULT_DB_PATH,
            },
        )

    def _ensure_model_choice_alignment(self) -> None:
        """設定値とコンボボックスの候補がズレた場合に警告し、UIを有効モデルへ合わせる。"""

        if not self.available_model_choices:
            return

        if config.LLM_MODEL not in self.available_model_choices:
            fallback_model = self.available_model_choices[0]
            config.SETTINGS_LOAD_NOTES.append(
                f"UI候補に存在しないLLMモデル '{config.LLM_MODEL}' を検出したため '{fallback_model}' に切り替えました。"
            )
            log_structured(
                logging.WARNING,
                "llm_model_ui_mismatch",
                {"configured_model": config.LLM_MODEL, "fallback_model": fallback_model},
            )
            target_model = fallback_model
        else:
            target_model = config.LLM_MODEL

        index = self.combo_llm_model.findText(target_model)
        if index < 0:
            index = 0
        self.combo_llm_model.setCurrentIndex(index)
        config.LLM_MODEL = self.combo_llm_model.currentText()
        self.label_current_model.setText(f"選択中: {config.LLM_MODEL}")

    # =============================
    # UI 構築
    # =============================
    def _build_left_pane_content(self, layout):
        return PromptUIMixin._build_left_pane_content(self, layout)

    def _add_option_cell(self, grid: QtWidgets.QGridLayout, row: int, label: str, values: Iterable[str]) -> QtWidgets.QComboBox:
        return PromptUIMixin._add_option_cell(self, grid, row, label, values)

    def _build_right_pane_content(self, layout):
        return PromptUIMixin._build_right_pane_content(self, layout)

    def _get_db_path_or_warn(self) -> Optional[Path]:
        return PromptDataMixin._get_db_path_or_warn(self)

    def _connect_with_foreign_keys(self, db_path: Path) -> sqlite3.Connection:
        return PromptDataMixin._connect_with_foreign_keys(self, db_path)

    def _build_db_missing_message(self, db_path: Path) -> str:
        return PromptDataMixin._build_db_missing_message(self, db_path)

    def _show_db_missing_dialog(self, db_path: Path) -> None:
        return PromptDataMixin._show_db_missing_dialog(self, db_path)

    # =============================
    # データロード
    # =============================
    def load_attribute_data(self):
        return PromptDataMixin.load_attribute_data(self)

    def update_attribute_ui_choices(self):
        return PromptDataMixin.update_attribute_ui_choices(self)

    # =============================
    # UI イベント
    # =============================
    def _on_model_change(self, value: str):
        self.label_current_model.setText(f"選択中: {value}")
        print(f"[LLM] 現在のモデル: {value} (changed via UI)")

    def _on_tail_media_type_change(self, value: str):
        return PromptDataMixin._on_tail_media_type_change(self, value)

    def _update_tail_free_text_choices(self, reset_selection: bool):
        return PromptDataMixin._update_tail_free_text_choices(self, reset_selection)

    def auto_update(self):
        if self.check_autofix.isChecked() and self.main_prompt:
            # 自動反映時は、現在の出力欄テキストを基準に main_prompt 等を同期してから末尾を再構成する。
            self.update_option(sync_from_text=True)

    def _open_csv_import_dialog(self):
        return PromptDataMixin._open_csv_import_dialog(self)

    def _populate_sample_csv_rows(self, text_edit: QtWidgets.QTextEdit) -> None:
        return PromptDataMixin._populate_sample_csv_rows(self, text_edit)

    def _process_csv(self, csv_content: str) -> Tuple[int, List[Tuple[int, str, str]], Optional[Path]]:
        return PromptDataMixin._process_csv(self, csv_content)

    def _export_failed_rows(self, failed_rows: List[Tuple[int, str, str]]) -> Path:
        return PromptDataMixin._export_failed_rows(self, failed_rows)

    def _export_csv(self):
        return PromptDataMixin._export_csv(self)

    def _open_exclusion_csv(self):
        return PromptDataMixin._open_exclusion_csv(self)

    def _setup_tail_presets_watcher(self) -> None:
        return PromptDataMixin._setup_tail_presets_watcher(self)

    @QtCore.Slot(str)
    def _on_tail_presets_file_changed(self, changed_path: str) -> None:
        return PromptDataMixin._on_tail_presets_file_changed(self, changed_path)

    def _reload_tail_presets_and_refresh_ui(self) -> None:
        return PromptDataMixin._reload_tail_presets_and_refresh_ui(self)

    def _setup_arrange_presets_watcher(self) -> None:
        return PromptDataMixin._setup_arrange_presets_watcher(self)

    @QtCore.Slot(str)
    def _on_arrange_presets_file_changed(self, changed_path: str) -> None:
        return PromptDataMixin._on_arrange_presets_file_changed(self, changed_path)

    def _reload_arrange_presets(self) -> None:
        return PromptDataMixin._reload_arrange_presets(self)

    def _update_arrange_preset_choices(self):
        return PromptDataMixin._update_arrange_preset_choices(self)

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
        output_language = combo_language_code(getattr(self, "combo_arrange_output_lang", None))
        
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
        main_text, options_tail, movie_tail, content_flags_tail = prepared
        if not main_text.strip():
            QtWidgets.QMessageBox.warning(self, "注意", "メインテキストが見つかりません。")
            return
        fragments = extract_sentence_details(main_text)
        video_style_arg, content_flags_arg = self._resolve_style_reflection_contexts(movie_tail, content_flags_tail)
        length_limit = self._get_selected_movie_length_limit()
        output_language = combo_language_code(getattr(self, "combo_movie_output_lang", None))
        self._start_chaos_mix_llm_worker(
            main_text=main_text,
            fragments=fragments,
            movie_tail=movie_tail,
            options_tail=options_tail,
            video_style_context=video_style_arg,
            content_flags_context=content_flags_arg,
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
        if not config.LLM_ENABLED:
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
        merged = inherit_options_if_present(self.text_output.toPlainText(), result)
        base_without_flags, _ = detach_content_flags_tail(merged)
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
        content_flags_context: str,
        length_limit: int,
        output_language: str,
    ):
        if not config.LLM_ENABLED:
            QtWidgets.QMessageBox.warning(self, "注意", "LLMが無効化されています。YAMLで LLM_ENABLED を true にしてください。")
            return
        worker = ChaosMixLLMWorker(
            text=main_text,
            fragments=fragments,
            model=self.combo_llm_model.currentText(),
            video_style=video_style_context,
            content_flags=content_flags_context,
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
        details = extract_sentence_details(result)
        chaos_json = build_movie_json_payload(
            summary=result.strip(),
            details=details,
            scope="single_chaotic_scene",
            key="world_description",
        )
        combined = compose_movie_prompt(chaos_json, movie_tail, flags_tail, options_tail)

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
                "person_present": true,
                "person_count": 2,
                "bgm": true,
                "ambient_sound": true,
                "dialogue": false,
                "on_screen_spoken_dialogue_subtitles": "On-screen subtitles display the spoken dialogue in this video.",
                "on_screen_non_dialogue_text_overlays": "There are on-screen non-dialogue text overlays such as commentary captions, labels, or sound-effect text rendered as part of the image.",
                "planned_cuts": 3,
                "spoken_language": "ja"
            }
        }
        
        narration / bgm / ambient_sound / dialogue は音声要素。
        person_present は「映像内に人物が映っているかどうか」を表す視覚要素フラグ（true/false）。
        person_count は人数指定で、"1+"（1人以上）/ "many"（群衆・5人以上）または具体的な人数（1〜4の整数）を取る。
          - 「(なし)」選択時: person_present=false, person_count は省略
          - 「1人以上」選択時: person_present=true, person_count="1+"
          - 「1人」〜「4人」選択時: person_present=true, person_count=N
          - 「とても多い」選択時: person_present=true, person_count="many"
        on_screen_spoken_dialogue_subtitles は「人物が話しているセリフそのものの字幕（セリフ字幕）が画面に表示されている」ことを、英語の説明文として明示します。
        on_screen_non_dialogue_text_overlays は「ツッコミテロップや解説テキスト、効果音文字など、セリフとは異なる編集用テキストオーバーレイが存在する」ことを、英語の説明文として明示します。
        planned_cuts は「作品全体をおおよそ何カットで構成するか」の目安（1〜6 または "many"）を表します。
        spoken_language は「動画内で想定される主な話し言葉の言語」を表し、"ja" または "en" を取ります。
        (Auto) 選択時や未指定時は planned_cuts / spoken_language フィールド自体を省略します。
        """

        # マスターチェックがOFFなら、フラグの値に関わらず JSON は付与しない
        if not getattr(self, "check_tail_flags_enabled", None) or not self.check_tail_flags_enabled.isChecked():
            return ""

        flags = {
            "narration": bool(self.check_tail_flag_narration.isChecked()),
            "bgm": bool(self.check_tail_flag_bgm.isChecked()),
            "ambient_sound": bool(self.check_tail_flag_ambient.isChecked()),
            "dialogue": bool(self.check_tail_flag_dialogue.isChecked()),
        }

        # 登場人物の人数を person_present / person_count として設定
        # - "(なし)" → person_present: false のみ
        # - "1人以上" → person_present: true, person_count: "1+"
        # - "1人"〜"4人" → person_present: true, person_count: N
        # - "とても多い" → person_present: true, person_count: "many"
        person_combo = getattr(self, "combo_tail_person_count", None)
        if isinstance(person_combo, QtWidgets.QComboBox):
            person_data = person_combo.currentData()
            if person_data is None:
                # (なし) の場合: 人物なし
                flags["person_present"] = False
            elif person_data == "1+":
                # 1人以上の場合: 人数を限定しない
                flags["person_present"] = True
                flags["person_count"] = "1+"
            elif person_data == "many":
                # 群衆など大人数のカット
                flags["person_present"] = True
                flags["person_count"] = "many"
            elif isinstance(person_data, int) and person_data >= 1:
                # 具体的な人数指定
                flags["person_present"] = True
                flags["person_count"] = person_data
            else:
                flags["person_present"] = False
        else:
            flags["person_present"] = False

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
        # 構成カット数 (1〜6 / "many") を planned_cuts として追加 (Auto の場合は省略)
        cut_combo = getattr(self, "combo_tail_cut_count", None)
        if isinstance(cut_combo, QtWidgets.QComboBox):
            data = cut_combo.currentData()
            if isinstance(data, int) and 1 <= data <= 6:
                flags["planned_cuts"] = data
            elif data == "many":
                flags["planned_cuts"] = "many"
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
        if not config.LLM_ENABLED:
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
            main_text, options_tail, movie_tail, _ = prepared
            details = extract_sentence_details(main_text)
            world_json = build_movie_json_payload(
                summary=main_text.strip(),
                details=details,
                scope="single_continuous_world",
                key="world_description",
            )
            flags_tail = self._make_tail_flags_json()
            result = compose_movie_prompt(world_json, movie_tail, flags_tail, options_tail)
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
        main_text, options_tail, movie_tail, content_flags_tail = prepared
        details = extract_sentence_details(main_text)
        video_style_arg, content_flags_arg = self._resolve_style_reflection_contexts(movie_tail, content_flags_tail)
        length_limit = self._get_selected_movie_length_limit()
        output_language = combo_language_code(getattr(self, "combo_movie_output_lang", None))
        self._start_movie_llm_transformation(
            "world",
            main_text,
            details,
            movie_tail,
            options_tail,
            video_style_arg,
            content_flags_arg,
            length_limit,
            output_language=output_language,
        )

    def handle_movie_storyboard(self):
        prepared = self._prepare_movie_prompt_parts()
        if not prepared:
            return
        main_text, options_tail, movie_tail, content_flags_tail = prepared
        details = extract_sentence_details(main_text)
        video_style_arg, content_flags_arg = self._resolve_style_reflection_contexts(movie_tail, content_flags_tail)
        length_limit = self._get_selected_movie_length_limit()
        output_language = combo_language_code(getattr(self, "combo_movie_output_lang", None))
        self._start_movie_llm_transformation(
            "storyboard",
            main_text,
            details,
            movie_tail,
            options_tail,
            video_style_arg,
            content_flags_arg,
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
        
        output_language = combo_language_code(getattr(self, "combo_arrange_output_lang", None))
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
        if not config.LLM_ENABLED:
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
        content_flags_context: str = "",
        length_limit: int = 0,
        output_language: str = "en",
    ):
        if not config.LLM_ENABLED:
            QtWidgets.QMessageBox.warning(self, "注意", "LLMが無効化されています。YAMLで LLM_ENABLED を true にしてください。")
            return
        worker = MovieLLMWorker(
            text=main_text,
            model=self.combo_llm_model.currentText(),
            mode=mode,
            details=details,
            video_style=video_style_context,
            content_flags=content_flags_context,
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
        merged = inherit_options_if_present(self.text_output.toPlainText(), result)
        base_without_flags, _ = detach_content_flags_tail(merged)
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
        details = extract_sentence_details(result)
        world_json = build_movie_json_payload(result, details, scope=scope, key=json_key)
        flags_tail = self._make_tail_flags_json()
        combined = compose_movie_prompt(world_json, movie_tail, flags_tail, options_tail)
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
        return PromptDataMixin._update_exclusion_words(self, new_words)

    # =============================
    # オプション整形系ヘルパー
    # =============================
    def _prepare_movie_prompt_parts(self) -> Optional[Tuple[str, str, str, str]]:
        """動画用整形で共通となる入力分解を行い、メインテキストと末尾要素（末尾2含む）を返す。"""
        src = self.text_output.toPlainText().strip()
        if not src:
            QtWidgets.QMessageBox.warning(self, "注意", "まずプロンプトを生成してください。")
            return None
        # 末尾2(JSONフラグ)はLLM用のメインテキストからは除外する
        core_without_flags, flags_tail = detach_content_flags_tail(src)
        core_without_movie, movie_tail = detach_movie_tail_for_llm(core_without_flags)
        main_text, options_tail, _ = split_prompt_and_options(core_without_movie)
        if not main_text:
            QtWidgets.QMessageBox.warning(self, "注意", "メインテキストが見つかりません。")
            return None
        return main_text, options_tail, movie_tail, flags_tail

    def _resolve_style_reflection_contexts(self, movie_tail: str, content_flags_tail: str) -> Tuple[str, str]:
        """スタイル反映ON時にLLMへ渡す video_style / content_flags を同時に解決する。"""
        checkbox = getattr(self, "check_use_video_style", None)
        if not checkbox or not checkbox.isChecked():
            return "", ""
        video_style = (movie_tail or "").strip()
        content_flags = (content_flags_tail or "").strip()
        if not content_flags:
            content_flags = self._make_tail_flags_json().strip()
        return video_style, content_flags

    def _detach_content_flags_tail(self, text: str) -> Tuple[str, str]:
        return detach_content_flags_tail(text)
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
        return detach_movie_tail_for_llm(text)
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
        return split_prompt_and_options(text)

    def _inherit_options_if_present(self, original_text: str, new_text: str) -> str:
        return inherit_options_if_present(original_text, new_text)

    def _strip_all_options(self, text: str) -> str:
        return strip_all_options(text)

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
        return PromptUIMixin.cycle_font_scale(self)

    def _apply_font_scale(self):
        return PromptUIMixin._apply_font_scale(self)

    def _update_font_button_label(self, label: str):
        return PromptUIMixin._update_font_button_label(self, label)


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
