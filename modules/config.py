"""共有定数とランタイム設定の保管場所。"""

from __future__ import annotations

import socket
from copy import deepcopy
from pathlib import Path
from typing import List

# =============================
# 固定値・オプション
# =============================
WINDOW_TITLE = "画像プロンプトランダム生成ツール (PySide6)"
DEFAULT_ROW_NUM = 10
DEFAULT_TAIL_MEDIA_TYPE = "image"
AVAILABLE_LLM_MODELS = [
    "gpt-4o-mini",
    "gpt-4o",
    "gpt-5.1",
]
DEFAULT_LLM_MODEL = AVAILABLE_LLM_MODELS[0]
LANGUAGE_COMBO_CHOICES = [
    ("英語", "en"),
    ("日本語", "ja"),
]

# =============================
# ストーリーボード関連定数
# =============================
# 総尺の選択肢（秒）
STORYBOARD_DURATION_CHOICES = [10, 15, 20, 25, 30]
DEFAULT_STORYBOARD_DURATION = 10

# カメラワークの選択肢
CAMERA_WORK_CHOICES = [
    ("固定", "static"),
    ("パン", "pan"),
    ("ズームイン", "zoom_in"),
    ("ズームアウト", "zoom_out"),
    ("トラッキング", "tracking"),
    ("ドリー", "dolly"),
    ("手持ち", "handheld"),
    ("ドローン", "drone"),
]

# テンプレート定義
# preset_cuts: 事前定義されたカット構成（None の場合は自動均等配分）
# weight_distribution: カット比率（preset_cuts が None の場合に使用）
STORYBOARD_TEMPLATES = {
    "none": {
        "label": "（テンプレートなし）",
        "description": "カットを均等配分",
        "preset_cuts": None,
        "weight_distribution": None,
    },
    "image_unbind": {
        "label": "画像スタート（呪縛解除）",
        "description": "添付画像から始めて0.3秒でシーンにジャンプ",
        "preset_cuts": [
            {
                "start_sec": 0.0,
                "duration_sec": 0.3,
                "description": "[Attached image]",
                "is_image_placeholder": True,
            },
            {
                "start_sec": 0.3,
                "duration_sec": None,  # 残り時間を自動計算
                "description": "Jump into the world where this image was taken. The scene begins to move and unfold naturally.",
                "is_image_placeholder": False,
            },
        ],
        "weight_distribution": None,
    },
    "opening_heavy": {
        "label": "オープニング重視",
        "description": "導入カットを総尺の40%に",
        "preset_cuts": None,
        "weight_distribution": [0.4, 0.3, 0.3],
    },
    "climax_heavy": {
        "label": "クライマックス重視",
        "description": "最終カットを総尺の40%に",
        "preset_cuts": None,
        "weight_distribution": [0.3, 0.3, 0.4],
    },
}

# 末尾プリセット（YAML欠損時のフォールバック）
DEFAULT_TAIL_PRESETS = {
    "image": [
        {"description_ja": "（なし）", "prompt": ""},
        {
            "description_ja": "超高解像度写真 (8K)",
            "prompt": "A high resolution photograph. Very high resolution. 8K photo",
        },
        {
            "description_ja": "日本画・墨絵スタイル",
            "prompt": "a Japanese ink painting. Zen painting",
        },
        {
            "description_ja": "中世ヨーロッパ絵画スタイル",
            "prompt": "a Medieval European painting.",
        },
    ],
    "movie": [
        {"description_ja": "（なし）", "prompt": ""},
        {
            "description_ja": "70mmフィルムのシネマティック全編",
            "prompt": "{\"video_style\":{\"scope\":\"full_movie\",\"description\":\"sweeping cinematic sequence shot on 70mm film\",\"look\":\"dramatic lighting\"}}",
        },
        {
            "description_ja": "4K HDR の高精細トラッキングショット",
            "prompt": "{\"video_style\":{\"scope\":\"full_movie\",\"description\":\"dynamic tracking shot captured as ultra high fidelity footage\",\"format\":\"4K HDR\"}}",
        },
        {
            "description_ja": "ムーディーなアートハウス短編",
            "prompt": "{\"video_style\":{\"scope\":\"full_movie\",\"description\":\"moody arthouse short film\",\"camera\":\"deliberate movement\"}}",
        },
        {
            "description_ja": "モダンな映画予告編風の高速モンタージュ",
            "prompt": "{\"video_style\":{\"scope\":\"full_movie\",\"description\":\"fast-paced montage cut like a modern movie trailer\",\"grade\":\"Dolby Vision\"}}",
        },
        {
            "description_ja": "タイトなシネマティックショット (4K)",
            "prompt": "{\"video_style\":{\"scope\":\"full_movie\",\"description\":\"tight cinematic shot with controlled, fluid camera motion\",\"format\":\"4K\"}}",
        },
        {
            "description_ja": "1960年代フィルムプリント風の雰囲気カット",
            "prompt": "{\"video_style\":{\"scope\":\"full_movie\",\"description\":\"atmospheric sequence graded like a 1960s film print\",\"grade\":\"film emulation\"}}",
        },
        {
            "description_ja": "スタジオライティングの高コントラストショット",
            "prompt": "{\"video_style\":{\"scope\":\"full_movie\",\"description\":\"crisp studio-lit shot with high contrast and clean composition\",\"look\":\"studio lighting\"}}",
        },
        {
            "description_ja": "ハンドヘルド撮影の自然なモーションブラー",
            "prompt": "{\"video_style\":{\"scope\":\"full_movie\",\"description\":\"handheld cinematic shot with subtle motion blur and natural grain\",\"camera\":\"handheld\"}}",
        },
        {
            "description_ja": "8K マスターのスムーズな編集シネマティック",
            "prompt": "{\"video_style\":{\"scope\":\"full_movie\",\"description\":\"cinematic shot mastered in 8K with smooth editing rhythm\",\"format\":\"8K\"}}",
        },
        {
            "description_ja": "ドローンによるワンテイク空撮",
            "prompt": "{\"video_style\":{\"scope\":\"full_movie\",\"description\":\"continuous one-take aerial drone footage flying smoothly through the scene\",\"camera\":\"drone one-shot\"}}",
        },
        {
            "description_ja": "サスペンスドラマ風の緊張感あるシーン",
            "prompt": "{\"video_style\":{\"scope\":\"full_movie\",\"description\":\"tense, dramatic scene from a suspense TV drama with moody lighting and framing\",\"genre\":\"suspense drama\"}}",
        },
        {
            "description_ja": "ワンショット・ドキュメンタリー調の現実的トーン",
            "prompt": "{\"video_style\":{\"scope\":\"full_movie\",\"description\":\"single-take documentary-style shot that follows this world in a realistic tone\",\"style\":\"one-shot documentary\"}}",
        },
    ],
}

TAIL_PRESETS = deepcopy(DEFAULT_TAIL_PRESETS)

DEFAULT_ARRANGE_PRESETS = [
    {"id": "auto", "label": "auto", "guidance": ""},
]
ARRANGE_PRESETS: List[dict] = deepcopy(DEFAULT_ARRANGE_PRESETS)

S_OPTIONS = ["", "0", "10", "20", "30", "40", "50", "100", "150", "200", "250", "300", "400", "500", "600", "700", "800", "900", "1000"]
AR_OPTIONS = ["", "16:9", "9:16", "4:3", "3:4"]
CHAOS_OPTIONS = ["", "0", "10", "20", "30", "40", "50", "60", "70", "80", "90", "100"]
Q_OPTIONS = ["", "1", "2"]
WEIRD_OPTIONS = ["", "0", "10", "20", "30", "40", "50", "100", "150", "200", "250", "500", "750", "1000", "1250", "1500", "1750", "2000", "2250", "2500", "2750", "3000"]
LABEL_EXCLUSION_WORDS = "除外語句："
CHAT_COMPLETIONS_URL = "https://api.openai.com/v1/chat/completions"
RESPONSES_API_URL = "https://api.openai.com/v1/responses"
RESPONSES_MODEL_PREFIXES = ("gpt-5",)
LENGTH_LIMIT_REASONS = {"length", "max_output_tokens"}

HOSTNAME = socket.gethostname()
SCRIPT_DIR = Path(__file__).resolve().parent.parent

LOG_DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"
LOG_FORMAT = (
    "%(asctime)s.%(msecs)03d\t%(levelname)s\t%(hostname)s\t"
    "pid=%(process)d\tthread=%(threadName)s\t%(name)s:%(lineno)d\t%(message)s"
)

FONT_SCALE_PRESETS = [
    {"label": "標準", "pt": 11},
    {"label": "大", "pt": 13},
    {"label": "特大", "pt": 16},
    {"label": "4K", "pt": 20},
]

# =============================
# アプリ設定（デフォルト＋ランタイム上書き）
# =============================
DEFAULT_APP_SETTINGS = {
    "POSITION_FILE": "window_position_app_image_prompt_creator.txt",
    "BASE_FOLDER": ".",
    "DEFAULT_TXT_PATH": "image_prompt_parts.txt",
    "DEFAULT_DB_PATH": "image_prompt_parts.db",
    "EXCLUSION_CSV": "exclusion_targets.csv",
    "ARRANGE_PRESETS_YAML": "arrange_presets.yaml",
    "TAIL_PRESETS_YAML": "tail_presets.yaml",
    "SORA_CHARACTERS_YAML": "sora_characters.yaml",
    "DEDUPLICATE_PROMPTS": True,
    "LLM_ENABLED": False,
    "LLM_MODEL": DEFAULT_LLM_MODEL,
    "LLM_MAX_COMPLETION_TOKENS": 4500,
    "LLM_TIMEOUT": 30,
    "OPENAI_API_KEY_ENV": "OPENAI_API_KEY",
    "LLM_INCLUDE_TEMPERATURE": False,
    "LLM_TEMPERATURE": 0.7,
}

SETTINGS_SNAPSHOT_KEYS = [
    "BASE_FOLDER",
    "DEFAULT_DB_PATH",
    "EXCLUSION_CSV",
    "ARRANGE_PRESETS_YAML",
    "TAIL_PRESETS_YAML",
    "LLM_ENABLED",
    "LLM_MODEL",
    "LLM_MAX_COMPLETION_TOKENS",
    "LLM_TIMEOUT",
    "LLM_INCLUDE_TEMPERATURE",
]

# 読み込み時にまとめて提示する警告
SETTINGS_LOAD_NOTES: List[str] = []

# ランタイム設定（initialize_settings で上書き）
settings = {"app_image_prompt_creator": deepcopy(DEFAULT_APP_SETTINGS)}
BASE_FOLDER = DEFAULT_APP_SETTINGS["BASE_FOLDER"]
DEFAULT_TXT_PATH = DEFAULT_APP_SETTINGS["DEFAULT_TXT_PATH"]
DEFAULT_DB_PATH = DEFAULT_APP_SETTINGS["DEFAULT_DB_PATH"]
POSITION_FILE = DEFAULT_APP_SETTINGS["POSITION_FILE"]
EXCLUSION_CSV = DEFAULT_APP_SETTINGS["EXCLUSION_CSV"]
DEDUPLICATE_PROMPTS = DEFAULT_APP_SETTINGS["DEDUPLICATE_PROMPTS"]
LLM_ENABLED = DEFAULT_APP_SETTINGS["LLM_ENABLED"]
LLM_MODEL = DEFAULT_APP_SETTINGS["LLM_MODEL"]
LLM_TEMPERATURE = DEFAULT_APP_SETTINGS["LLM_TEMPERATURE"]
LLM_MAX_COMPLETION_TOKENS = DEFAULT_APP_SETTINGS["LLM_MAX_COMPLETION_TOKENS"]
LLM_TIMEOUT = DEFAULT_APP_SETTINGS["LLM_TIMEOUT"]
OPENAI_API_KEY_ENV = DEFAULT_APP_SETTINGS["OPENAI_API_KEY_ENV"]
ARRANGE_PRESETS_YAML = str(SCRIPT_DIR / DEFAULT_APP_SETTINGS["ARRANGE_PRESETS_YAML"])
TAIL_PRESETS_YAML = str(SCRIPT_DIR / DEFAULT_APP_SETTINGS["TAIL_PRESETS_YAML"])
SORA_CHARACTERS_YAML = str(SCRIPT_DIR / DEFAULT_APP_SETTINGS["SORA_CHARACTERS_YAML"])
LLM_INCLUDE_TEMPERATURE = DEFAULT_APP_SETTINGS["LLM_INCLUDE_TEMPERATURE"]
