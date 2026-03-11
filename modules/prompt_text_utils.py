"""テキスト整形や末尾抽出など、UIに依存しないプロンプト処理ヘルパー。"""

from __future__ import annotations

import json
import re
from typing import List, Tuple

MOVIE_REQUIREMENTS_HEADER = "Video requirements:"
ATTACHED_IMAGE_WORLD_DESCRIPTION_PREFIX = (
    "Expand the world shown in the attached image into a coherent moving scene "
    "while preserving its atmosphere, place, and visual logic."
)


def sanitize_to_english(text: str) -> str:
    """プロンプト内の典型的な和語を軽量に英訳する。"""
    replacements = {
        "和風": "Japanese style",
        "浮世絵": "ukiyo-e",
        "侍": "samurai",
        "忍者": "ninja",
        "アール・デコ": "Art Deco",
        "アール・ヌーヴォー": "Art Nouveau",
        "水彩画": "watercolor",
        "漫画": "manga",
        "アニメ": "anime",
        "ノワール": "noir",
        "ヴェイパーウェーブ": "vaporwave",
    }
    out = text
    for source, target in replacements.items():
        out = out.replace(source, target)
    return out


def extract_anchor_terms(text: str, max_terms: int = 8) -> List[str]:
    """残したい名詞・象徴語を抽出し、簡易スコア順に返す。"""
    try:
        cleaned = re.sub(r"[^A-Za-z0-9\-\s]", " ", text)
        tokens = [t.strip("-") for t in cleaned.split()]
        tokens = [t for t in tokens if len(t) >= 3]
        priority = {
            "cherry",
            "blossom",
            "blossoms",
            "lantern",
            "lanterns",
            "temple",
            "shrine",
            "garden",
            "tea",
            "bamboo",
            "maple",
            "zen",
            "wabi",
            "sabi",
            "imperfection",
            "architecture",
            "wood",
            "paper",
            "stone",
            "bridge",
            "pond",
            "kimono",
            "tatami",
            "shoji",
            "bonsai",
        }
        scored = []
        for token in tokens:
            score = 1
            lowered = token.lower()
            if lowered in priority:
                score += 3
            if any(
                keyword in lowered
                for keyword in [
                    "garden",
                    "temple",
                    "shrine",
                    "lantern",
                    "blossom",
                    "bamboo",
                    "maple",
                    "tea",
                    "zen",
                ]
            ):
                score += 1
            scored.append((score, token))
        scored.sort(reverse=True)
        anchors: List[str] = []
        seen = set()
        for _, word in scored:
            lowered_word = word.lower()
            if lowered_word not in seen:
                anchors.append(word)
                seen.add(lowered_word)
            if len(anchors) >= max_terms:
                break
        return anchors
    except Exception:
        return []


def split_prompt_and_options(text: str) -> Tuple[str, str, bool]:
    """MJのオプション部分を末尾から切り出し、メイン部と返す。"""
    try:
        tokens = (text or "").strip().split()
        if not tokens:
            return "", "", False
        allowed = {"--ar", "--s", "--chaos", "--q", "--weird"}
        start_idx = None
        i = len(tokens) - 1
        while i >= 0:
            if tokens[i] in allowed:
                start_idx = i
                i -= 1
                if i >= 0 and tokens[i] not in allowed and not tokens[i].startswith("--"):
                    i -= 1
                while i >= 0:
                    if tokens[i] in allowed:
                        i -= 1
                        if i >= 0 and not tokens[i].startswith("--"):
                            i -= 1
                    else:
                        break
                start_idx = i + 1
                break
            else:
                i -= 1
        if start_idx is not None and 0 <= start_idx < len(tokens):
            j = start_idx
            ok = True
            while j < len(tokens):
                if tokens[j] in allowed:
                    j += 1
                    if j < len(tokens) and not tokens[j].startswith("--"):
                        j += 1
                else:
                    ok = False
                    break
            if ok:
                main_text = " ".join(tokens[:start_idx]).rstrip()
                options_tail = (" " + " ".join(tokens[start_idx:])) if start_idx < len(tokens) else ""
                return main_text, options_tail, True
        return (text or "").strip(), "", False
    except Exception:
        return (text or "").strip(), "", False


def inherit_options_if_present(original_text: str, new_text: str) -> str:
    """元テキストに存在する MJ オプションを新テキストへ継承する。"""
    orig_main, orig_opts, has_opts = split_prompt_and_options(original_text)
    if has_opts:
        new_main, _, _ = split_prompt_and_options(new_text)
        return new_main + orig_opts
    return strip_all_options(new_text)


def strip_all_options(text: str) -> str:
    """MJオプションを一括削除し、余分な空白も正規化する。"""
    try:
        pattern = r"(?:(?<=\s)|^)--(?:ar|s|chaos|q|weird)(?:\s+(?!-)[^\s]+)?"
        cleaned = re.sub(pattern, "", text)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned
    except Exception:
        return (text or "").strip()


def _detach_named_json_tail(text: str, key_name: str) -> Tuple[str, str]:
    """指定キーを含む JSON ブロックを末尾側から1つ抽出する。"""
    text = (text or "").strip()
    search_end = len(text) - 1
    marker_double = f'"{key_name}"'
    marker_single = f"'{key_name}'"

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
            if marker_double in candidate or marker_single in candidate:
                remaining = (text[:start_idx] + " " + text[end_idx + 1 :]).strip()
                remaining = " ".join(remaining.split())
                return remaining, candidate
            search_end = start_idx - 1
        else:
            search_end = end_idx - 1

    return text, ""


def detach_content_flags_tail(text: str) -> Tuple[str, str]:
    """
    content_flags を含む JSON ブロック({...})を末尾から探して取り出す。
    見つかった場合は (残りテキスト, content_flags JSON) を返す。
    """
    return _detach_named_json_tail(text, "content_flags")


def detach_movie_tail_for_llm(text: str) -> Tuple[str, str]:
    """
    video_style を含む JSON ブロック({...})を末尾から探して取り出す。
    見つかった場合は (残りテキスト, video_style JSON) を返す。
    """
    return _detach_named_json_tail(text, "video_style")


def detach_direction_constraints_tail(text: str) -> Tuple[str, str]:
    """
    direction_constraints を含む JSON ブロック({...})を末尾から探して取り出す。
    見つかった場合は (残りテキスト, direction_constraints JSON) を返す。
    """
    return _detach_named_json_tail(text, "direction_constraints")


def extract_sentence_details(text: str) -> List[str]:
    """句読点で分割した細部表現リストを返す。"""
    sentence_candidates = re.split(r"[。\.]\s*", text or "")
    details = [s.strip(" .　") for s in sentence_candidates if s.strip(" .　")]
    return details or [text.strip()]


def _ensure_sentence(text: str) -> str:
    """末尾句点を補い、1文として扱いやすい形へ整える。"""
    normalized = " ".join(str(text or "").split()).strip()
    if not normalized:
        return ""
    if normalized.endswith((".", "!", "?")):
        return normalized
    return normalized + "."


def strip_compiled_movie_requirements(prompt_text: str) -> str:
    """prompt 末尾に追記した Video requirements ブロックを取り除く。"""
    text = (prompt_text or "").strip()
    marker = f"\n\n{MOVIE_REQUIREMENTS_HEADER}\n"
    if marker not in text:
        return text
    base, _ = text.rsplit(marker, 1)
    return base.strip()


def _compile_content_flags_to_sentences(content_flags: dict | None) -> List[str]:
    """content_flags を動画モデルが読みやすい自然文へ変換する。"""
    if not isinstance(content_flags, dict):
        return []

    sentences: List[str] = []
    flag_phrases = {
        "narration": ("Use narration", "Do not use narration"),
        "bgm": ("Use background music", "Do not use background music"),
        "ambient_sound": ("Include ambient environmental sound", "Do not use ambient environmental sound"),
        "dialogue": ("Include spoken dialogue", "Do not use spoken dialogue"),
    }
    for key, (positive, negative) in flag_phrases.items():
        value = content_flags.get(key)
        if value is True:
            sentences.append(_ensure_sentence(positive))
        elif value is False:
            sentences.append(_ensure_sentence(negative))

    person_present = content_flags.get("person_present")
    person_count = content_flags.get("person_count")
    if person_present is False:
        sentences.append("No people appear on screen.")
    elif person_present is True:
        if person_count == "1+":
            sentences.append("At least one person appears on screen.")
        elif person_count == "many":
            sentences.append("Many people appear on screen.")
        elif isinstance(person_count, int) and person_count >= 1:
            sentences.append(_ensure_sentence(f"Show {person_count} people on screen"))
        else:
            sentences.append("People appear on screen.")

    if content_flags.get("on_screen_spoken_dialogue_subtitles"):
        sentences.append("Display on-screen subtitles for the spoken dialogue.")
    if content_flags.get("on_screen_non_dialogue_text_overlays"):
        sentences.append("Display non-dialogue text overlays on screen.")

    spoken_language = content_flags.get("spoken_language")
    if isinstance(spoken_language, str) and spoken_language in ("ja", "en"):
        language_label = "Japanese" if spoken_language == "ja" else "English"
        sentences.append(_ensure_sentence(f"If speech is present, use {language_label}"))

    return sentences


def _compile_direction_constraints_to_sentences(direction_constraints: dict | None) -> List[str]:
    """direction_constraints を自然文へ変換する。"""
    if not isinstance(direction_constraints, dict):
        return []

    sentences: List[str] = []

    environment_scope = direction_constraints.get("environment_scope")
    if environment_scope == "indoor_only":
        sentences.append("Keep the entire video indoors only.")
    elif environment_scope == "outdoor_only":
        sentences.append("Keep the entire video outdoors only.")
    elif environment_scope == "indoor_outdoor_mixed":
        sentences.append("Allow both indoor and outdoor settings within the same piece.")
    elif environment_scope == "underground":
        sentences.append("Keep the setting underground.")
    elif environment_scope == "underwater":
        sentences.append("Keep the setting underwater.")
    elif environment_scope == "water_surface":
        sentences.append("Keep the setting on or immediately above the water surface.")
    elif environment_scope == "aerial":
        sentences.append("Keep the viewpoint in the air or high above the ground.")
    elif environment_scope == "space":
        sentences.append("Keep the setting in outer space.")

    subject_tags = direction_constraints.get("subject_tags")
    if isinstance(subject_tags, list):
        tags = [str(tag).strip() for tag in subject_tags if str(tag).strip()]
        if tags:
            readable_map = {
                "architecture": "architecture",
                "interior_space": "interior spaces",
                "urban_infrastructure": "urban infrastructure",
                "outdoor_ruins": "outdoor ruins",
                "natural_landforms": "natural landforms",
                "vegetation": "vegetation",
                "water_features": "water features",
                "wildlife": "wildlife",
                "vehicles": "vehicles",
                "machinery": "machinery",
                "celestial_bodies": "celestial bodies",
            }
            readable_tags = [readable_map.get(tag, tag) for tag in tags]
            sentences.append(_ensure_sentence(f"Visually focus on these subjects: {', '.join(readable_tags)}"))

    allow_still_frames = direction_constraints.get("allow_still_frames")
    if allow_still_frames is False:
        sentences.append("Avoid still or frozen-looking frames.")

    camera_motion = direction_constraints.get("camera_motion")
    if camera_motion == "mostly_static":
        sentences.append("Keep camera movement mostly static and restrained.")
    elif camera_motion == "gentle":
        sentences.append("Use gentle, continuous camera movement.")
    elif camera_motion == "continuous":
        sentences.append("Keep the camera moving continuously.")

    visual_energy = direction_constraints.get("visual_energy")
    if visual_energy == "calm":
        sentences.append("Keep the visuals calm and controlled.")
    elif visual_energy == "vivid":
        sentences.append("Keep the visuals vivid and full of life.")
    elif visual_energy == "intense":
        sentences.append("Keep the visuals intense and highly energetic.")

    cut_duration_policy = direction_constraints.get("cut_duration_policy")
    if cut_duration_policy == "uniform":
        sentences.append("Keep cut durations evenly distributed.")
    elif cut_duration_policy == "weighted":
        sentences.append("Use intentionally varied cut durations with weighted emphasis.")
    elif cut_duration_policy == "variable":
        sentences.append("Cut durations do not need to be evenly distributed.")

    subject_focus = direction_constraints.get("subject_focus")
    if subject_focus == "people_primary":
        sentences.append("Keep people as the primary visual focus of the composition whenever they appear on screen.")
    elif subject_focus == "scene_primary":
        sentences.append(
            "Even if people appear on screen, keep the environment, scenery, and overall scene as the primary visual focus rather than individual people."
        )

    freeform_constraints = direction_constraints.get("freeform_constraints")
    if isinstance(freeform_constraints, str) and freeform_constraints.strip():
        sentences.append(_ensure_sentence(freeform_constraints))

    if direction_constraints.get("live_action_only") is True:
        sentences.append("Render the entire video as fully live-action footage with no animated or illustrative look.")

    if direction_constraints.get("ultra_high_resolution_8k") is True:
        sentences.append("Render the entire video in ultra high resolution 8K quality.")

    return sentences


def compile_movie_instructions(content_flags: dict | None, direction_constraints: dict | None) -> List[str]:
    """弱い構造化メタデータを、動画モデルが解釈しやすい自然文の文配列へ変換する。"""
    sentences = _compile_content_flags_to_sentences(content_flags)
    sentences.extend(_compile_direction_constraints_to_sentences(direction_constraints))
    return [sentence for sentence in sentences if sentence]


def compile_movie_requirements_text(content_flags: dict | None, direction_constraints: dict | None) -> str:
    """弱い構造化メタデータを、LLM補助用の箇条書きテキストへ変換する。"""
    sentences = compile_movie_instructions(content_flags, direction_constraints)
    return "\n".join(f"- {sentence}" for sentence in sentences)


def build_movie_json_payload(summary: str, details: List[str], scope: str, key: str) -> str:
    """動画用コアを最小化したJSON文字列にする。

    Plan A: Sora Web/iOS向けに `prompt` を単一文字列で保持し、冗長な summary/details を残さない。
    `scope`/`key` 引数は呼び出し互換のため残すが、実体は prompt に集約する。
    """
    payload = {"prompt": (summary or "").strip()}
    return json.dumps(payload, ensure_ascii=False)


def prepend_attached_image_world_description(movie_tail: str, enabled: bool) -> str:
    """添付画像世界トグルON時に、video_style.description の先頭へ前置きを加える。"""
    normalized_tail = str(movie_tail or "").strip()
    if not enabled:
        return normalized_tail

    if not normalized_tail:
        return json.dumps(
            {"video_style": {"description": ATTACHED_IMAGE_WORLD_DESCRIPTION_PREFIX}},
            ensure_ascii=False,
        )

    try:
        payload = json.loads(normalized_tail)
    except Exception:
        return normalized_tail

    if not isinstance(payload, dict):
        return normalized_tail

    video_style = payload.get("video_style")
    if not isinstance(video_style, dict):
        video_style = {}
        payload["video_style"] = video_style

    current_description = " ".join(str(video_style.get("description", "")).split()).strip()
    if current_description.startswith(ATTACHED_IMAGE_WORLD_DESCRIPTION_PREFIX):
        return json.dumps(payload, ensure_ascii=False)

    if current_description:
        video_style["description"] = f"{ATTACHED_IMAGE_WORLD_DESCRIPTION_PREFIX} {current_description}"
    else:
        video_style["description"] = ATTACHED_IMAGE_WORLD_DESCRIPTION_PREFIX
    return json.dumps(payload, ensure_ascii=False)


def compose_movie_prompt(
    core_json: str,
    movie_tail: str,
    flags_tail: str,
    direction_tail: str,
    options_tail: str,
) -> str:
    """Sora向けに video_prompt ルートへ統合したJSONを返す（最小構造）。

    - core_json   : prompt または storyboard を含むJSON文字列/辞書/プレーンテキスト
    - movie_tail  : {"video_style": {...}}
    - flags_tail  : {"content_flags": {...}}
    - direction_tail: {"direction_constraints": {...}}
    - options_tail : MJオプション（動画では無視）
    """

    def _parse_json_block(raw):
        if raw is None:
            return None
        if isinstance(raw, dict):
            return raw
        text = str(raw).strip()
        if not text:
            return None
        try:
            return json.loads(text)
        except Exception:
            return None

    base_payload = {"video_prompt": {}}

    core = _parse_json_block(core_json)
    if core:
        if "video_prompt" in core and isinstance(core["video_prompt"], dict):
            base_payload["video_prompt"].update(core["video_prompt"])
        else:
            # storyboardがあれば保持
            if isinstance(core.get("storyboard"), dict):
                base_payload["video_prompt"]["storyboard"] = core["storyboard"]
            # promptがあれば文字列化して格納
            if isinstance(core.get("prompt"), str):
                base_payload["video_prompt"]["prompt"] = core["prompt"]
            # world_descriptionにsummaryがあれば prompt に取り込む（後方互換）
            if "prompt" not in base_payload["video_prompt"] and isinstance(core.get("world_description"), dict):
                summary = core["world_description"].get("summary", "")
                if summary:
                    base_payload["video_prompt"]["prompt"] = summary
            # それでも無ければ core全体を文字列化して prompt に落とす
            if "prompt" not in base_payload["video_prompt"]:
                base_payload["video_prompt"]["prompt"] = json.dumps(core, ensure_ascii=False)
    else:
        text = str(core_json or "").strip()
        if text:
            base_payload["video_prompt"]["prompt"] = text

    video_style = _parse_json_block(movie_tail)
    if video_style and "video_style" in video_style:
        base_payload["video_prompt"]["video_style"] = video_style["video_style"]

    flags = _parse_json_block(flags_tail)
    if flags and "content_flags" in flags:
        base_payload["video_prompt"]["content_flags"] = flags["content_flags"]

    direction_constraints = _parse_json_block(direction_tail)
    if direction_constraints and "direction_constraints" in direction_constraints:
        base_payload["video_prompt"]["direction_constraints"] = direction_constraints["direction_constraints"]

    prompt_text = strip_compiled_movie_requirements(base_payload["video_prompt"].get("prompt", ""))
    if prompt_text or "prompt" in base_payload["video_prompt"]:
        base_payload["video_prompt"]["prompt"] = prompt_text

    compiled_instructions = compile_movie_instructions(
        base_payload["video_prompt"].get("content_flags"),
        base_payload["video_prompt"].get("direction_constraints"),
    )
    if compiled_instructions:
        base_payload["video_prompt"]["instructions"] = compiled_instructions

    # Sora Web/iOS では --ar などのMJオプションは不要なので options_tail は無視する

    # 空要素を取り除く（promptは空でもキーを残す）
    vp = base_payload["video_prompt"]
    cleaned = {k: v for k, v in vp.items() if v is not None and v != ""}
    base_payload["video_prompt"] = cleaned
    return json.dumps(base_payload, ensure_ascii=False, indent=2)
