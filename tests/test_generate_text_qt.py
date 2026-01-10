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
    """video_prompt.prompt が無いストーリーボードJSONでも、cuts[].description を本文として復元できること。"""

    from modules.storyboard import extract_metadata_from_prompt

    raw = """
    {
      "video_prompt": {
        "video_style": {"genre": "tv_news_special"},
        "content_flags": {"bgm": true},
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
    video_style, content_flags, prompt_text = extract_metadata_from_prompt(raw)
    assert video_style == {"genre": "tv_news_special"}
    assert content_flags == {"bgm": True}
    assert "東京の夜" in prompt_text
    assert "路地を走るタクシー" in prompt_text


def test_extract_metadata_from_prompt_video_prompt_without_body_falls_back_to_full_text():
    """本文がどこにも無い場合でも、自由記述として全文フォールバックし empty にならないこと。"""

    from modules.storyboard import extract_metadata_from_prompt

    raw = '{"video_prompt":{"storyboard":{"cuts":[{"index":0,"description":""}]}}}'
    _, _, prompt_text = extract_metadata_from_prompt(raw)
    assert prompt_text  # empty にはならない
    assert "video_prompt" in prompt_text