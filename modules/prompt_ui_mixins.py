from __future__ import annotations

from typing import Iterable

from PySide6 import QtCore, QtGui, QtWidgets

from modules import config
from modules.prompt_data import load_exclusion_words
from modules.ui_helpers import create_language_combo


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
