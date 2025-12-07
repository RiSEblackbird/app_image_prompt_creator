from __future__ import annotations

import csv
import logging
import os
import subprocess
import sys
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

from PySide6 import QtCore, QtWidgets

from modules import config
from modules.export_loader import load_export_module
from modules.logging_utils import get_exception_trace, log_structured
from modules.prompt_data import (
    AttributeDetail,
    AttributeType,
    load_arrange_presets_from_yaml,
    load_exclusion_words,
    load_tail_presets_from_yaml,
)


MJImage = load_export_module()


class PromptDataMixin:
    """DB・CSV・プリセットの読み書きや監視を担当するミックスイン。"""

    def _get_db_path_or_warn(self) -> Optional[Path]:
        """DBパスの存在をチェックし、欠損時はセットアップ手順を案内する。"""

        db_path = Path(config.DEFAULT_DB_PATH)
        log_structured(logging.INFO, "db_path_check", {"db_path": str(db_path)})
        if db_path.exists():
            return db_path
        self._show_db_missing_dialog(db_path)
        return None

    def _connect_with_foreign_keys(self, db_path: Path) -> sqlite3.Connection:
        """外部キー制約を確実に有効化した SQLite 接続を返す。"""

        log_structured(logging.INFO, "sqlite_connect_attempt", {"db_path": str(db_path)})
        conn = sqlite3.connect(db_path)
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

    def _on_tail_media_type_change(self, value: str):
        self._update_tail_free_text_choices(reset_selection=True)
        self.auto_update()

    def _update_tail_free_text_choices(self, reset_selection: bool):
        """メディア種別に応じた末尾プリセット候補をコンボボックスへ反映する。"""

        media_type = self.combo_tail_media_type.currentText() or config.DEFAULT_TAIL_MEDIA_TYPE
        presets = config.TAIL_PRESETS.get(media_type, config.TAIL_PRESETS.get(config.DEFAULT_TAIL_MEDIA_TYPE, []))

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
        attribute_labels = [row[1].replace('"', "'") if row[1] else "attribute" for row in samples]
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

                        cursor.execute("INSERT INTO prompts (content) VALUES (?)", (content,))
                        prompt_id = cursor.lastrowid
                        for attribute_detail_id in attribute_detail_ids:
                            cursor.execute(
                                "INSERT INTO prompt_attribute_details (prompt_id, attribute_detail_id) VALUES (?, ?)",
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
        export_path = config.SCRIPT_DIR / f"failed_csv_rows_{timestamp}.csv"
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
                subprocess.Popen(["notepad.exe", config.EXCLUSION_CSV])
            elif sys.platform == "darwin":
                subprocess.call(["open", "-a", "TextEdit", config.EXCLUSION_CSV])
            else:
                subprocess.call(["xdg-open", config.EXCLUSION_CSV])
        except Exception as error:
            QtWidgets.QMessageBox.critical(self, "エラー", f"CSVファイルを開けませんでした: {error}")

    def _setup_tail_presets_watcher(self) -> None:
        """末尾プリセット YAML の変更を監視し、プルダウン候補へ自動反映する。"""

        path = Path(config.TAIL_PRESETS_YAML)
        if not path.exists():
            return

        watcher = QtCore.QFileSystemWatcher(self)
        watcher.addPath(str(path))
        watcher.fileChanged.connect(self._on_tail_presets_file_changed)
        self._tail_presets_watcher = watcher

    @QtCore.Slot(str)
    def _on_tail_presets_file_changed(self, changed_path: str) -> None:
        """YAML 編集完了後にプリセットを再読込し、現在のコンボボックスに反映する。"""

        QtCore.QTimer.singleShot(300, self._reload_tail_presets_and_refresh_ui)

    def _reload_tail_presets_and_refresh_ui(self) -> None:
        """tail_presets.yaml を再読込し、media_type / tail_free 両コンボを最新状態に更新する。"""

        previous_media_type = self.combo_tail_media_type.currentText() or config.DEFAULT_TAIL_MEDIA_TYPE
        previous_prompt = self._resolve_tail_free_prompt()

        load_tail_presets_from_yaml()

        media_types = list(config.TAIL_PRESETS.keys())
        if not media_types:
            return

        self.combo_tail_media_type.blockSignals(True)
        self.combo_tail_media_type.clear()
        self.combo_tail_media_type.addItems(media_types)

        if previous_media_type in media_types:
            self.combo_tail_media_type.setCurrentText(previous_media_type)
        elif config.DEFAULT_TAIL_MEDIA_TYPE in media_types:
            self.combo_tail_media_type.setCurrentText(config.DEFAULT_TAIL_MEDIA_TYPE)
        else:
            self.combo_tail_media_type.setCurrentIndex(0)
        self.combo_tail_media_type.blockSignals(False)

        self._update_tail_free_text_choices(reset_selection=True)
        if previous_prompt:
            for i in range(self.combo_tail_free.count()):
                data = self.combo_tail_free.itemData(i)
                if isinstance(data, str) and data == previous_prompt:
                    self.combo_tail_free.setCurrentIndex(i)
                    break

    def _setup_arrange_presets_watcher(self) -> None:
        """アレンジプリセット YAML の変更を監視し、内部定義を自動更新する。"""

        path = Path(config.ARRANGE_PRESETS_YAML)
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
        for preset in config.ARRANGE_PRESETS:
            self.combo_arrange_preset.addItem(preset["label"], userData=preset)

        if current:
            index = self.combo_arrange_preset.findText(current)
            if index >= 0:
                self.combo_arrange_preset.setCurrentIndex(index)
        self.combo_arrange_preset.blockSignals(False)
        self._on_arrange_preset_change(self.combo_arrange_preset.currentText())

    def _update_exclusion_words(self, new_words: List[str]):
        """除外語句CSVを更新し、UIの選択肢をリロードする。"""
        updated_words: List[str] = []
        try:
            with open(config.EXCLUSION_CSV, "w", encoding="utf-8", newline="") as file:
                writer = csv.writer(file, quotechar='"', quoting=csv.QUOTE_ALL)
                for word in new_words:
                    new_phrase = word.strip()
                    if not new_phrase:
                        continue
                    writer.writerow([new_phrase])
                updated_words = load_exclusion_words()
        except OSError as error:
            QtWidgets.QMessageBox.critical(self, "書き込みエラー", f"除外語句の保存に失敗しました: {error}")
            return

        self.combo_exclusion.clear()
        self.combo_exclusion.addItems(updated_words)
        if new_words:
            self.combo_exclusion.setCurrentText(new_words[-1])
