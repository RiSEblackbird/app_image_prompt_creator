import os
import sqlite3
import sys
from pathlib import Path

import pytest

PySide6 = pytest.importorskip("PySide6")
from PySide6 import QtCore, QtTest, QtWidgets

# repo root から pytest を実行しても import が崩れないよう、app_image_prompt_creator を明示的に sys.path へ追加する。
_REPO_ROOT = Path(__file__).resolve().parents[2]
_APP_DIR = _REPO_ROOT / "app_image_prompt_creator"
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

import app_image_prompt_creator_qt as qt_app  # noqa: E402
from modules import config as prompt_config  # noqa: E402


@pytest.fixture(scope="module", autouse=True)
def qt_application():
    """オフスクリーン描画で Qt アプリを初期化し、GUI依存テストを安定化させる。"""

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


def _prepare_test_db(db_path: Path) -> None:
    """重複説明を含む属性データセットを作成する。"""

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.executescript(
        """
        CREATE TABLE attribute_types (
            id INTEGER PRIMARY KEY,
            attribute_name TEXT,
            description TEXT
        );
        CREATE TABLE attribute_details (
            id INTEGER PRIMARY KEY,
            attribute_type_id INTEGER,
            description TEXT,
            value TEXT
        );
        CREATE TABLE prompts (
            id INTEGER PRIMARY KEY,
            content TEXT
        );
        CREATE TABLE prompt_attribute_details (
            prompt_id INTEGER,
            attribute_detail_id INTEGER
        );
        """
    )
    cursor.execute(
        "INSERT INTO attribute_types (id, attribute_name, description) VALUES (?, ?, ?)",
        (1, "style", "画風"),
    )
    cursor.executemany(
        "INSERT INTO attribute_details (id, attribute_type_id, description, value) VALUES (?, ?, ?, ?)",
        [
            (1, 1, "印象派", "impressionist"),
            (2, 1, "印象派", "neo_impressionist"),
        ],
    )
    cursor.execute("INSERT INTO prompts (id, content) VALUES (?, ?)", (1, "First prompt"))
    cursor.execute("INSERT INTO prompts (id, content) VALUES (?, ?)", (2, "Second prompt"))
    cursor.executemany(
        "INSERT INTO prompt_attribute_details (prompt_id, attribute_detail_id) VALUES (?, ?)",
        [
            (1, 1),
            (2, 2),
        ],
    )
    conn.commit()
    conn.close()


@pytest.fixture()
def prompt_generator(tmp_path, monkeypatch, qt_application):
    """テスト用DBを差し替えたウィンドウインスタンスを返す。"""

    db_path = tmp_path / "test.db"
    _prepare_test_db(db_path)
    # PromptGeneratorWindow は modules.config.DEFAULT_DB_PATH を参照するため、そちらを差し替える。
    # qt_app モジュールの属性だけを差し替えると、起動時にDB不足ダイアログが出てテストが停止しうる。
    monkeypatch.setattr(qt_app.config, "DEFAULT_DB_PATH", str(db_path))
    window = qt_app.PromptGeneratorWindow()
    window.spin_row_num.setValue(1)
    yield window
    window.close()


def _process_events() -> None:
    """Qt の遅延レイアウト更新を反映させる。"""
    app = QtWidgets.QApplication.instance()
    assert app is not None
    app.processEvents()
    QtCore.QThread.msleep(10)
    app.processEvents()


def test_generate_text_uses_selected_attribute_id(prompt_generator):
    """同じ説明文の属性から、IDで指定したほうのみ抽出されることを確認する。"""

    detail_combo = prompt_generator.attribute_combo_map[1]
    second_detail_index = detail_combo.findData(2)
    assert second_detail_index >= 0
    detail_combo.setCurrentIndex(second_detail_index)
    prompt_generator.attribute_count_map[1].setCurrentText("1")

    prompt_generator.generate_text()

    assert "Second prompt." in prompt_generator.main_prompt
    assert "First prompt" not in prompt_generator.main_prompt


def test_generate_and_copy_waits_for_llm_completion(prompt_generator, monkeypatch):
    """LLMモードでは、生成前にクリップボードへコピーしないこと。"""

    copied = []
    prompt_generator.text_output.setPlainText("previous output")
    monkeypatch.setattr(prompt_generator, "_is_llm_generation_mode", lambda: True)
    monkeypatch.setattr(prompt_generator, "generate_text", lambda: True)
    monkeypatch.setattr(
        prompt_generator,
        "copy_all_to_clipboard",
        lambda: copied.append(prompt_generator.text_output.toPlainText()),
    )

    prompt_generator.generate_and_copy()

    assert copied == []
    assert prompt_generator._pending_generate_and_copy is True


def test_llm_success_copies_pending_result_after_output_is_updated(prompt_generator, monkeypatch):
    """LLM生成の完了後に、更新済みの全文をコピーすること。"""

    copied = []

    class DummyThread:
        def quit(self):
            return None

        def wait(self):
            return None

    class DummyWorker:
        def deleteLater(self):
            return None

    def fake_update_option(sync_from_text=False):
        prompt_generator.text_output.setPlainText(prompt_generator.main_prompt)

    monkeypatch.setattr(prompt_generator, "update_option", fake_update_option)
    monkeypatch.setattr(QtWidgets.QDialog, "exec", lambda self: 0)
    monkeypatch.setattr(
        prompt_generator,
        "_copy_output_to_clipboard",
        lambda show_message=False: copied.append(prompt_generator.text_output.toPlainText()) or True,
    )
    prompt_generator._llm_generate_context = {
        "total_lines": 1,
        "deduplicate": False,
        "exclusion_words": [],
        "attribute_conditions": [],
        "chaos_level": 1,
        "output_language": "en",
    }
    prompt_generator._pending_generate_and_copy = True

    prompt_generator._handle_generate_llm_success(DummyThread(), DummyWorker(), "generated line")

    assert copied == ["generated line."]
    assert prompt_generator._pending_generate_and_copy is False


def test_attribute_section_toggle_changes_visible_height(prompt_generator):
    """属性選択は展開時に十分な高さを持ち、格納時に最小化されること。"""

    prompt_generator.resize(420, 900)
    prompt_generator.show()
    _process_events()

    collapsed_height = prompt_generator.attr_section_container.height()
    assert collapsed_height <= 60
    assert not prompt_generator.attr_body_container.isVisible()

    prompt_generator.attr_toggle_button.click()
    _process_events()

    expanded_height = prompt_generator.attr_section_container.height()
    assert prompt_generator.attr_body_container.isVisible()
    assert expanded_height >= 140
    assert expanded_height > collapsed_height + 60

    prompt_generator.attr_toggle_button.click()
    _process_events()

    collapsed_again_height = prompt_generator.attr_section_container.height()
    assert not prompt_generator.attr_body_container.isVisible()
    assert collapsed_again_height < expanded_height
    assert collapsed_again_height <= 60


def test_collapsed_attribute_section_recomputes_height_after_font_scale(prompt_generator):
    """格納状態でフォント変更しても、ヘッダが欠けない高さに再計算されること。"""

    prompt_generator.resize(420, 900)
    prompt_generator.show()
    _process_events()

    assert not prompt_generator.attr_toggle_button.isChecked()

    initial_max_height = prompt_generator.attr_section_container.maximumHeight()
    initial_button_height = prompt_generator.attr_toggle_button.sizeHint().height()
    assert initial_max_height >= initial_button_height

    # 複数回切り替えて確実に大きいフォントへ到達させる。
    for _ in range(max(2, len(qt_app.config.FONT_SCALE_PRESETS))):
        prompt_generator.cycle_font_scale()
    _process_events()

    scaled_max_height = prompt_generator.attr_section_container.maximumHeight()
    scaled_button_height = prompt_generator.attr_toggle_button.sizeHint().height()

    assert scaled_button_height >= initial_button_height
    assert scaled_max_height >= scaled_button_height


def test_main_splitter_starts_with_wider_left_pane(prompt_generator):
    """初期表示時の左ペインは、最小幅ではなく操作しやすい既定幅で始まること。"""

    prompt_generator.show()
    _process_events()

    splitter = prompt_generator.main_splitter
    sizes = splitter.sizes()

    assert sizes[0] >= 700
    assert sizes[1] >= 280
    assert sizes[0] > 220


def test_main_splitter_default_sizes_retries_until_success(prompt_generator, monkeypatch):
    """初回適用が未確定でも、既定サイズの再試行で最終的に適用済みになること。"""

    call_count = 0

    def fake_apply_default_sizes():
        nonlocal call_count
        call_count += 1
        return call_count >= 2

    monkeypatch.setattr(prompt_generator, "_apply_default_main_splitter_sizes", fake_apply_default_sizes)

    prompt_generator.show()
    _process_events()

    assert call_count >= 2
    assert prompt_generator._main_splitter_default_applied is True


def test_left_splitter_can_change_sizes_when_attribute_section_expanded(prompt_generator):
    """左スプリッタは展開後も上下サイズを変更できること。"""

    prompt_generator.resize(420, 900)
    prompt_generator.show()
    _process_events()

    if not prompt_generator.attr_toggle_button.isChecked():
        prompt_generator.attr_toggle_button.click()
        _process_events()

    splitter = prompt_generator.left_splitter
    before = splitter.sizes()
    total = sum(before)
    assert total > 0

    target_upper = min(total - 40, before[0] + 80)
    splitter.moveSplitter(target_upper, 1)
    _process_events()

    after = splitter.sizes()
    assert after != before
    assert abs(after[0] - target_upper) <= 40


def test_left_splitter_handle_drag_moves_down_when_attribute_section_expanded(prompt_generator):
    """左スプリッタのハンドルを実際にドラッグすると下方向へ移動できること。"""

    prompt_generator.resize(420, 900)
    prompt_generator.show()
    _process_events()

    if not prompt_generator.attr_toggle_button.isChecked():
        prompt_generator.attr_toggle_button.click()
        _process_events()

    splitter = prompt_generator.left_splitter
    before = splitter.sizes()
    handle = splitter.handle(1)
    assert handle is not None

    center = handle.rect().center()
    drag_target = center + QtCore.QPoint(0, 80)
    QtTest.QTest.mousePress(handle, QtCore.Qt.LeftButton, QtCore.Qt.NoModifier, center)
    QtTest.QTest.mouseMove(handle, drag_target, delay=20)
    QtTest.QTest.mouseRelease(handle, QtCore.Qt.LeftButton, QtCore.Qt.NoModifier, drag_target, delay=20)
    _process_events()

    after = splitter.sizes()
    assert after != before
    assert after[0] > before[0]


def test_collapsed_attribute_section_keeps_minimal_height_without_forcing_splitter(prompt_generator):
    """属性選択を格納しても、最小化されるのは属性セクションだけでスプリッタ位置は固定しないこと。"""

    prompt_generator.resize(420, 900)
    prompt_generator.show()
    _process_events()

    if not prompt_generator.attr_toggle_button.isChecked():
        prompt_generator.attr_toggle_button.click()
        _process_events()

    splitter = prompt_generator.left_splitter
    splitter.moveSplitter(260, 1)
    _process_events()
    expanded_sizes = splitter.sizes()
    expanded_height = prompt_generator.attr_section_container.height()

    prompt_generator.attr_toggle_button.click()
    _process_events()

    collapsed_sizes = splitter.sizes()
    collapsed_height = prompt_generator.attr_section_container.height()

    assert not prompt_generator.attr_body_container.isVisible()
    assert collapsed_height <= 60
    assert collapsed_height < expanded_height
    assert abs(collapsed_sizes[0] - expanded_sizes[0]) <= 20
    assert abs(collapsed_sizes[1] - expanded_sizes[1]) <= 20


def test_left_splitter_handle_drag_moves_when_attribute_section_collapsed(prompt_generator):
    """属性選択が格納状態でも、左スプリッタのハンドルを下方向へドラッグできること。"""

    prompt_generator.resize(420, 900)
    prompt_generator.show()
    _process_events()

    assert not prompt_generator.attr_toggle_button.isChecked()

    splitter = prompt_generator.left_splitter
    before = splitter.sizes()
    handle = splitter.handle(1)
    assert handle is not None

    center = handle.rect().center()
    drag_target = center + QtCore.QPoint(0, 80)
    QtTest.QTest.mousePress(handle, QtCore.Qt.LeftButton, QtCore.Qt.NoModifier, center)
    QtTest.QTest.mouseMove(handle, drag_target, delay=20)
    QtTest.QTest.mouseRelease(handle, QtCore.Qt.LeftButton, QtCore.Qt.NoModifier, drag_target, delay=20)
    _process_events()

    after = splitter.sizes()
    assert after != before
    assert after[0] > before[0]


def test_storyboard_duration_allocation_prompt_llm_contains_duration_rules(qt_application):
    """カット数指定 + 尺配分=LLM の場合に duration_sec と厳密合計ルールを要求すること。"""

    from modules.llm import StoryboardLLMWorker

    worker = StoryboardLLMWorker(
        text="東京の夜景。雨。ネオン。",
        model="gpt-4o-mini",
        cut_count=3,
        total_duration_sec=12.0,
        duration_allocation="llm",
        auto_structure=False,
    )
    _, user_prompt = worker._build_prompts()
    assert "duration_sec" in user_prompt
    assert "SUM of all duration_sec MUST EQUAL total_duration_sec EXACTLY" in user_prompt
    assert "exactly 3 cinematic cuts" in user_prompt
    assert "DEPICTABILITY FIRST" in user_prompt


def test_storyboard_duration_allocation_prompt_uniform_uses_array_format(qt_application):
    """カット数指定 + 尺配分=均等 の場合は配列フォーマットを使い、duration_sec を必須化しないこと。"""

    from modules.llm import StoryboardLLMWorker

    worker = StoryboardLLMWorker(
        text="A calm morning in Kyoto.",
        model="gpt-4o-mini",
        cut_count=4,
        total_duration_sec=20.0,
        duration_allocation="uniform",
        auto_structure=False,
    )
    _, user_prompt = worker._build_prompts()
    assert "Output format (JSON array)" in user_prompt
    assert '"duration_sec"' not in user_prompt
    assert "DEPICTABILITY FIRST" in user_prompt


def test_storyboard_auto_structure_prompt_keeps_total_duration_fixed(qt_application):
    """自動構成（カット数自動）でも総尺は固定値を厳守し、LLMに総尺を選ばせないこと。"""

    from modules.llm import StoryboardLLMWorker

    worker = StoryboardLLMWorker(
        text="東京の夜景。雨。ネオン。",
        model="gpt-4o-mini",
        cut_count=3,
        total_duration_sec=12.0,
        duration_allocation="llm",
        auto_structure=True,
    )
    _, user_prompt = worker._build_prompts()
    assert "Total video duration: 12.0 seconds (fixed by settings)." in user_prompt
    assert "DO NOT change total_duration_sec" in user_prompt
    assert '"total_duration_sec": 12.0' in user_prompt


def test_storyboard_duration_allocation_prompt_llm_total_allows_model_total_duration(qt_application):
    """総尺もモデル提案にする場合は、総尺レンジと total_duration_sec の返却を要求すること。"""

    from modules.llm import StoryboardLLMWorker

    worker = StoryboardLLMWorker(
        text="A moonlit shrine path with drifting fog.",
        model="gpt-4o-mini",
        cut_count=4,
        total_duration_sec=15.0,
        duration_allocation="llm_total",
        auto_structure=False,
    )
    _, user_prompt = worker._build_prompts()
    assert "Decide total_duration_sec between 8.0 and 24.0 seconds." in user_prompt
    assert "Treat 12.0 seconds as a soft preference" in user_prompt
    assert '"total_duration_sec": <number>' in user_prompt
    assert "exactly 4 cinematic cuts" in user_prompt


def test_storyboard_llm_total_success_updates_total_duration_override(prompt_generator, monkeypatch):
    """総尺をモデル提案にするモードでは、返却された total_duration_sec をUIの総尺として採用すること。"""

    class DummyThread:
        def quit(self):
            return None

        def wait(self):
            return None

    class DummyWorker:
        def deleteLater(self):
            return None

    monkeypatch.setattr(QtWidgets.QMessageBox, "information", lambda *args, **kwargs: None)
    prompt_generator._sb_llm_context = {
        "cut_count": 2,
        "total_duration": 10.0,
        "original_total_duration": 10.0,
        "auto_structure": False,
        "duration_allocation": "llm_total",
        "total_duration_mode": "llm",
        "min_duration_sec": 8.0,
        "max_duration_sec": 24.0,
        "fixed_preset_defs": [],
        "fixed_duration_sum": 0.0,
    }

    prompt_generator._handle_sb_llm_success(
        DummyThread(),
        DummyWorker(),
        qt_app.json.dumps(
            {
                "total_duration_sec": 14.5,
                "cuts": [
                    {"cut": 1, "duration_sec": 5.0, "description": "霧の参道。", "camera": "pan"},
                    {"cut": 2, "duration_sec": 9.5, "description": "鳥居の奥へ進む。", "camera": "tracking"},
                ],
            },
            ensure_ascii=False,
        ),
    )

    assert prompt_generator._get_sb_total_duration() == 14.5
    assert [cut.duration_sec for cut in prompt_generator._sb_cuts] == [5.0, 9.5]
    assert [cut.start_sec for cut in prompt_generator._sb_cuts] == [0.0, 5.0]


def test_storyboard_llm_total_missing_total_duration_is_rejected(prompt_generator, monkeypatch):
    """総尺モデル提案モードで total_duration_sec が欠けた応答は、均等割当へ黙ってフォールバックしないこと。"""

    class DummyThread:
        def quit(self):
            return None

        def wait(self):
            return None

    class DummyWorker:
        def deleteLater(self):
            return None

    warnings = []
    monkeypatch.setattr(QtWidgets.QMessageBox, "warning", lambda *args, **kwargs: warnings.append(args))
    prompt_generator._sb_llm_context = {
        "cut_count": 2,
        "total_duration": 10.0,
        "original_total_duration": 10.0,
        "auto_structure": False,
        "duration_allocation": "llm_total",
        "total_duration_mode": "llm",
        "min_duration_sec": 8.0,
        "max_duration_sec": 24.0,
        "fixed_preset_defs": [],
        "fixed_duration_sum": 0.0,
    }

    prompt_generator._handle_sb_llm_success(
        DummyThread(),
        DummyWorker(),
        qt_app.json.dumps(
            {
                "cuts": [
                    {"cut": 1, "duration_sec": 5.0, "description": "霧の参道。", "camera": "pan"},
                    {"cut": 2, "duration_sec": 5.0, "description": "鳥居の奥へ進む。", "camera": "tracking"},
                ]
            },
            ensure_ascii=False,
        ),
    )

    assert warnings
    assert "total_duration_sec" in warnings[0][2]
    assert prompt_generator._sb_cuts == []


def test_extract_metadata_from_prompt_fallbacks_to_storyboard_cut_descriptions():
    """video_prompt.prompt が無いストーリーボードJSONでも、メタ情報と本文を復元できること。"""

    from modules.storyboard import extract_metadata_from_prompt

    raw = """
    {
      "video_prompt": {
        "video_style": {"genre": "tv_news_special"},
        "content_flags": {"bgm": true},
        "direction_constraints": {"environment_scope": "outdoor_only", "subject_tags": ["ruins", "wildlife"]},
        "storyboard": {
          "total_duration_sec": 10.0,
          "template": "none",
          "cuts": [
            {"index": 0, "start_sec": 0.0, "duration_sec": 2.5, "description": "東京の夜。雨に濡れたネオンが反射する。"},
            {"index": 1, "start_sec": 2.5, "duration_sec": 7.5, "description": "路地を走るタクシー。カメラは追従する。"}
          ]
        }
      }
    }
    """
    video_style, content_flags, direction_constraints, prompt_text = extract_metadata_from_prompt(raw)
    assert video_style == {"genre": "tv_news_special"}
    assert content_flags == {"bgm": True}
    assert direction_constraints == {"environment_scope": "outdoor_only", "subject_tags": ["ruins", "wildlife"]}
    assert "東京の夜" in prompt_text
    assert "路地を走るタクシー" in prompt_text


def test_extract_metadata_from_prompt_video_prompt_without_body_falls_back_to_full_text():
    """本文がどこにも無い場合でも、自由記述として全文フォールバックし empty にならないこと。"""

    from modules.storyboard import extract_metadata_from_prompt

    raw = '{"video_prompt":{"storyboard":{"cuts":[{"index":0,"description":""}]}}}'
    _, _, _, prompt_text = extract_metadata_from_prompt(raw)
    assert prompt_text  # empty にはならない
    assert "video_prompt" in prompt_text


def test_build_storyboard_json_keeps_structured_movie_metadata():
    """ストーリーボードJSONでは instructions を持たず、構造化メタデータをそのまま保持すること。"""

    from modules.prompt_data import StoryboardCut
    from modules.storyboard import build_storyboard_json

    result = build_storyboard_json(
        cuts=[
            StoryboardCut(index=0, start_sec=0.0, duration_sec=5.0, description="夜の路地。"),
            StoryboardCut(index=1, start_sec=5.0, duration_sec=5.0, description="濡れた道路を進む。"),
        ],
        total_duration_sec=10.0,
        template_id="none",
        content_flags={"dialogue_mode": "no_dialogue", "person_mode": "no_people"},
        direction_constraints={"environment_scope": "outdoor_only", "camera_motion": "continuous"},
    )

    payload = qt_app.json.loads(result)
    assert payload["video_prompt"]["storyboard"]["total_duration_sec"] == 10.0
    assert payload["video_prompt"]["content_flags"]["dialogue_mode"] == "no_dialogue"
    assert payload["video_prompt"]["content_flags"]["person_mode"] == "no_people"
    assert payload["video_prompt"]["direction_constraints"]["environment_scope"] == "outdoor_only"
    assert "instructions" not in payload["video_prompt"]


def test_compose_movie_prompt_keeps_direction_constraints():
    """動画JSON統合時に prompt を汚さず、送信用は構造化メタデータだけを保持すること。"""

    from modules.prompt_text_utils import compose_movie_prompt

    result = compose_movie_prompt(
        core_json='{"prompt":"A vast interior atrium."}',
        movie_tail='{"video_style":{"scope":"full_movie","format":"8K"}}',
        flags_tail='{"content_flags":{"bgm_mode":"with_bgm","dialogue_mode":"no_dialogue","person_mode":"no_people"}}',
        direction_tail='{"direction_constraints":{"environment_scope":"outdoor_only","subject_tags":["ruins","wildlife"],"camera_motion":"continuous"}}',
        options_tail="",
    )

    payload = qt_app.json.loads(result)
    assert payload["video_prompt"]["video_style"]["format"] == "8K"
    assert payload["video_prompt"]["content_flags"]["bgm_mode"] == "with_bgm"
    assert payload["video_prompt"]["content_flags"]["dialogue_mode"] == "no_dialogue"
    assert payload["video_prompt"]["content_flags"]["person_mode"] == "no_people"
    assert payload["video_prompt"]["direction_constraints"]["environment_scope"] == "outdoor_only"
    assert payload["video_prompt"]["direction_constraints"]["subject_tags"] == ["ruins", "wildlife"]
    assert payload["video_prompt"]["direction_constraints"]["camera_motion"] == "continuous"
    assert payload["video_prompt"]["prompt"] == "A vast interior atrium."
    assert "instructions" not in payload["video_prompt"]


def test_compile_movie_instructions_include_bgm_details():
    """BGM 詳細が自然文の補助指示へ展開されること。"""

    from modules.prompt_text_utils import compile_movie_instructions

    instructions = compile_movie_instructions(
        {
            "bgm_mode": "with_bgm",
            "bgm_genre": "cinematic",
            "bgm_mood": "melancholic",
            "bgm_tempo": "slow",
            "bgm_vocal": "instrumental",
            "bgm_sync": "beat_matched",
            "bgm_notes": "Let the bass stay soft.",
        },
        None,
    )

    assert "Use background music." in instructions
    assert "Use a cinematic soundtrack." in instructions
    assert "Keep the music melancholic." in instructions
    assert "Use a slow tempo." in instructions
    assert "Keep the track instrumental." in instructions
    assert "Synchronize the music with the edit rhythm." in instructions
    assert "Let the bass stay soft." in instructions


def test_all_bgm_dropdown_tokens_compile_to_sentences():
    """BGM 詳細の全トークンが自然文へ変換でき、UI定義と文生成の契約が崩れていないこと。"""

    from modules.prompt_text_utils import compile_movie_instructions

    option_sets = (
        ("bgm_genre", prompt_config.BGM_GENRE_CHOICES),
        ("bgm_mood", prompt_config.BGM_MOOD_CHOICES),
        ("bgm_tempo", prompt_config.BGM_TEMPO_CHOICES),
        ("bgm_vocal", prompt_config.BGM_VOCAL_CHOICES),
        ("bgm_sync", prompt_config.BGM_SYNC_CHOICES),
    )

    for key, choices in option_sets:
        for _, token in choices:
            if not token:
                continue
            instructions = compile_movie_instructions({"bgm_mode": "with_bgm", key: token}, None)
            assert "Use background music." in instructions
            assert len(instructions) >= 2


def test_bgm_dropdown_labels_are_japanese(prompt_generator):
    """BGM のプルダウンは日本語ラベルで表示されること。"""

    genre_combo = prompt_generator.combo_tail_bgm_genre
    mood_combo = prompt_generator.combo_tail_bgm_mood

    assert genre_combo.count() == 36
    assert mood_combo.count() == 30
    assert prompt_generator.combo_tail_bgm_tempo.count() == 18
    assert prompt_generator.combo_tail_bgm_vocal.count() == 18
    assert prompt_generator.combo_tail_bgm_sync.count() == 18
    assert genre_combo.itemText(0) == "未指定"
    assert genre_combo.itemText(genre_combo.findData("cinematic")) == "シネマティック"
    assert genre_combo.itemText(genre_combo.findData("alien_ritual")) == "異界の儀式音楽"
    assert mood_combo.itemText(mood_combo.findData("melancholic")) == "切ない"
    assert mood_combo.itemText(mood_combo.findData("nightmarish")) == "悪夢"
    assert prompt_generator.combo_tail_bgm_tempo.itemText(
        prompt_generator.combo_tail_bgm_tempo.findData("erratic_meter")
    ) == "暴走変拍子"
    assert prompt_generator.combo_tail_bgm_vocal.itemText(
        prompt_generator.combo_tail_bgm_vocal.findData("robotic_chant")
    ) == "ロボット詠唱"
    assert prompt_generator.combo_tail_bgm_sync.itemText(
        prompt_generator.combo_tail_bgm_sync.findData("counter_sync")
    ) == "逆同期"


def test_make_tail_flags_json_includes_bgm_details(prompt_generator):
    """BGM を有効にすると詳細設定が content_flags に含まれること。"""

    prompt_generator.check_tail_flags_enabled.setChecked(True)
    prompt_generator.check_tail_flag_bgm.setChecked(True)
    prompt_generator.combo_tail_bgm_genre.setCurrentIndex(prompt_generator.combo_tail_bgm_genre.findData("cinematic"))
    prompt_generator.combo_tail_bgm_mood.setCurrentIndex(prompt_generator.combo_tail_bgm_mood.findData("melancholic"))
    prompt_generator.combo_tail_bgm_tempo.setCurrentIndex(prompt_generator.combo_tail_bgm_tempo.findData("slow"))
    prompt_generator.combo_tail_bgm_vocal.setCurrentIndex(
        prompt_generator.combo_tail_bgm_vocal.findData("instrumental")
    )
    prompt_generator.combo_tail_bgm_sync.setCurrentIndex(
        prompt_generator.combo_tail_bgm_sync.findData("beat_matched")
    )
    prompt_generator.entry_tail_bgm_notes.setText("後半だけ少し盛り上げる。")

    payload = qt_app.json.loads(prompt_generator._make_tail_flags_json().strip())
    flags = payload["content_flags"]

    assert flags["bgm_mode"] == "with_bgm"
    assert flags["narration_mode"] == "no_narration"
    assert flags["ambient_sound_mode"] == "no_ambient_sound"
    assert flags["dialogue_mode"] == "no_dialogue"
    assert flags["bgm_genre"] == "cinematic"
    assert flags["bgm_mood"] == "melancholic"
    assert flags["bgm_tempo"] == "slow"
    assert flags["bgm_vocal"] == "instrumental"
    assert flags["bgm_sync"] == "beat_matched"
    assert flags["bgm_notes"] == "後半だけ少し盛り上げる。"


def test_prepend_attached_image_world_description_updates_video_style_description():
    """添付画像世界トグル用の前置きが video_style.description の先頭に入ること。"""

    from modules.prompt_text_utils import (
        ATTACHED_IMAGE_WORLD_DESCRIPTION_PREFIX,
        prepend_attached_image_world_description,
    )

    result = prepend_attached_image_world_description(
        '{"video_style":{"scope":"full_movie","description":"this is sweeping cinematic footage"}}',
        enabled=True,
    )

    payload = qt_app.json.loads(result)
    assert payload["video_style"]["description"] == (
        f"{ATTACHED_IMAGE_WORLD_DESCRIPTION_PREFIX} this is sweeping cinematic footage"
    )


def test_extract_metadata_from_prompt_strips_compiled_requirements_block():
    """旧形式の polluted prompt でも本文抽出時に要件ブロックを除去できること。"""

    from modules.storyboard import extract_metadata_from_prompt

    raw = """
    {
      "video_prompt": {
        "prompt": "A ruined stone gate in moonlight.\\n\\nVideo requirements:\\n- Keep the entire video outdoors only.\\n- Visually focus on these subjects: ruins, wildlife.",
        "direction_constraints": {
          "environment_scope": "outdoor_only",
          "subject_tags": ["ruins", "wildlife"]
        }
      }
    }
    """
    _, _, direction_constraints, prompt_text = extract_metadata_from_prompt(raw)
    assert direction_constraints == {"environment_scope": "outdoor_only", "subject_tags": ["ruins", "wildlife"]}
    assert prompt_text == "A ruined stone gate in moonlight."


def test_make_direction_constraints_json_from_ui(prompt_generator):
    """演出制約UIの選択が direction_constraints JSON として出力されること。"""

    prompt_generator.check_direction_constraints_enabled.setChecked(True)
    prompt_generator.combo_direction_environment_scope.setCurrentText("水中")
    prompt_generator.check_direction_allow_still_frames.setChecked(False)
    prompt_generator.direction_common_subject_actions["water_features"].setChecked(True)
    prompt_generator.direction_common_subject_actions["celestial_bodies"].setChecked(True)
    prompt_generator.entry_direction_subject_tags.setText("coral reef")
    prompt_generator.combo_direction_camera_motion.setCurrentText("常時動く")
    prompt_generator.combo_direction_visual_energy.setCurrentText("生き生き")
    prompt_generator.combo_direction_cut_duration_policy.setCurrentText("可変")
    prompt_generator.combo_direction_subject_focus.setCurrentText("情景主体")
    prompt_generator.entry_direction_freeform_constraints.setText("Avoid modern urban elements.")
    prompt_generator.check_direction_live_action_only.setChecked(True)
    prompt_generator.check_direction_ultra_high_resolution_8k.setChecked(True)
    prompt_generator.direction_style_tag_checkboxes["anime"].setChecked(True)
    prompt_generator.direction_style_tag_checkboxes["ukiyo-e"].setChecked(True)

    payload = qt_app.json.loads(prompt_generator._make_direction_constraints_json().strip())

    assert payload == {
        "direction_constraints": {
            "still_frame_policy": "forbid",
            "environment_scope": "underwater",
            "subject_tags": ["water_features", "celestial_bodies", "coral reef"],
            "camera_motion": "continuous",
            "visual_energy": "vivid",
            "cut_duration_policy": "variable",
            "focus_priority": "scene",
            "freeform_constraints": "Avoid modern urban elements.",
            "render_style": "live_action",
            "resolution_tier": "8k",
            "style_tags": ["anime", "ukiyo-e"],
        }
    }
    assert prompt_generator.label_direction_common_subjects.text() in ("水辺・水域 / 天体", "天体 / 水辺・水域")


def test_all_direction_choice_tokens_compile_to_sentences():
    """direction_constraints の全トークンが自然文へ変換でき、UI定義と文生成の契約が崩れていないこと。"""

    from modules.prompt_text_utils import compile_movie_instructions

    single_value_option_sets = (
        ("environment_scope", prompt_config.DIRECTION_ENVIRONMENT_SCOPE_CHOICES),
        ("camera_motion", prompt_config.DIRECTION_CAMERA_MOTION_CHOICES),
        ("visual_energy", prompt_config.DIRECTION_VISUAL_ENERGY_CHOICES),
        ("cut_duration_policy", prompt_config.DIRECTION_CUT_DURATION_POLICY_CHOICES),
        ("focus_priority", prompt_config.DIRECTION_SUBJECT_FOCUS_CHOICES),
    )

    for key, choices in single_value_option_sets:
        for _, token in choices:
            if not token:
                continue
            instructions = compile_movie_instructions(None, {key: token})
            assert instructions, f"{key}={token} did not compile into any instruction"

    for _, token in prompt_config.DIRECTION_COMMON_SUBJECT_TAGS:
        instructions = compile_movie_instructions(None, {"subject_tags": [token]})
        assert instructions, f"subject_tags={token} did not compile into any instruction"

    for _, token in prompt_config.DIRECTION_STYLE_TAG_CHOICES:
        instructions = compile_movie_instructions(None, {"style_tags": [token]})
        assert instructions, f"style_tags={token} did not compile into any instruction"


def test_direction_dropdown_and_menu_counts(prompt_generator):
    """演出制約の各選択肢が追加後の件数になっていること。"""

    assert prompt_generator.combo_direction_environment_scope.count() == 19
    assert len(prompt_generator.direction_common_subject_actions) == 21
    assert prompt_generator.combo_direction_camera_motion.count() == 14
    assert prompt_generator.combo_direction_visual_energy.count() == 14
    assert prompt_generator.combo_direction_cut_duration_policy.count() == 14
    assert prompt_generator.combo_direction_subject_focus.count() == 13

    assert prompt_generator.combo_direction_environment_scope.itemText(
        prompt_generator.combo_direction_environment_scope.findData("wetlands")
    ) == "湿地・沼地"
    assert prompt_generator.combo_direction_subject_focus.itemText(
        prompt_generator.combo_direction_subject_focus.findData("texture")
    ) == "質感主体"
    assert prompt_generator.direction_common_subject_actions["signage"].text() == "広告・看板"


def test_resolve_focus_priority_from_defaults_accepts_new_tokens(prompt_generator):
    """新しい focus_priority 既定値も UI に復元できること。"""

    assert prompt_generator._resolve_focus_priority_from_defaults({"focus_priority": "depth"}) == "depth"


def test_movie_direction_constraints_compile_new_quality_flags():
    """新しい演出制約フラグが instructions に自然文として反映されること。"""

    from modules.prompt_text_utils import compile_movie_instructions

    instructions = compile_movie_instructions(
        None,
        {
            "render_style": "live_action",
            "resolution_tier": "8k",
        },
    )

    assert "Render the entire video as fully live-action footage with no animated or illustrative look." in instructions
    assert "Render the entire video in ultra high resolution 8K quality." in instructions


def test_movie_direction_constraints_compile_style_tags():
    """画風タグが instructions に自然文として反映されること。"""

    from modules.prompt_text_utils import compile_movie_instructions

    instructions = compile_movie_instructions(
        None,
        {
            "style_tags": ["anime", "ukiyo-e"],
        },
    )

    assert "Use an anime-inspired visual style with cel-like clarity, stylized motion, and expressive composition." in instructions
    assert "Use a ukiyo-e-inspired visual style with woodblock-like contours, flat layered color, and graphic patterning." in instructions


def test_movie_direction_constraints_compile_subject_focus():
    """主体指定が instructions に自然文として反映されること。"""

    from modules.prompt_text_utils import compile_movie_instructions

    instructions = compile_movie_instructions(
        {"person_mode": "at_least_one_person"},
        {"focus_priority": "scene"},
    )

    assert "At least one person appears on screen." in instructions
    assert (
        "Even if people appear on screen, keep the environment, scenery, and overall scene as the primary visual focus rather than individual people."
        in instructions
    )


def test_make_tail_flags_json_supports_explicit_zero_people(prompt_generator):
    """0人選択時は person_mode=no_people を明示出力すること。"""

    prompt_generator.check_tail_flags_enabled.setChecked(True)
    prompt_generator.combo_tail_person_count.setCurrentText("0人")

    payload = qt_app.json.loads(prompt_generator._make_tail_flags_json().strip())

    assert payload["content_flags"]["person_mode"] == "no_people"


def test_movie_tail_media_type_hides_midjourney_options(prompt_generator):
    """movie 用途では、無効な Midjourney オプションUIを隠して誤操作を防ぐこと。"""

    assert not prompt_generator.group_midjourney_options.isHidden()

    prompt_generator.combo_tail_media_type.setCurrentText("movie")

    assert prompt_generator.group_midjourney_options.isHidden()

    prompt_generator.combo_tail_media_type.setCurrentText("image")

    assert not prompt_generator.group_midjourney_options.isHidden()


def test_movie_tail_preset_detaches_attached_image_world_option(prompt_generator):
    """添付画像世界の指定はプリセット一覧ではなく独立トグルで扱うこと。"""

    prompt_generator.combo_tail_media_type.setCurrentText("movie")
    labels = [prompt_generator.combo_tail_free.itemText(i) for i in range(prompt_generator.combo_tail_free.count())]

    assert "添付画像に写る世界についての動画" not in labels
    assert not prompt_generator.check_attached_image_world_prefix.isHidden()


def test_attached_image_world_toggle_prepends_movie_description_in_output(prompt_generator):
    """独立トグルON時は、選択中 style の description 先頭へ要件を前置きすること。"""

    from modules.prompt_text_utils import ATTACHED_IMAGE_WORLD_DESCRIPTION_PREFIX

    prompt_generator.combo_tail_media_type.setCurrentText("movie")
    target_index = prompt_generator.combo_tail_free.findText(
        "70mmフィルムで撮影された、ドラマチック照明の横移動シネマティック全編"
    )
    assert target_index >= 0
    prompt_generator.combo_tail_free.setCurrentIndex(target_index)
    prompt_generator.main_prompt = "A ruined city under moonlight."
    prompt_generator.check_attached_image_world_prefix.setChecked(True)

    prompt_generator.update_option(sync_from_text=False)

    payload = qt_app.json.loads(prompt_generator.text_output.toPlainText())
    description = payload["video_prompt"]["video_style"]["description"]
    assert description.startswith(ATTACHED_IMAGE_WORLD_DESCRIPTION_PREFIX)
    assert "this is sweeping cinematic footage" in description


def test_update_option_does_not_restore_cleared_prompt(prompt_generator):
    """出力欄を空にした後の部分更新で、直前の本文が復活しないこと。"""

    prompt_generator.main_prompt = "Revived prompt should not return."
    prompt_generator.option_prompt = " --ar 16:9"
    prompt_generator.tail_free_texts = " cinematic lighting"
    prompt_generator.text_output.setPlainText("")

    prompt_generator.update_option()

    assert prompt_generator.main_prompt == ""
    assert prompt_generator.option_prompt == ""
    assert prompt_generator.text_output.toPlainText() == ""


def test_update_option_button_click_keeps_cleared_output_empty(prompt_generator):
    """Qt の clicked(bool) 経由でも、空欄更新で旧本文が復活しないこと。"""

    prompt_generator.main_prompt = "Revived prompt should not return."
    prompt_generator.option_prompt = " --ar 16:9"
    prompt_generator.tail_free_texts = " cinematic lighting"
    prompt_generator.text_output.setPlainText("")

    update_button = next(
        button for button in prompt_generator.findChildren(QtWidgets.QPushButton)
        if button.text() == "オプションのみ更新"
    )
    update_button.click()

    assert prompt_generator.main_prompt == ""
    assert prompt_generator.option_prompt == ""
    assert prompt_generator.text_output.toPlainText() == ""


def test_storyboard_time_edit_start_updates_prev_duration_and_ripples(prompt_generator, monkeypatch):
    """開始時刻の編集が、直前カットの尺に反映され、以降の start が累積で再計算されること。"""

    # QMessageBox がモーダルでテストを止めないようにする（失敗時の保険）
    monkeypatch.setattr(QtWidgets.QMessageBox, "warning", lambda *args, **kwargs: None)

    prompt_generator.spin_sb_cut_count.setValue(3)
    prompt_generator._sb_init_from_template()
    assert len(prompt_generator._sb_cuts) == 3

    # 2番目のカットを選択し、開始を +1.0 秒ずらす → 前カットの尺が +1.0 秒になる
    prompt_generator.list_sb_cuts.setCurrentRow(1)
    before = [(c.start_sec, c.duration_sec) for c in prompt_generator._sb_cuts]

    old_start_1 = prompt_generator._sb_cuts[1].start_sec
    # QDoubleSpinBox は小数桁/ステップで丸めるため、実際に入った値を基準に差分を評価する
    prompt_generator.spin_sb_start.setValue(old_start_1 + 1.0)
    applied_start_1 = prompt_generator.spin_sb_start.value()
    delta = round(applied_start_1 - old_start_1, 2)

    after = [(c.start_sec, c.duration_sec) for c in prompt_generator._sb_cuts]

    def assert_close(actual: float, expected: float, tol: float = 0.02) -> None:
        assert abs(round(actual - expected, 2)) <= tol

    # 前カット(0)の尺が増える
    assert_close(after[0][1] - before[0][1], delta)
    # 選択カット(1)の開始は更新される（累積なので一致するはず）
    assert_close(after[1][0] - before[1][0], delta)
    # 後続カット(2)の開始もリップルする
    assert_close(after[2][0] - before[2][0], delta)


def test_storyboard_time_edit_duration_ripples_next_start(prompt_generator, monkeypatch):
    """尺の編集が、後続カットの start を自動更新し、総尺は最後で吸収されること。"""

    monkeypatch.setattr(QtWidgets.QMessageBox, "warning", lambda *args, **kwargs: None)

    prompt_generator.spin_sb_cut_count.setValue(3)
    prompt_generator._sb_init_from_template()
    assert len(prompt_generator._sb_cuts) == 3

    prompt_generator.list_sb_cuts.setCurrentRow(0)
    before = [(c.start_sec, c.duration_sec) for c in prompt_generator._sb_cuts]

    # 先頭カットの尺を +1.0 秒
    old_dur_0 = prompt_generator._sb_cuts[0].duration_sec
    prompt_generator.spin_sb_duration_cut.setValue(old_dur_0 + 1.0)
    applied_dur_0 = prompt_generator.spin_sb_duration_cut.value()
    delta = round(applied_dur_0 - old_dur_0, 2)

    after = [(c.start_sec, c.duration_sec) for c in prompt_generator._sb_cuts]

    def assert_close(actual: float, expected: float, tol: float = 0.02) -> None:
        assert abs(round(actual - expected, 2)) <= tol

    # 先頭カットの尺が増える
    assert_close(after[0][1] - before[0][1], delta)
    # 次カット以降の開始が押し出される
    assert_close(after[1][0] - before[1][0], delta)
    assert_close(after[2][0] - before[2][0], delta)
