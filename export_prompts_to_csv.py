"""DB内容をCSVにエクスポートするための補助モジュール。

MJImage クラスの run() は Tk / Qt 双方のGUIから呼び出され、
現在の prompts テーブルと attribute_details テーブルの関連付けを
確認用 CSV に書き出す。設定ファイルが無い環境でも動作を継続し、
利用者に復旧手順を知らせるダイアログを必ず出す。"""
from __future__ import annotations

import csv
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, Tuple

import tkinter as tk
from tkinter import messagebox
import yaml

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_SETTINGS_PATH = SCRIPT_DIR / "desktop_gui_settings.yaml"
# 既定のDBパスは設定ファイルが無い場合のフェイルセーフとして利用する。
FALLBACK_DB_PATH = SCRIPT_DIR / "app_image_prompt_creator" / "image_prompt_parts.db"


def _load_settings(settings_path: Path) -> Dict:
    """YAML設定を読み込み、無い場合は空dictで返す。

    将来的な設定キー追加にも対応できるよう、存在しない場合は例外を
    投げず空dictを返して呼び出し側でフォールバックする。
    """

    if not settings_path.exists():
        logging.warning("設定ファイルが見つかりません。フォールバック値を使用します。")
        return {}
    with settings_path.open("r", encoding="utf-8") as fp:
        return yaml.safe_load(fp) or {}


def _pick_db_path(settings: Dict) -> Path:
    """設定から DB パスを取り出し、無い場合はフォールバックを返す。"""

    app_settings = settings.get("app_image_prompt_creator", {}) if settings else {}
    configured = app_settings.get("DEFAULT_DB_PATH")
    if configured:
        return Path(configured)
    return FALLBACK_DB_PATH


def _safe_message(title: str, body: str, kind: str = "info") -> None:
    """Tk を利用したメッセージ表示。GUIが使えない環境でもログに残す。"""

    root = None
    try:
        root = tk.Tk()
        root.withdraw()
        if kind == "error":
            messagebox.showerror(title, body)
        elif kind == "warning":
            messagebox.showwarning(title, body)
        else:
            messagebox.showinfo(title, body)
    except Exception as exc:  # pragma: no cover - GUIが無いCI環境向け
        logging.log(logging.ERROR if kind == "error" else logging.INFO, f"{title}: {body} ({exc})")
    finally:
        if root is not None:
            root.destroy()


def _ensure_parent_dir(path: Path) -> None:
    """エクスポート先ディレクトリを事前に作成する。"""

    path.parent.mkdir(parents=True, exist_ok=True)


class MJImage:
    """prompts と attribute_details をCSVへ出力するユーティリティ。"""

    def __init__(self, settings_path: Path | str = DEFAULT_SETTINGS_PATH) -> None:
        self.settings_path = Path(settings_path)
        self.settings = _load_settings(self.settings_path)

    def _fetch_prompt_rows(self, cursor: sqlite3.Cursor) -> Iterable[Tuple]:
        """DBからプロンプトと属性をまとめて取得する。"""

        cursor.execute(
            """
            SELECT
                p.id,
                p.content,
                COALESCE(GROUP_CONCAT(ad.id, '|'), '') AS attribute_ids,
                COALESCE(GROUP_CONCAT(ad.description, '|'), '') AS attribute_descriptions
            FROM prompts p
            LEFT JOIN prompt_attribute_details pad ON p.id = pad.prompt_id
            LEFT JOIN attribute_details ad ON pad.attribute_detail_id = ad.id
            GROUP BY p.id, p.content
            ORDER BY p.id
            """
        )
        return cursor.fetchall()

    def _build_export_path(self) -> Path:
        """タイムスタンプ付きのエクスポート先パスを返す。"""

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return SCRIPT_DIR / f"prompts_export_{timestamp}.csv"

    def _export(self, db_path: Path) -> Path:
        """DBを開いてCSVを書き出すメイン処理。"""

        export_path = self._build_export_path()
        _ensure_parent_dir(export_path)

        with sqlite3.connect(db_path) as conn:
            conn.execute("PRAGMA foreign_keys = ON;")
            cursor = conn.cursor()
            rows = self._fetch_prompt_rows(cursor)

        with export_path.open("w", encoding="utf-8", newline="") as fp:
            writer = csv.writer(fp)
            writer.writerow(["prompt_id", "content", "attribute_detail_ids", "attribute_descriptions"])
            for row in rows:
                writer.writerow(row)

        return export_path

    def run(self) -> None:
        """エクスポート処理を実行し、結果をダイアログで案内する。"""

        db_path = _pick_db_path(self.settings)
        if not db_path.exists():
            instruction = (
                "export_prompts_to_csv.py から参照するDBが見つかりません。\n"
                f"想定パス: {db_path}\n\n"
                "復旧手順:\n"
                "1) `python export_prompts_to_csv.py` を実行する前に DB を配置する\n"
                "2) desktop_gui_settings.yaml の DEFAULT_DB_PATH を正しい場所に更新する\n"
                "3) README のセットアップ手順に沿って DB を初期化する"
            )
            _safe_message("DB未検出", instruction, kind="error")
            return

        try:
            export_path = self._export(db_path)
        except sqlite3.Error as exc:
            _safe_message(
                "CSV出力失敗",
                f"DB読み取りまたはCSV書き込みに失敗しました。\n{exc}",
                kind="error",
            )
            logging.exception("CSVエクスポートに失敗")
            return

        _safe_message(
            "CSV出力完了",
            (
                "DB内容を確認用CSVに出力しました。\n"
                f"出力先: {export_path}\n\n"
                "CSVの各行には prompt_id と content に加え、関連する attribute_detail の"
                "ID と説明を '|' 区切りでまとめています。"
            ),
            kind="info",
        )


if __name__ == "__main__":
    MJImage().run()
