"""ストーリーボード機能とSoraキャラクター一覧ダイアログを提供するモジュール。"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import asdict
from typing import Dict, List, Optional, Tuple

from PySide6 import QtCore, QtGui, QtWidgets

from . import config
from .prompt_data import SoraCharacter, StoryboardCut, load_sora_characters


def extract_metadata_from_prompt(text: str) -> Tuple[Optional[dict], Optional[dict], str]:
    """プロンプトテキストから video_style と content_flags を抽出する。

    Args:
        text: 入力テキスト（プロンプト全文）

    Returns:
        (video_style, content_flags, remaining_text) のタプル
        - video_style: {"video_style": {...}} の中身、または None
        - content_flags: {"content_flags": {...}} の中身、または None
        - remaining_text: メタデータを除去した残りのテキスト
    """
    video_style = None
    content_flags = None
    remaining = text

    # video_style を抽出
    # {"video_style": {...}} のパターンを探す
    vs_pattern = r'\{[^{}]*"video_style"\s*:\s*\{[^{}]*\}[^{}]*\}'
    vs_match = re.search(vs_pattern, remaining)
    if vs_match:
        try:
            vs_json = json.loads(vs_match.group())
            video_style = vs_json.get("video_style")
            remaining = remaining[:vs_match.start()] + remaining[vs_match.end():]
        except json.JSONDecodeError:
            pass

    # content_flags を抽出
    # {"content_flags": {...}} のパターンを探す
    cf_pattern = r'\{[^{}]*"content_flags"\s*:\s*\{[^{}]*\}[^{}]*\}'
    cf_match = re.search(cf_pattern, remaining)
    if cf_match:
        try:
            cf_json = json.loads(cf_match.group())
            content_flags = cf_json.get("content_flags")
            remaining = remaining[:cf_match.start()] + remaining[cf_match.end():]
        except json.JSONDecodeError:
            pass

    # 連続する空白を正規化
    remaining = " ".join(remaining.split()).strip()

    return video_style, content_flags, remaining


class SoraCharacterListDialog(QtWidgets.QDialog):
    """Soraキャラクター一覧を表示し、各値をコピーできるダイアログ。

    テーブル形式でキャラクター一覧を表示し、ID/名前/三人称それぞれに
    コピーボタンを配置して、クリップボードへのコピーを容易にする。
    """

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("Sora キャラクター一覧")
        self.setMinimumSize(700, 400)
        self.setModal(True)
        self._characters: List[SoraCharacter] = []
        self._build_ui()
        self._load_characters()

    def _build_ui(self):
        """UIコンポーネントを構築する。"""
        layout = QtWidgets.QVBoxLayout(self)

        # テーブル
        self.table = QtWidgets.QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(["ID", "名前", "3人称", "", "", ""])
        self.table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QtWidgets.QHeaderView.Fixed)
        self.table.horizontalHeader().setSectionResizeMode(4, QtWidgets.QHeaderView.Fixed)
        self.table.horizontalHeader().setSectionResizeMode(5, QtWidgets.QHeaderView.Fixed)
        self.table.setColumnWidth(3, 50)
        self.table.setColumnWidth(4, 50)
        self.table.setColumnWidth(5, 50)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(True)
        layout.addWidget(self.table)

        # ファイルパス表示
        self.file_label = QtWidgets.QLabel(f"ファイル: {config.SORA_CHARACTERS_YAML}")
        self.file_label.setStyleSheet("color: #666;")
        layout.addWidget(self.file_label)

        # ボタン行
        btn_layout = QtWidgets.QHBoxLayout()
        open_btn = QtWidgets.QPushButton("ファイルを開く")
        open_btn.setToolTip("OSのデフォルトエディタでYAMLファイルを開きます")
        open_btn.clicked.connect(self._open_file)
        btn_layout.addWidget(open_btn)

        reload_btn = QtWidgets.QPushButton("再読み込み")
        reload_btn.setToolTip("YAMLファイルを再読み込みしてリストを更新します")
        reload_btn.clicked.connect(self._load_characters)
        btn_layout.addWidget(reload_btn)

        btn_layout.addStretch()

        close_btn = QtWidgets.QPushButton("閉じる")
        close_btn.clicked.connect(self.accept)
        btn_layout.addWidget(close_btn)

        layout.addLayout(btn_layout)

    def _load_characters(self):
        """キャラクターデータをYAMLから読み込み、テーブルに表示する。"""
        self._characters = load_sora_characters()
        self.table.setRowCount(len(self._characters))

        for row, char in enumerate(self._characters):
            # データ列
            id_item = QtWidgets.QTableWidgetItem(char.id)
            id_item.setToolTip(char.id)
            self.table.setItem(row, 0, id_item)

            name_item = QtWidgets.QTableWidgetItem(char.name)
            name_item.setToolTip(char.name)
            self.table.setItem(row, 1, name_item)

            pronoun_item = QtWidgets.QTableWidgetItem(char.pronoun_3rd)
            pronoun_item.setToolTip(char.pronoun_3rd)
            self.table.setItem(row, 2, pronoun_item)

            # コピーボタン
            self._add_copy_button(row, 3, char.id, "ID")
            self._add_copy_button(row, 4, char.name, "名")
            self._add_copy_button(row, 5, char.pronoun_3rd, "代")

        if not self._characters:
            self.table.setRowCount(1)
            empty_item = QtWidgets.QTableWidgetItem("（キャラクターが登録されていません）")
            empty_item.setForeground(QtGui.QColor("#999"))
            self.table.setItem(0, 0, empty_item)
            self.table.setSpan(0, 0, 1, 6)

    def _add_copy_button(self, row: int, col: int, value: str, label: str):
        """テーブルセルにコピーボタンを追加する。"""
        btn = QtWidgets.QPushButton(label)
        btn.setFixedWidth(45)
        btn.setToolTip(f"「{value}」をコピー")
        btn.clicked.connect(lambda checked=False, v=value: self._copy_to_clipboard(v))
        self.table.setCellWidget(row, col, btn)

    def _copy_to_clipboard(self, text: str):
        """テキストをクリップボードにコピーし、ステータス表示する。"""
        QtGui.QGuiApplication.clipboard().setText(text)
        parent = self.parent()
        if parent and hasattr(parent, "statusBar"):
            parent.statusBar().showMessage(f"コピーしました: {text}", 2000)

    def _open_file(self):
        """OSのデフォルトエディタでYAMLファイルを開く。"""
        path = config.SORA_CHARACTERS_YAML
        try:
            if sys.platform == "win32":
                os.startfile(path)
            elif sys.platform == "darwin":
                subprocess.run(["open", path], check=False)
            else:
                subprocess.run(["xdg-open", path], check=False)
        except Exception as e:
            QtWidgets.QMessageBox.warning(
                self,
                "ファイルを開けません",
                f"ファイルを開く際にエラーが発生しました:\n{e}\n\nパス: {path}",
            )


def _extract_scene_essence(description: str, max_len: int = 60) -> str:
    """カット説明から場面の本質を抽出する。

    Args:
        description: カットの説明文
        max_len: 最大文字数

    Returns:
        抽出された場面の本質（簡潔な形式）
    """
    # 最初の文を取得
    core = description.split(".")[0].strip()

    # 長すぎる場合は句読点や接続詞で切る
    if len(core) > max_len:
        for delim in [",", " and ", " while ", " as ", " with "]:
            if delim in core:
                core = core.split(delim)[0].strip()
                break
        if len(core) > max_len:
            core = core[:max_len - 3] + "..."

    return core


def _lowercase_first(text: str) -> str:
    """先頭が通常の文章開始なら小文字化する。

    ただし、固有名詞の可能性がある場合（2文字目以降が小文字）はそのまま。
    """
    if not text:
        return text
    # "A woman" -> "a woman", "She" -> "she", but "Tokyo" -> "Tokyo"
    if len(text) > 1 and text[0].isupper() and text[1].islower():
        return text[0].lower() + text[1:]
    return text


def _build_continuity_bridge(prev_description: str, current_description: str) -> str:
    """直前のカットから現在のカットへの連続性ブリッジを生成する。

    前のカットの具体的な場面要素を参照して、
    世界観の一貫性と滑らかな遷移を実現する指示を生成する。

    Args:
        prev_description: 直前のカットの説明
        current_description: 現在のカットの説明

    Returns:
        連続性を強化した説明文
    """
    prev_essence = _extract_scene_essence(prev_description)

    # 現在の説明の先頭を調整（接続詞の後なので小文字が自然）
    current_adjusted = _lowercase_first(current_description)

    # 前のシーンの要素を明示的に引き継ぐ形式
    # 動画生成モデルが前後の繋がりを理解しやすい構造
    bridge = (
        f"(Following: {prev_essence}) "
        f"Seamlessly continuing in the same setting, {current_adjusted}"
    )
    return bridge


def build_storyboard_json(
    cuts: List[StoryboardCut],
    total_duration_sec: float,
    template_id: str = "none",
    video_style: Optional[dict] = None,
    content_flags: Optional[dict] = None,
    continuity_enhanced: bool = False,
) -> str:
    """ストーリーボードのカットリストをJSON形式に変換する。

    video_style と content_flags はストーリーボードと並列に配置される。
    これにより、各カットの説明に冗長な情報を含めずに済む。

    Args:
        cuts: カットのリスト
        total_duration_sec: 総尺（秒）
        template_id: 使用したテンプレートID
        video_style: 動画スタイル定義（省略可）
        content_flags: コンテンツフラグ（省略可）
        continuity_enhanced: 連続性強化モード（有効時、前のカットを参照した遷移指示を追加）

    Returns:
        JSON文字列
    """
    cuts_data = []
    for i, cut in enumerate(cuts):
        description = cut.description

        # 連続性強化モード: 2番目以降のカット（かつプレースホルダでない）に適用
        if continuity_enhanced and i > 0 and not cut.is_image_placeholder:
            prev_cut = cuts[i - 1]
            # 前のカットがプレースホルダでない場合のみブリッジ生成
            if not prev_cut.is_image_placeholder:
                # 既にブリッジが含まれている場合はスキップ
                if not description.startswith("(Following:"):
                    description = _build_continuity_bridge(prev_cut.description, description)

        cut_dict = {
            "index": cut.index,
            "start_sec": cut.start_sec,
            "duration_sec": cut.duration_sec,
            "description": description,
        }
        if cut.camera_work and cut.camera_work != "static":
            cut_dict["camera_work"] = cut.camera_work
        if cut.characters:
            cut_dict["characters"] = cut.characters
        if cut.is_image_placeholder:
            cut_dict["is_image_placeholder"] = True
        cuts_data.append(cut_dict)

    # ルートレベルのペイロードを構築
    # video_style と content_flags はストーリーボードと並列に配置
    payload = {}

    if video_style:
        payload["video_style"] = video_style

    if content_flags:
        payload["content_flags"] = content_flags

    storyboard_data = {
        "total_duration_sec": total_duration_sec,
        "template": template_id,
        "cuts": cuts_data,
    }
    # 連続性強化フラグをストーリーボードに含める
    if continuity_enhanced:
        storyboard_data["continuity_enhanced"] = True

    payload["storyboard"] = storyboard_data
    return json.dumps(payload, ensure_ascii=False, indent=2)


def create_cuts_from_template(
    template_id: str,
    total_duration_sec: float,
    cut_count: int = 3,
) -> List[StoryboardCut]:
    """テンプレートと総尺からカットリストを生成する。

    Args:
        template_id: テンプレートID（config.STORYBOARD_TEMPLATES のキー）
        total_duration_sec: 総尺（秒）
        cut_count: カット数（テンプレートによっては無視される）

    Returns:
        StoryboardCutのリスト
    """
    template = config.STORYBOARD_TEMPLATES.get(template_id)
    if not template:
        template = config.STORYBOARD_TEMPLATES["none"]

    preset_cuts = template.get("preset_cuts")
    weight_distribution = template.get("weight_distribution")

    # preset_cuts が定義されている場合（画像呪縛解除テンプレートなど）
    if preset_cuts:
        cuts = []
        remaining_duration = total_duration_sec
        fixed_duration_sum = 0.0

        # 固定尺のカットを先に処理
        for i, preset in enumerate(preset_cuts):
            duration = preset.get("duration_sec")
            if duration is not None:
                fixed_duration_sum += duration

        # 可変尺のカットに残りを割り当て
        variable_count = sum(1 for p in preset_cuts if p.get("duration_sec") is None)
        variable_duration = max(0, total_duration_sec - fixed_duration_sum)
        if variable_count > 0:
            per_variable = variable_duration / variable_count
        else:
            per_variable = 0

        current_time = 0.0
        for i, preset in enumerate(preset_cuts):
            duration = preset.get("duration_sec")
            if duration is None:
                duration = per_variable

            cut = StoryboardCut(
                index=i,
                start_sec=round(current_time, 2),
                duration_sec=round(duration, 2),
                description=preset.get("description", ""),
                camera_work="static",
                characters=[],
                is_image_placeholder=preset.get("is_image_placeholder", False),
            )
            cuts.append(cut)
            current_time += duration

        return cuts

    # weight_distribution が定義されている場合
    if weight_distribution:
        actual_cut_count = len(weight_distribution)
        cuts = []
        current_time = 0.0

        for i, weight in enumerate(weight_distribution):
            duration = total_duration_sec * weight
            cut = StoryboardCut(
                index=i,
                start_sec=round(current_time, 2),
                duration_sec=round(duration, 2),
                description="",
                camera_work="static",
                characters=[],
                is_image_placeholder=False,
            )
            cuts.append(cut)
            current_time += duration

        return cuts

    # デフォルト: 均等配分
    cuts = []
    duration_per_cut = total_duration_sec / max(1, cut_count)
    current_time = 0.0

    for i in range(cut_count):
        cut = StoryboardCut(
            index=i,
            start_sec=round(current_time, 2),
            duration_sec=round(duration_per_cut, 2),
            description="",
            camera_work="static",
            characters=[],
            is_image_placeholder=False,
        )
        cuts.append(cut)
        current_time += duration_per_cut

    return cuts
