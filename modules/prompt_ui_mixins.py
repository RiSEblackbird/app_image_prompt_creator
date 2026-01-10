from __future__ import annotations

import json
import re
from typing import Iterable, List

from PySide6 import QtCore, QtGui, QtWidgets

from modules import config
from modules.prompt_data import (
    StoryboardCut,
    load_exclusion_words,
    load_sora_characters,
    save_sora_characters,
)
from modules.ui_helpers import create_language_combo
from modules.storyboard import (
    SoraCharacterListDialog,
    SoraCharacterRegisterDialog,
    build_storyboard_json,
    create_cuts_from_template,
    extract_metadata_from_prompt,
)


class PromptUIMixin:
    """UI構築とフォント制御を担当するミックスイン。"""

    def _build_ui(self):
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)

        main_layout = QtWidgets.QVBoxLayout(central)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)

        self._build_header(main_layout)

        splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        main_layout.addWidget(splitter, 1)

        left_widget = QtWidgets.QWidget()
        left_layout = QtWidgets.QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 5, 0)
        left_layout.setSpacing(10)
        self._build_left_pane_content(left_layout)
        splitter.addWidget(left_widget)

        right_widget = QtWidgets.QWidget()
        right_layout = QtWidgets.QVBoxLayout(right_widget)
        right_layout.setContentsMargins(5, 0, 0, 0)
        right_layout.setSpacing(10)
        self._build_right_pane_content(right_layout)
        splitter.addWidget(right_widget)

        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 6)

        self.status_bar = self.statusBar()
        self.loading_progress = QtWidgets.QProgressBar()
        self.loading_progress.setRange(0, 0)
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

        header_layout.addWidget(QtWidgets.QLabel("LLMモデル:"))
        self.combo_llm_model = QtWidgets.QComboBox()
        self.combo_llm_model.addItems(self.available_model_choices)
        header_layout.addWidget(self.combo_llm_model)
        self.label_current_model = QtWidgets.QLabel(f"選択中: {self.combo_llm_model.currentText()}")
        header_layout.addWidget(self.label_current_model)
        self.combo_llm_model.currentTextChanged.connect(self._on_model_change)
        self._ensure_model_choice_alignment()

        header_layout.addStretch(1)

        self.button_font_scale = QtWidgets.QPushButton("フォント: 標準")
        self.button_font_scale.setToolTip("UI全体のフォントサイズを段階的に切り替えます。")
        self.button_font_scale.clicked.connect(self.cycle_font_scale)
        header_layout.addWidget(self.button_font_scale)

    def _build_left_pane_content(self, layout):
        basic_group = QtWidgets.QGroupBox("基本設定")
        basic_grid = QtWidgets.QGridLayout(basic_group)

        basic_grid.addWidget(QtWidgets.QLabel("行数:"), 0, 0)
        self.spin_row_num = QtWidgets.QSpinBox()
        self.spin_row_num.setMinimum(1)
        self.spin_row_num.setMaximum(999)
        self.spin_row_num.setValue(config.DEFAULT_ROW_NUM)
        basic_grid.addWidget(self.spin_row_num, 0, 1)

        self.check_autofix = QtWidgets.QCheckBox("自動反映")
        basic_grid.addWidget(self.check_autofix, 0, 2)

        self.check_dedup = QtWidgets.QCheckBox("重複除外")
        self.check_dedup.setChecked(bool(config.DEDUPLICATE_PROMPTS))
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

        if not config.LLM_ENABLED:
            self.radio_mode_llm.setEnabled(False)
            self.radio_mode_llm.setToolTip(
                "LLM生成を利用するには desktop_gui_settings.yaml の LLM_ENABLED を true に設定してください。"
            )

        basic_grid.addWidget(QtWidgets.QLabel("カオス度(LLM):"), 3, 0)
        self._llm_chaos_container = QtWidgets.QWidget()
        chaos_layout = QtWidgets.QHBoxLayout(self._llm_chaos_container)
        chaos_layout.setContentsMargins(0, 0, 0, 0)
        self.slider_llm_chaos = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.slider_llm_chaos.setRange(1, 10)
        self.slider_llm_chaos.setTickPosition(QtWidgets.QSlider.TicksBelow)
        self.slider_llm_chaos.setTickInterval(1)
        self.slider_llm_chaos.setValue(1)
        self.slider_llm_chaos.setToolTip(
            "LLM生成時の創造性（カオス度）を1〜10で指定します。1は安定寄り、5で十分強い変化、10で最大限カオスなバリエーションを許容します。"
        )
        self.label_llm_chaos_val = QtWidgets.QLabel("1 (安定)")
        self.slider_llm_chaos.valueChanged.connect(self._on_llm_chaos_change)
        chaos_layout.addWidget(self.slider_llm_chaos, 1)
        chaos_layout.addWidget(self.label_llm_chaos_val)
        self._llm_chaos_container.setVisible(False)
        basic_grid.addWidget(self._llm_chaos_container, 3, 1, 1, 2)

        basic_grid.addWidget(QtWidgets.QLabel("LLM生成言語:"), 4, 0)
        self.combo_llm_output_lang = QtWidgets.QComboBox()
        self.combo_llm_output_lang.addItem("英語", userData="en")
        self.combo_llm_output_lang.addItem("日本語", userData="ja")
        self.combo_llm_output_lang.setCurrentIndex(0)
        self.combo_llm_output_lang.setToolTip(
            "通常生成の LLMモードで生成されるフラグメント（1行ごとの短文）の言語を指定します。"
        )
        basic_grid.addWidget(self.combo_llm_output_lang, 4, 1, 1, 2)

        self.radio_mode_db.toggled.connect(self._update_generate_mode_ui)
        self.radio_mode_llm.toggled.connect(self._update_generate_mode_ui)
        self._update_generate_mode_ui()

        layout.addWidget(basic_group)

        attr_group = QtWidgets.QGroupBox("属性選択")
        attr_layout = QtWidgets.QVBoxLayout(attr_group)
        self.attribute_area = QtWidgets.QScrollArea()
        self.attribute_area.setWidgetResizable(True)
        self.attribute_container = QtWidgets.QWidget()
        self.attribute_layout = QtWidgets.QFormLayout(self.attribute_container)
        self.attribute_area.setWidget(self.attribute_container)
        attr_layout.addWidget(self.attribute_area)
        layout.addWidget(attr_group, 1)

        tabs = QtWidgets.QTabWidget()
        layout.addWidget(tabs)

        style_tab = QtWidgets.QWidget()
        style_layout = QtWidgets.QVBoxLayout(style_tab)
        style_layout.setContentsMargins(5, 5, 5, 5)

        tail_form = QtWidgets.QFormLayout()
        self.combo_tail_media_type = QtWidgets.QComboBox()
        self.combo_tail_media_type.addItems(list(config.TAIL_PRESETS.keys()))
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

        tail2_group = QtWidgets.QGroupBox("末尾2 (JSONフラグ)")
        tail2_layout = QtWidgets.QVBoxLayout(tail2_group)

        self.check_tail_flags_enabled = QtWidgets.QCheckBox("末尾2を反映")
        self.check_tail_flags_enabled.setToolTip(
            "ONにすると content_flags JSON を末尾に付与します。すべてのフラグが OFF でも JSON 自体が付きます。"
        )
        self.check_tail_flags_enabled.stateChanged.connect(self.auto_update)
        tail2_layout.addWidget(self.check_tail_flags_enabled)

        flags_row = QtWidgets.QHBoxLayout()
        self.check_tail_flag_narration = QtWidgets.QCheckBox("ナレーション")
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
            self.check_tail_flag_bgm,
            self.check_tail_flag_ambient,
            self.check_tail_flag_dialogue,
            self.check_tail_flag_dialogue_subtitle,
            self.check_tail_flag_telop,
        ):
            chk.stateChanged.connect(self.auto_update)
            flags_row.addWidget(chk)
        tail2_layout.addLayout(flags_row)

        # 登場人物（動画用）
        # person_present/person_count を末尾2(content_flags)へ反映するための入力UI。
        person_row = QtWidgets.QHBoxLayout()
        person_row.addWidget(QtWidgets.QLabel("登場人物(動画用):"))
        self.combo_tail_person_count = QtWidgets.QComboBox()
        self.combo_tail_person_count.addItem("(なし)", userData=None)
        self.combo_tail_person_count.addItem("1人以上", userData="1+")
        for i in range(1, 5):
            self.combo_tail_person_count.addItem(f"{i}人", userData=i)
        self.combo_tail_person_count.addItem("とても多い", userData="many")
        self.combo_tail_person_count.setToolTip(
            "映像内に人物が映っているかどうかと、おおよその人数を指定します。"
            "「とても多い」は person_count=\"many\"（群衆・大人数）として JSON に反映されます。"
        )
        self.combo_tail_person_count.currentIndexChanged.connect(self.auto_update)
        person_row.addWidget(self.combo_tail_person_count)
        person_row.addStretch(1)
        tail2_layout.addLayout(person_row)

        cuts_row = QtWidgets.QHBoxLayout()
        cuts_row.addWidget(QtWidgets.QLabel("カット数(動画用):"))
        self.combo_tail_cut_count = QtWidgets.QComboBox()
        # planned_cuts は末尾2(content_flags)へ入る値で、1〜6 または "many"（多数カット）を取りうる。
        # QComboBox は addItems() だと userData が入らないため、表示文字列と JSON 用の値を明示的に紐付ける。
        self.combo_tail_cut_count.addItem("未指定", userData=None)
        for i in range(1, 7):
            self.combo_tail_cut_count.addItem(str(i), userData=i)
        self.combo_tail_cut_count.addItem("とても多い", userData="many")
        self.combo_tail_cut_count.setToolTip(
            "作品全体の構成カット数の目安を指定します。"
            "「とても多い」は planned_cuts=\"many\"（多数カット）として JSON に反映されます。"
        )
        self.combo_tail_cut_count.currentIndexChanged.connect(self.auto_update)
        cuts_row.addWidget(self.combo_tail_cut_count)
        cuts_row.addStretch(1)
        tail2_layout.addLayout(cuts_row)

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

        mj_group = QtWidgets.QGroupBox("オプション")
        mj_grid = QtWidgets.QGridLayout(mj_group)
        self.combo_tail_ar = self._add_option_cell(mj_grid, 0, "ar オプション:", config.AR_OPTIONS)
        self.combo_tail_s = self._add_option_cell(mj_grid, 1, "s オプション:", config.S_OPTIONS)
        self.combo_tail_chaos = self._add_option_cell(mj_grid, 2, "chaos オプション:", config.CHAOS_OPTIONS)
        self.combo_tail_q = self._add_option_cell(mj_grid, 3, "q オプション:", config.Q_OPTIONS)
        self.combo_tail_weird = self._add_option_cell(mj_grid, 4, "weird オプション:", config.WEIRD_OPTIONS)
        style_layout.addWidget(mj_group)

        style_layout.addStretch(1)
        tabs.addTab(style_tab, "スタイル・オプション")

        data_tab = QtWidgets.QWidget()
        data_layout = QtWidgets.QVBoxLayout(data_tab)
        data_layout.setContentsMargins(5, 5, 5, 5)

        excl_group = QtWidgets.QGroupBox("除外設定")
        excl_layout = QtWidgets.QVBoxLayout(excl_group)
        excl_row = QtWidgets.QHBoxLayout()
        excl_row.addWidget(QtWidgets.QLabel(config.LABEL_EXCLUSION_WORDS))
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
        """グリッドレイアウトにオプション項目を追加するヘルパー。"""
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
        self.text_output = QtWidgets.QTextEdit()
        self.text_output.setAcceptRichText(False)
        self.text_output.setPlaceholderText("ここに生成結果が表示されます")
        layout.addWidget(self.text_output, 1)

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

        tools_tabs = QtWidgets.QTabWidget()
        tools_tabs.setMinimumHeight(320)
        layout.addWidget(tools_tabs)

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
        llm_row.addWidget(self.check_use_video_style)

        llm_row.addWidget(QtWidgets.QLabel("出力言語:"))
        self.combo_movie_output_lang = create_language_combo()
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

        adjust_tab = QtWidgets.QWidget()
        adjust_layout = QtWidgets.QVBoxLayout(adjust_tab)
        adjust_layout.setContentsMargins(5, 5, 5, 5)

        length_group = QtWidgets.QHBoxLayout()
        length_group.addWidget(QtWidgets.QLabel("文字数目標:"))
        self.combo_length_adjust = QtWidgets.QComboBox()
        self.combo_length_adjust.addItems(["半分", "2割減", "同程度", "2割増", "倍"])
        self.combo_length_adjust.setCurrentText("同程度")
        length_group.addWidget(self.combo_length_adjust)

        length_group.addWidget(QtWidgets.QLabel("出力言語:"))
        self.combo_arrange_output_lang = create_language_combo()
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

        # ストーリーボードタブ
        storyboard_tab = QtWidgets.QWidget()
        storyboard_layout = QtWidgets.QVBoxLayout(storyboard_tab)
        storyboard_layout.setContentsMargins(5, 5, 5, 5)

        # 設定行
        settings_row = QtWidgets.QHBoxLayout()
        settings_row.addWidget(QtWidgets.QLabel("テンプレート:"))
        self.combo_sb_template = QtWidgets.QComboBox()
        for key, tmpl in config.STORYBOARD_TEMPLATES.items():
            self.combo_sb_template.addItem(tmpl["label"], userData=key)
        self.combo_sb_template.setToolTip("カット構成のテンプレートを選択します")
        self.combo_sb_template.currentIndexChanged.connect(self._on_sb_template_change)
        settings_row.addWidget(self.combo_sb_template)

        settings_row.addWidget(QtWidgets.QLabel("総尺:"))
        self.combo_sb_duration = QtWidgets.QComboBox()
        for sec in config.STORYBOARD_DURATION_CHOICES:
            self.combo_sb_duration.addItem(f"{sec}秒", userData=sec)
        self.combo_sb_duration.setCurrentIndex(0)
        self._sb_duration_tooltip_base = "動画の総尺を選択します（10〜30秒）"
        self.combo_sb_duration.setToolTip(self._sb_duration_tooltip_base)
        self.combo_sb_duration.currentIndexChanged.connect(self._on_sb_duration_change)
        settings_row.addWidget(self.combo_sb_duration)

        settings_row.addWidget(QtWidgets.QLabel("カット数:"))
        self.spin_sb_cut_count = QtWidgets.QSpinBox()
        self.spin_sb_cut_count.setRange(1, 12)
        self.spin_sb_cut_count.setValue(3)
        self.spin_sb_cut_count.setToolTip("カットの数を指定します（1〜12）")
        self.spin_sb_cut_count.valueChanged.connect(self._on_sb_cut_count_change)
        settings_row.addWidget(self.spin_sb_cut_count)

        # 連続性強化トグル
        self.check_sb_continuity = QtWidgets.QCheckBox("連続性強化")
        self.check_sb_continuity.setToolTip(
            "有効にすると、各カットが直前のカットから滑らかに変化するよう指示を追加し、\n"
            "世界観の一貫性を強化します"
        )
        settings_row.addWidget(self.check_sb_continuity)

        # スタイル反映トグル（video_style / content_flags を背景補足情報として LLM に伝える）
        self.check_sb_style_reflection = QtWidgets.QCheckBox("スタイル反映")
        self.check_sb_style_reflection.setToolTip(
            "有効にすると、抽出した video_style（カメラ・照明・雰囲気）と\n"
            "content_flags（音声・人物・テロップ情報）をLLMへ背景補足情報として渡し、\n"
            "それに沿った描写になるようカット内容を生成します"
        )
        settings_row.addWidget(self.check_sb_style_reflection)

        # カット数・総尺の自動決定
        self.check_sb_auto_structure = QtWidgets.QCheckBox("カット数/尺をLLM自動決定")
        self.check_sb_auto_structure.setToolTip(
            "ONにすると、カット数と総尺をLLMがプロンプト内容から自動判断します。\n"
            f"目安レンジ: カット数 {config.STORYBOARD_AUTO_MIN_CUTS}-{config.STORYBOARD_AUTO_MAX_CUTS}、"
            f"総尺 {config.STORYBOARD_AUTO_MIN_DURATION:.0f}-{config.STORYBOARD_AUTO_MAX_DURATION:.0f} 秒"
        )
        self.check_sb_auto_structure.toggled.connect(self._on_sb_auto_structure_toggled)
        settings_row.addWidget(self.check_sb_auto_structure)

        char_list_btn = QtWidgets.QPushButton("キャラクター一覧...")
        char_list_btn.setToolTip("Soraキャラクター一覧を表示します")
        char_list_btn.clicked.connect(self._show_sora_character_dialog)
        settings_row.addWidget(char_list_btn)

        settings_row.addStretch()
        storyboard_layout.addLayout(settings_row)

        # カットリストと詳細のスプリッター
        sb_splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)

        # 左: カットリスト
        cut_list_widget = QtWidgets.QWidget()
        cut_list_layout = QtWidgets.QVBoxLayout(cut_list_widget)
        cut_list_layout.setContentsMargins(0, 0, 0, 0)

        self.list_sb_cuts = QtWidgets.QListWidget()
        self.list_sb_cuts.setMinimumWidth(180)
        self.list_sb_cuts.currentRowChanged.connect(self._on_sb_cut_selected)
        cut_list_layout.addWidget(self.list_sb_cuts)

        cut_btn_row = QtWidgets.QHBoxLayout()
        add_cut_btn = QtWidgets.QPushButton("+追加")
        add_cut_btn.clicked.connect(self._sb_add_cut)
        cut_btn_row.addWidget(add_cut_btn)
        del_cut_btn = QtWidgets.QPushButton("-削除")
        del_cut_btn.clicked.connect(self._sb_delete_cut)
        cut_btn_row.addWidget(del_cut_btn)
        up_cut_btn = QtWidgets.QPushButton("↑上へ")
        up_cut_btn.clicked.connect(self._sb_move_cut_up)
        cut_btn_row.addWidget(up_cut_btn)
        down_cut_btn = QtWidgets.QPushButton("↓下へ")
        down_cut_btn.clicked.connect(self._sb_move_cut_down)
        cut_btn_row.addWidget(down_cut_btn)
        cut_list_layout.addLayout(cut_btn_row)

        sb_splitter.addWidget(cut_list_widget)

        # 右: カット詳細
        cut_detail_widget = QtWidgets.QWidget()
        cut_detail_layout = QtWidgets.QVBoxLayout(cut_detail_widget)
        cut_detail_layout.setContentsMargins(5, 0, 0, 0)

        cut_detail_layout.addWidget(QtWidgets.QLabel("カット詳細:"))
        self.text_sb_cut_desc = QtWidgets.QTextEdit()
        self.text_sb_cut_desc.setPlaceholderText("このカットの説明を入力...")
        self.text_sb_cut_desc.setMinimumHeight(80)
        self.text_sb_cut_desc.textChanged.connect(self._on_sb_cut_desc_changed)
        cut_detail_layout.addWidget(self.text_sb_cut_desc)

        time_row = QtWidgets.QHBoxLayout()
        time_row.addWidget(QtWidgets.QLabel("開始:"))
        self.spin_sb_start = QtWidgets.QDoubleSpinBox()
        self.spin_sb_start.setRange(0.0, 30.0)
        self.spin_sb_start.setSingleStep(0.1)
        self.spin_sb_start.setDecimals(1)
        self.spin_sb_start.setSuffix("秒")
        self.spin_sb_start.valueChanged.connect(self._on_sb_cut_time_changed)
        time_row.addWidget(self.spin_sb_start)

        time_row.addWidget(QtWidgets.QLabel("尺:"))
        self.spin_sb_duration_cut = QtWidgets.QDoubleSpinBox()
        self.spin_sb_duration_cut.setRange(0.1, 30.0)
        self.spin_sb_duration_cut.setSingleStep(0.1)
        self.spin_sb_duration_cut.setDecimals(1)
        self.spin_sb_duration_cut.setSuffix("秒")
        self.spin_sb_duration_cut.valueChanged.connect(self._on_sb_cut_time_changed)
        time_row.addWidget(self.spin_sb_duration_cut)

        time_row.addWidget(QtWidgets.QLabel("カメラ:"))
        self.combo_sb_camera = QtWidgets.QComboBox()
        for label, code in config.CAMERA_WORK_CHOICES:
            self.combo_sb_camera.addItem(label, userData=code)
        self.combo_sb_camera.currentIndexChanged.connect(self._on_sb_cut_camera_changed)
        time_row.addWidget(self.combo_sb_camera)

        time_row.addStretch()
        cut_detail_layout.addLayout(time_row)

        # キャラクター選択
        char_row = QtWidgets.QHBoxLayout()
        char_row.addWidget(QtWidgets.QLabel("登場キャラ:"))
        self.combo_sb_char = QtWidgets.QComboBox()
        self.combo_sb_char.setMinimumWidth(150)
        self._refresh_sb_character_combo()
        char_row.addWidget(self.combo_sb_char)
        add_char_btn = QtWidgets.QPushButton("+追加")
        add_char_btn.clicked.connect(self._sb_add_character_to_cut)
        char_row.addWidget(add_char_btn)
        self.label_sb_cut_chars = QtWidgets.QLabel("（なし）")
        self.label_sb_cut_chars.setStyleSheet("color: #666;")
        char_row.addWidget(self.label_sb_cut_chars)
        clear_char_btn = QtWidgets.QPushButton("クリア")
        clear_char_btn.clicked.connect(self._sb_clear_characters_from_cut)
        char_row.addWidget(clear_char_btn)
        char_row.addStretch()
        cut_detail_layout.addLayout(char_row)

        cut_detail_layout.addStretch()

        sb_splitter.addWidget(cut_detail_widget)
        sb_splitter.setStretchFactor(0, 3)
        sb_splitter.setStretchFactor(1, 7)

        storyboard_layout.addWidget(sb_splitter, 1)

        # アクションボタン行
        sb_action_row = QtWidgets.QHBoxLayout()
        init_sb_btn = QtWidgets.QPushButton("テンプレートから初期化")
        init_sb_btn.setToolTip("選択したテンプレートでカットを初期化します")
        init_sb_btn.clicked.connect(self._sb_init_from_template)
        sb_action_row.addWidget(init_sb_btn)

        from_prompt_btn = QtWidgets.QPushButton("現在のプロンプトから生成(LLM)")
        from_prompt_btn.setToolTip("出力欄のプロンプト全文をLLMでカットに分割します")
        from_prompt_btn.clicked.connect(self._sb_generate_from_prompt)
        sb_action_row.addWidget(from_prompt_btn)

        sb_action_row.addStretch()

        apply_to_text_btn = QtWidgets.QPushButton("テキスト欄に反映")
        apply_to_text_btn.setToolTip("ストーリーボードJSONを出力欄に反映します")
        apply_to_text_btn.clicked.connect(self._sb_apply_to_text_output)
        sb_action_row.addWidget(apply_to_text_btn)

        copy_sb_btn = QtWidgets.QPushButton("JSON出力&コピー")
        copy_sb_btn.setToolTip("ストーリーボードをJSON形式でクリップボードにコピーします")
        copy_sb_btn.clicked.connect(self._sb_copy_json)
        sb_action_row.addWidget(copy_sb_btn)

        storyboard_layout.addLayout(sb_action_row)

        tools_tabs.addTab(storyboard_tab, "ストーリーボード")

        # ストーリーボード内部状態の初期化
        self._sb_cuts: List[StoryboardCut] = []
        self._sb_current_index: int = -1
        self._sb_video_style: dict = None  # 抽出した video_style
        self._sb_content_flags: dict = None  # 抽出した content_flags
        self._sb_total_duration_override: float | None = None  # LLM自動決定した総尺
        self._sb_detected_characters: List[str] = []  # テキストから検出したキャラクターID

    # =============================
    # ストーリーボードタブのイベントハンドラ
    # =============================
    def _show_sora_character_dialog(self):
        """Soraキャラクター一覧ダイアログを表示する。"""
        dialog = SoraCharacterListDialog(self)
        dialog.exec()
        # ダイアログを閉じた後、キャラクターコンボを更新
        self._refresh_sb_character_combo()

    def _refresh_sb_character_combo(self):
        """キャラクターコンボボックスを最新のYAMLデータで更新する。"""
        self.combo_sb_char.clear()
        self.combo_sb_char.addItem("（選択してください）", userData=None)
        characters = load_sora_characters()
        for char in characters:
            self.combo_sb_char.addItem(f"{char.name} ({char.id})", userData=char.id)

    def _extract_character_ids_from_text(self, text: str) -> List[str]:
        """テキストから @ID 形式のキャラクター識別子を抽出する。"""
        if not text:
            return []
        pattern = re.compile(r"(?<!\w)@[A-Za-z0-9][A-Za-z0-9._:/-]{0,63}")
        seen: set[str] = set()
        result: List[str] = []
        for match in pattern.finditer(text):
            candidate = match.group(0).rstrip(".,;:!?)］）】」』、。…")
            if candidate and candidate not in seen:
                seen.add(candidate)
                result.append(candidate)
        return result

    def _ensure_characters_registered(self, detected_ids: List[str]) -> bool:
        """検出したIDをYAMLと突合し、未登録なら登録ダイアログを表示する。"""
        self._sb_detected_characters = detected_ids or []
        if not detected_ids:
            return True

        known_ids = {char.id for char in load_sora_characters()}
        missing_ids = [cid for cid in detected_ids if cid not in known_ids]
        if not missing_ids:
            return True

        dialog = SoraCharacterRegisterDialog(missing_ids, self)
        result = dialog.exec()
        if result != QtWidgets.QDialog.Accepted:
            return False

        new_entries = dialog.get_entries()
        if new_entries:
            if not save_sora_characters(new_entries):
                choice = QtWidgets.QMessageBox.question(
                    self,
                    "保存に失敗しました",
                    "sora_characters.yaml への保存に失敗しました。\n"
                    "登録せずに続行しますか？",
                    QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                    QtWidgets.QMessageBox.No,
                )
                if choice == QtWidgets.QMessageBox.No:
                    return False
            else:
                self._refresh_sb_character_combo()

        return True

    def _on_sb_template_change(self, index: int):
        """テンプレート変更時の処理。"""
        pass  # 必要に応じてUIの有効/無効を切り替え

    def _sb_init_from_template(self):
        """テンプレートからカットリストを初期化する。"""
        template_id = self.combo_sb_template.currentData()
        total_duration = self._get_sb_total_duration()
        cut_count = self.spin_sb_cut_count.value()

        # 手動初期化時は自動総尺をリセット
        self._clear_sb_duration_override()

        self._sb_cuts = create_cuts_from_template(template_id, total_duration, cut_count)
        self._sb_refresh_cut_list()

        if self._sb_cuts:
            self.list_sb_cuts.setCurrentRow(0)

    def _sb_refresh_cut_list(self):
        """カットリストUIを内部状態から再描画する。"""
        self.list_sb_cuts.clear()
        for cut in self._sb_cuts:
            label = f"#{cut.index} ({cut.start_sec:.1f}s, {cut.duration_sec:.1f}s)"
            if cut.is_image_placeholder:
                label = f"#{cut.index} [画像] ({cut.start_sec:.1f}s)"
            self.list_sb_cuts.addItem(label)

    def _get_sb_total_duration(self) -> float:
        """UI選択またはLLM決定された総尺を返す。"""
        if self._sb_total_duration_override is not None:
            return round(self._sb_total_duration_override, 2)
        return self.combo_sb_duration.currentData() or config.DEFAULT_STORYBOARD_DURATION

    def _set_sb_total_duration_override(self, value: float | None):
        """LLM決定の総尺を保持し、ツールチップに表示する。"""
        self._sb_total_duration_override = None if value is None else round(float(value), 2)
        self._update_sb_duration_tooltip()

    def _clear_sb_duration_override(self):
        """LLM決定の総尺を解除する。"""
        self._sb_total_duration_override = None
        self._update_sb_duration_tooltip()

    def _update_sb_duration_tooltip(self):
        """総尺コンボのツールチップを最新状態に揃える。"""
        if self._sb_total_duration_override is None:
            self.combo_sb_duration.setToolTip(self._sb_duration_tooltip_base)
        else:
            self.combo_sb_duration.setToolTip(
                f"{self._sb_duration_tooltip_base}\nLLM自動推定: {self._sb_total_duration_override:.1f} 秒"
            )

    def _on_sb_auto_structure_toggled(self, checked: bool):
        """自動構成トグル切替時の処理。"""
        self.combo_sb_duration.setEnabled(not checked)
        self.spin_sb_cut_count.setEnabled(not checked)
        if checked:
            # LLM決定を待つ状態にする
            self._clear_sb_duration_override()

    def _on_sb_duration_change(self, *_):
        """総尺選択変更時にLLM自動値を解除する。"""
        self._clear_sb_duration_override()

    def _on_sb_cut_count_change(self, *_):
        """カット数変更時にLLM自動値を解除する。"""
        self._clear_sb_duration_override()

    def _recalculate_sb_total_from_cuts(self):
        """カットの開始+尺から総尺を再計算し、自動値があれば更新する。"""
        if self._sb_total_duration_override is None or not self._sb_cuts:
            return
        last_cut = self._sb_cuts[-1]
        total = round(last_cut.start_sec + last_cut.duration_sec, 2)
        self._set_sb_total_duration_override(total)

    def _adjust_sb_total_duration(self, target_total: float):
        """最終カットで総尺誤差を吸収する。"""
        if not self._sb_cuts:
            return
        last_cut = self._sb_cuts[-1]
        actual_end = round(last_cut.start_sec + last_cut.duration_sec, 2)
        delta = round(target_total - actual_end, 2)
        if abs(delta) >= 0.01:
            last_cut.duration_sec = round(max(0.1, last_cut.duration_sec + delta), 2)

    def _apply_detected_characters_to_cuts(self):
        """検出済みキャラクターIDを全カットに付与する（重複除去）。"""
        if not self._sb_detected_characters or not self._sb_cuts:
            return
        for cut in self._sb_cuts:
            existing = set(cut.characters or [])
            for char_id in self._sb_detected_characters:
                if char_id not in existing:
                    cut.characters.append(char_id)
                    existing.add(char_id)

    def _on_sb_cut_selected(self, row: int):
        """カットリストの選択変更時に詳細エリアを更新する。"""
        if row < 0 or row >= len(self._sb_cuts):
            self._sb_current_index = -1
            self.text_sb_cut_desc.clear()
            self.spin_sb_start.setValue(0)
            self.spin_sb_duration_cut.setValue(1)
            self.combo_sb_camera.setCurrentIndex(0)
            self.label_sb_cut_chars.setText("（なし）")
            return

        self._sb_current_index = row
        cut = self._sb_cuts[row]

        # イベント発火を抑制するためにblockSignals
        self.text_sb_cut_desc.blockSignals(True)
        self.text_sb_cut_desc.setPlainText(cut.description)
        self.text_sb_cut_desc.blockSignals(False)

        self.spin_sb_start.blockSignals(True)
        self.spin_sb_start.setValue(cut.start_sec)
        self.spin_sb_start.blockSignals(False)

        self.spin_sb_duration_cut.blockSignals(True)
        self.spin_sb_duration_cut.setValue(cut.duration_sec)
        self.spin_sb_duration_cut.blockSignals(False)

        camera_index = 0
        for i in range(self.combo_sb_camera.count()):
            if self.combo_sb_camera.itemData(i) == cut.camera_work:
                camera_index = i
                break
        self.combo_sb_camera.blockSignals(True)
        self.combo_sb_camera.setCurrentIndex(camera_index)
        self.combo_sb_camera.blockSignals(False)

        self._update_sb_cut_chars_label()

    def _update_sb_cut_chars_label(self):
        """現在選択中のカットのキャラクター表示を更新する。"""
        if self._sb_current_index < 0 or self._sb_current_index >= len(self._sb_cuts):
            self.label_sb_cut_chars.setText("（なし）")
            return
        cut = self._sb_cuts[self._sb_current_index]
        if cut.characters:
            self.label_sb_cut_chars.setText(", ".join(cut.characters))
        else:
            self.label_sb_cut_chars.setText("（なし）")

    def _on_sb_cut_desc_changed(self):
        """カット説明変更時の処理。"""
        if self._sb_current_index < 0 or self._sb_current_index >= len(self._sb_cuts):
            return
        self._sb_cuts[self._sb_current_index].description = self.text_sb_cut_desc.toPlainText()

    def _on_sb_cut_time_changed(self):
        """カットの時間設定変更時の処理。"""
        if self._sb_current_index < 0 or self._sb_current_index >= len(self._sb_cuts):
            return
        cut = self._sb_cuts[self._sb_current_index]
        cut.start_sec = round(self.spin_sb_start.value(), 2)
        cut.duration_sec = round(self.spin_sb_duration_cut.value(), 2)
        self._sb_refresh_cut_list()
        self.list_sb_cuts.setCurrentRow(self._sb_current_index)
        self._recalculate_sb_total_from_cuts()

    def _on_sb_cut_camera_changed(self):
        """カメラワーク変更時の処理。"""
        if self._sb_current_index < 0 or self._sb_current_index >= len(self._sb_cuts):
            return
        self._sb_cuts[self._sb_current_index].camera_work = self.combo_sb_camera.currentData() or "static"

    def _sb_add_cut(self):
        """新しいカットを追加する。"""
        total_duration = self._get_sb_total_duration()
        if self._sb_cuts:
            last_cut = self._sb_cuts[-1]
            new_start = last_cut.start_sec + last_cut.duration_sec
            remaining = total_duration - new_start
            new_duration = max(0.5, remaining) if remaining > 0 else 1.0
        else:
            new_start = 0.0
            new_duration = total_duration / 3

        new_cut = StoryboardCut(
            index=len(self._sb_cuts),
            start_sec=round(new_start, 2),
            duration_sec=round(new_duration, 2),
            description="",
            camera_work="static",
            characters=[],
            is_image_placeholder=False,
        )
        self._sb_cuts.append(new_cut)
        self._sb_reindex_cuts()
        self._sb_refresh_cut_list()
        self.list_sb_cuts.setCurrentRow(len(self._sb_cuts) - 1)
        self._recalculate_sb_total_from_cuts()

    def _sb_delete_cut(self):
        """選択中のカットを削除する。"""
        if self._sb_current_index < 0 or self._sb_current_index >= len(self._sb_cuts):
            return
        del self._sb_cuts[self._sb_current_index]
        self._sb_reindex_cuts()
        self._sb_refresh_cut_list()
        if self._sb_cuts:
            new_index = min(self._sb_current_index, len(self._sb_cuts) - 1)
            self.list_sb_cuts.setCurrentRow(new_index)
        else:
            self._sb_current_index = -1
            self._on_sb_cut_selected(-1)
        self._recalculate_sb_total_from_cuts()

    def _sb_move_cut_up(self):
        """選択中のカットを上に移動する。"""
        if self._sb_current_index <= 0 or self._sb_current_index >= len(self._sb_cuts):
            return
        idx = self._sb_current_index
        self._sb_cuts[idx], self._sb_cuts[idx - 1] = self._sb_cuts[idx - 1], self._sb_cuts[idx]
        self._sb_reindex_cuts()
        self._sb_refresh_cut_list()
        self.list_sb_cuts.setCurrentRow(idx - 1)
        self._recalculate_sb_total_from_cuts()

    def _sb_move_cut_down(self):
        """選択中のカットを下に移動する。"""
        if self._sb_current_index < 0 or self._sb_current_index >= len(self._sb_cuts) - 1:
            return
        idx = self._sb_current_index
        self._sb_cuts[idx], self._sb_cuts[idx + 1] = self._sb_cuts[idx + 1], self._sb_cuts[idx]
        self._sb_reindex_cuts()
        self._sb_refresh_cut_list()
        self.list_sb_cuts.setCurrentRow(idx + 1)
        self._recalculate_sb_total_from_cuts()

    def _sb_reindex_cuts(self):
        """カットのインデックスを振り直す。"""
        for i, cut in enumerate(self._sb_cuts):
            cut.index = i

    def _sb_add_character_to_cut(self):
        """選択したキャラクターを現在のカットに追加する。"""
        if self._sb_current_index < 0 or self._sb_current_index >= len(self._sb_cuts):
            QtWidgets.QMessageBox.warning(self, "注意", "カットを選択してください。")
            return
        char_id = self.combo_sb_char.currentData()
        if not char_id:
            QtWidgets.QMessageBox.warning(self, "注意", "キャラクターを選択してください。")
            return
        cut = self._sb_cuts[self._sb_current_index]
        if char_id not in cut.characters:
            cut.characters.append(char_id)
        self._update_sb_cut_chars_label()

    def _sb_clear_characters_from_cut(self):
        """現在のカットからキャラクターをクリアする。"""
        if self._sb_current_index < 0 or self._sb_current_index >= len(self._sb_cuts):
            return
        self._sb_cuts[self._sb_current_index].characters = []
        self._update_sb_cut_chars_label()

    def _sb_copy_json(self):
        """ストーリーボードをJSON形式でクリップボードにコピーする。"""
        if not self._sb_cuts:
            QtWidgets.QMessageBox.warning(self, "注意", "カットがありません。テンプレートから初期化してください。")
            return

        template_id = self.combo_sb_template.currentData() or "none"
        total_duration = self._get_sb_total_duration()
        continuity = self.check_sb_continuity.isChecked()

        # メタデータ（video_style, content_flags）と連続性強化フラグを含めてJSON生成
        json_text = build_storyboard_json(
            self._sb_cuts,
            total_duration,
            template_id,
            video_style=self._sb_video_style,
            content_flags=self._sb_content_flags,
            continuity_enhanced=continuity,
        )
        QtGui.QGuiApplication.clipboard().setText(json_text)
        QtWidgets.QMessageBox.information(self, "コピー完了", "ストーリーボードJSONをクリップボードにコピーしました。")

    def _sb_generate_from_prompt(self):
        """出力欄のプロンプト全文をLLMでストーリーボードのカットに分割する。"""
        from modules.llm import StoryboardLLMWorker

        if not config.LLM_ENABLED:
            QtWidgets.QMessageBox.warning(
                self,
                "注意",
                "LLMが無効化されています。YAMLで LLM_ENABLED を true にしてください。",
            )
            return

        # 出力欄から全テキストを取得（末尾固定部含む）
        raw_text = self.text_output.toPlainText().strip()
        if not raw_text:
            QtWidgets.QMessageBox.warning(
                self,
                "注意",
                "出力欄にプロンプトがありません。先にプロンプトを生成してください。",
            )
            return

        # メタデータ（video_style, content_flags）を抽出して保持
        # これらはカットの説明に含めず、ストーリーボードと並列に配置する
        video_style, content_flags, prompt_text = extract_metadata_from_prompt(raw_text)
        self._sb_video_style = video_style
        self._sb_content_flags = content_flags

        # テキストからキャラクターIDを抽出し、未登録があれば登録を促す
        detected_characters = self._extract_character_ids_from_text(prompt_text)
        if not self._ensure_characters_registered(detected_characters):
            return

        # 総尺とカット数を取得
        total_duration = self._get_sb_total_duration()
        cut_count = self.spin_sb_cut_count.value()
        auto_structure = self.check_sb_auto_structure.isChecked()

        # 出力言語を取得（動画用設定を流用）
        output_language = "en"
        lang_combo = getattr(self, "combo_movie_output_lang", None)
        if lang_combo:
            data = lang_combo.currentData()
            if data in ("en", "ja"):
                output_language = data

        # 連続性強化フラグを取得
        continuity = self.check_sb_continuity.isChecked()

        # スタイル反映フラグを取得
        style_reflection = self.check_sb_style_reflection.isChecked()

        # スタイル反映が有効な場合、video_style / content_flags を LLM に渡す
        video_style_ctx = None
        content_flags_ctx = None
        if style_reflection:
            video_style_ctx = video_style
            content_flags_ctx = content_flags

        # メタデータを除いたプロンプトテキストをLLMに送信
        worker = StoryboardLLMWorker(
            text=prompt_text,
            model=self.combo_llm_model.currentText(),
            cut_count=cut_count,
            total_duration_sec=total_duration,
            output_language=output_language,
            continuity_enhanced=continuity,
            video_style=video_style_ctx,
            content_flags=content_flags_ctx,
            length_limit=getattr(config, "SORA_PROMPT_SAFE_CHARS", 1900),
            auto_structure=auto_structure,
            cut_count_min=config.STORYBOARD_AUTO_MIN_CUTS,
            cut_count_max=config.STORYBOARD_AUTO_MAX_CUTS,
            min_duration_sec=config.STORYBOARD_AUTO_MIN_DURATION,
            max_duration_sec=config.STORYBOARD_AUTO_MAX_DURATION,
            default_duration_sec=total_duration or config.STORYBOARD_AUTO_DEFAULT_DURATION,
        )

        # コンテキストを保存
        self._sb_llm_context = {
            "cut_count": cut_count,
            "total_duration": total_duration,
            "auto_structure": auto_structure,
        }

        if self._start_background_worker(
            worker,
            self._handle_sb_llm_success,
            self._handle_sb_llm_failure,
        ):
            pass  # ワーカー開始成功

    def _handle_sb_llm_success(self, thread: QtCore.QThread, worker, result: str):
        """ストーリーボードLLM生成成功時の処理。"""
        self._set_loading_state(False)
        thread.quit()
        thread.wait()
        worker.deleteLater()
        self._thread = None

        context = getattr(self, "_sb_llm_context", {}) or {}
        self._sb_llm_context = None

        if not result:
            QtWidgets.QMessageBox.warning(self, "注意", "LLMから空のレスポンスが返されました。")
            return

        auto_structure = context.get("auto_structure", False)

        # JSONレスポンスをパース（オブジェクト形式/配列形式どちらも許容）
        cuts_data = None
        total_duration = context.get("total_duration") or config.DEFAULT_STORYBOARD_DURATION
        try:
            parsed = json.loads(result)
            if isinstance(parsed, dict) and isinstance(parsed.get("cuts"), list):
                cuts_data = parsed.get("cuts")
                total_duration = parsed.get("total_duration_sec") or total_duration
            elif isinstance(parsed, list):
                cuts_data = parsed
        except Exception:
            cuts_data = None

        if cuts_data is None:
            try:
                json_match = re.search(r'\{.*"cuts"\s*:\s*\[.*\]\s*\}', result, re.DOTALL)
                if json_match:
                    parsed = json.loads(json_match.group())
                    cuts_data = parsed.get("cuts")
                    total_duration = parsed.get("total_duration_sec") or total_duration
            except Exception:
                cuts_data = None

        if cuts_data is None:
            try:
                json_match = re.search(r'\[.*\]', result, re.DOTALL)
                if json_match:
                    cuts_data = json.loads(json_match.group())
            except Exception:
                cuts_data = None

        if not isinstance(cuts_data, list) or not cuts_data:
            QtWidgets.QMessageBox.warning(self, "注意", "有効なカットデータが見つかりません。")
            return

        # カットを生成
        actual_cut_count = len(cuts_data)

        # duration_sec が返ってくる場合は尊重し、無い場合は均等割り当て
        durations: List[float] = []
        has_duration_field = True
        for cut_data in cuts_data:
            dur = cut_data.get("duration_sec")
            if dur is None:
                dur = cut_data.get("duration")
            if isinstance(dur, (int, float)):
                durations.append(max(0.1, float(dur)))
            else:
                has_duration_field = False
                break

        if has_duration_field and durations:
            total_from_payload = round(sum(durations), 2)
            try:
                total_duration_value = float(total_duration) if total_duration is not None else None
            except (TypeError, ValueError):
                total_duration_value = None

            if auto_structure or total_duration_value is None:
                total_duration_value = total_from_payload or config.DEFAULT_STORYBOARD_DURATION
            if total_duration_value and total_from_payload and abs(total_duration_value - total_from_payload) >= 0.2:
                # スケールして総尺に合わせる
                scale = total_duration_value / total_from_payload
                durations = [round(max(0.1, d * scale), 2) for d in durations]
                total_from_payload = round(sum(durations), 2)
            if total_duration_value is None:
                total_duration_value = total_from_payload or config.DEFAULT_STORYBOARD_DURATION
            duration_per_cut = None
            total_duration = total_duration_value
        else:
            total_duration = float(total_duration or config.DEFAULT_STORYBOARD_DURATION)
            duration_per_cut = total_duration / actual_cut_count
            durations = [duration_per_cut for _ in range(actual_cut_count)]

        # 数値に正規化
        total_duration = round(float(total_duration), 2)

        # カメラワークのマッピング
        camera_map = {
            "static": "static",
            "pan": "pan",
            "zoom_in": "zoom_in",
            "zoom_out": "zoom_out",
            "tracking": "tracking",
            "dolly": "dolly",
            "handheld": "handheld",
            "drone": "drone",
        }

        self._sb_cuts = []
        current_time = 0.0
        for i, cut_data in enumerate(cuts_data):
            description = cut_data.get("description", "")
            camera_raw = cut_data.get("camera", "static")
            camera_work = camera_map.get(camera_raw.lower(), "static")

            duration_sec = durations[i] if i < len(durations) else duration_per_cut
            duration_sec = round(duration_sec or duration_per_cut or 1.0, 2)

            cut = StoryboardCut(
                index=i,
                start_sec=round(current_time, 2),
                duration_sec=duration_sec,
                description=description,
                camera_work=camera_work,
                characters=[],
                is_image_placeholder=False,
            )
            self._sb_cuts.append(cut)
            current_time += duration_sec

        # 総尺誤差を最終カットで吸収
        self._adjust_sb_total_duration(total_duration)

        # テキストから検出したキャラクターを全カットへ反映
        self._apply_detected_characters_to_cuts()

        # 自動構成の結果を保存
        if auto_structure:
            self._set_sb_total_duration_override(total_duration)
            # UIのカット数表示も結果に合わせる
            try:
                self.spin_sb_cut_count.blockSignals(True)
                self.spin_sb_cut_count.setValue(actual_cut_count)
            finally:
                self.spin_sb_cut_count.blockSignals(False)
        else:
            self._clear_sb_duration_override()

        self._sb_refresh_cut_list()
        if self._sb_cuts:
            self.list_sb_cuts.setCurrentRow(0)

        QtWidgets.QMessageBox.information(
            self,
            "生成完了",
            f"LLMでプロンプトから {actual_cut_count} カットを生成しました。\n"
            f"（総尺: {total_duration:.1f}秒）",
        )

    def _handle_sb_llm_failure(self, thread: QtCore.QThread, worker, error: str):
        """ストーリーボードLLM生成失敗時の処理。"""
        self._set_loading_state(False)
        thread.quit()
        thread.wait()
        worker.deleteLater()
        self._thread = None
        self._sb_llm_context = None
        QtWidgets.QMessageBox.critical(
            self,
            "エラー",
            f"ストーリーボード生成でエラーが発生しました:\n{error}",
        )

    def _sb_apply_to_text_output(self):
        """ストーリーボードJSONを出力欄に上書きする。"""
        if not self._sb_cuts:
            QtWidgets.QMessageBox.warning(
                self,
                "注意",
                "カットがありません。先にストーリーボードを生成してください。",
            )
            return

        template_id = self.combo_sb_template.currentData() or "none"
        total_duration = self._get_sb_total_duration()
        continuity = self.check_sb_continuity.isChecked()

        # メタデータ（video_style, content_flags）と連続性強化フラグを含めてJSON生成
        json_text = build_storyboard_json(
            self._sb_cuts,
            total_duration,
            template_id,
            video_style=self._sb_video_style,
            content_flags=self._sb_content_flags,
            continuity_enhanced=continuity,
        )

        # 出力欄を上書き
        self.text_output.setPlainText(json_text)
        QtWidgets.QMessageBox.information(
            self,
            "反映完了",
            "ストーリーボードJSONを出力欄に反映しました。",
        )

    def cycle_font_scale(self):
        """UI全体のフォントプリセットを巡回させる。"""
        if not config.FONT_SCALE_PRESETS:
            return
        self.font_scale_level = (self.font_scale_level + 1) % len(config.FONT_SCALE_PRESETS)
        self._apply_font_scale()

    def _apply_font_scale(self):
        """現在のプリセットを QApplication とウィンドウ自身へ適用する。"""
        if not config.FONT_SCALE_PRESETS:
            return
        preset = config.FONT_SCALE_PRESETS[self.font_scale_level]
        base_size = preset["pt"]
        base_family = self._ui_font_family or self.font().family()
        new_font = QtGui.QFont(base_family, base_size)

        app = QtWidgets.QApplication.instance()
        if app is not None:
            app.setFont(new_font)
        self.setFont(new_font)

        if hasattr(self, "text_output") and self.text_output is not None:
            output_font = QtGui.QFont(base_family, base_size + 2)
            self.text_output.setFont(output_font)

        big_action_size = base_size + 2
        group_title_size = base_size

        self.centralWidget().setStyleSheet(
            f"""
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
        """
        )

        self._update_font_button_label(preset["label"])

    def _update_font_button_label(self, label: str):
        """フォント切替ボタンのラベルを最新状態に揃える。"""
        if self.button_font_scale:
            self.button_font_scale.setText(f"フォント: {label}")
