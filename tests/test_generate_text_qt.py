import os
import sqlite3
import sys
from pathlib import Path

import pytest

PySide6 = pytest.importorskip("PySide6")
from PySide6 import QtWidgets

# repo root から pytest を実行しても import が崩れないよう、app_image_prompt_creator を明示的に sys.path へ追加する。
_REPO_ROOT = Path(__file__).resolve().parents[2]
_APP_DIR = _REPO_ROOT / "app_image_prompt_creator"
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

import app_image_prompt_creator_qt as qt_app  # noqa: E402


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


def test_compose_movie_prompt_keeps_direction_constraints():
    """動画JSON統合時に prompt を汚さず、自然文要件は instructions に分離すること。"""

    from modules.prompt_text_utils import compose_movie_prompt

    result = compose_movie_prompt(
        core_json='{"prompt":"A vast interior atrium."}',
        movie_tail='{"video_style":{"scope":"full_movie","format":"8K"}}',
        flags_tail='{"content_flags":{"bgm":true,"dialogue":false,"person_present":false}}',
        direction_tail='{"direction_constraints":{"environment_scope":"outdoor_only","subject_tags":["ruins","wildlife"],"camera_motion":"continuous"}}',
        options_tail="",
    )

    payload = qt_app.json.loads(result)
    assert payload["video_prompt"]["video_style"]["format"] == "8K"
    assert payload["video_prompt"]["content_flags"]["bgm"] is True
    assert payload["video_prompt"]["direction_constraints"]["environment_scope"] == "outdoor_only"
    assert payload["video_prompt"]["direction_constraints"]["subject_tags"] == ["ruins", "wildlife"]
    assert payload["video_prompt"]["direction_constraints"]["camera_motion"] == "continuous"
    assert payload["video_prompt"]["prompt"] == "A vast interior atrium."
    assert "Do not use spoken dialogue." in payload["video_prompt"]["instructions"]
    assert "No people appear on screen." in payload["video_prompt"]["instructions"]
    assert "Keep the entire video outdoors only." in payload["video_prompt"]["instructions"]
    assert "Visually focus on these subjects: ruins, wildlife." in payload["video_prompt"]["instructions"]


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
    prompt_generator.entry_direction_freeform_constraints.setText("Avoid modern urban elements.")

    payload = qt_app.json.loads(prompt_generator._make_direction_constraints_json().strip())

    assert payload == {
        "direction_constraints": {
            "allow_still_frames": False,
            "environment_scope": "underwater",
            "subject_tags": ["water_features", "celestial_bodies", "coral reef"],
            "camera_motion": "continuous",
            "visual_energy": "vivid",
            "cut_duration_policy": "variable",
            "freeform_constraints": "Avoid modern urban elements.",
        }
    }
    assert prompt_generator.label_direction_common_subjects.text() in ("水辺・水域 / 天体", "天体 / 水辺・水域")


def test_make_tail_flags_json_supports_explicit_zero_people(prompt_generator):
    """0人選択時は未指定ではなく person_count=0 を明示出力すること。"""

    prompt_generator.check_tail_flags_enabled.setChecked(True)
    prompt_generator.combo_tail_person_count.setCurrentText("0人")

    payload = qt_app.json.loads(prompt_generator._make_tail_flags_json().strip())

    assert payload["content_flags"]["person_present"] is False
    assert payload["content_flags"]["person_count"] == 0


def test_movie_tail_media_type_hides_midjourney_options(prompt_generator):
    """movie 用途では、無効な Midjourney オプションUIを隠して誤操作を防ぐこと。"""

    assert not prompt_generator.group_midjourney_options.isHidden()

    prompt_generator.combo_tail_media_type.setCurrentText("movie")

    assert prompt_generator.group_midjourney_options.isHidden()

    prompt_generator.combo_tail_media_type.setCurrentText("image")

    assert not prompt_generator.group_midjourney_options.isHidden()


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