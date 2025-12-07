"""テキスト整形や末尾抽出など、UIに依存しないプロンプト処理ヘルパー。"""

from __future__ import annotations

import json
import re
from typing import List, Tuple


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


def detach_content_flags_tail(text: str) -> Tuple[str, str]:
    """
    content_flags を含む JSON ブロック({...})を末尾から探して取り出す。
    見つかった場合は (残りテキスト, content_flags JSON) を返す。
    """
    text = (text or "").strip()
    search_end = len(text) - 1

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
            if '"content_flags"' in candidate or "'content_flags'" in candidate:
                flags_tail = candidate
                remaining = (text[:start_idx] + " " + text[end_idx + 1 :]).strip()
                remaining = " ".join(remaining.split())
                return remaining, flags_tail
            search_end = start_idx - 1
        else:
            search_end = end_idx - 1

    return text, ""


def detach_movie_tail_for_llm(text: str) -> Tuple[str, str]:
    """
    video_style を含む JSON ブロック({...})を末尾から探して取り出す。
    見つかった場合は (残りテキスト, video_style JSON) を返す。
    """
    text = (text or "").strip()
    search_end = len(text) - 1

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
            if '"video_style"' in candidate or "'video_style'" in candidate:
                movie_tail = candidate
                remaining = (text[:start_idx] + " " + text[end_idx + 1 :]).strip()
                remaining = " ".join(remaining.split())
                return remaining, movie_tail
            search_end = start_idx - 1
        else:
            search_end = end_idx - 1

    return text, ""


def extract_sentence_details(text: str) -> List[str]:
    """句読点で分割した細部表現リストを返す。"""
    sentence_candidates = re.split(r"[。\.]\s*", text or "")
    details = [s.strip(" .　") for s in sentence_candidates if s.strip(" .　")]
    return details or [text.strip()]


def build_movie_json_payload(summary: str, details: List[str], scope: str, key: str) -> str:
    """world_description もしくは storyboard としてJSON文字列を生成する。"""
    payload = {
        key: {
            "scope": scope,
            "summary": (summary or "").strip(),
        }
    }
    return json.dumps(payload, ensure_ascii=False)


def compose_movie_prompt(core_json: str, movie_tail: str, flags_tail: str, options_tail: str) -> str:
    """生成したJSONと末尾要素（動画スタイル・末尾2フラグ・MJオプション）を安全に連結する。"""
    parts = [core_json]
    if movie_tail:
        parts.append(movie_tail.strip())
    if flags_tail:
        parts.append(flags_tail.strip())
    if options_tail:
        parts.append(options_tail.strip())
    return " ".join(p for p in parts if p)
