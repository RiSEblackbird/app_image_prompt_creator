from __future__ import annotations

import logging
import os
import re
import time
from typing import List, Optional, Tuple

import requests
from PySide6 import QtCore

from . import config
from .logging_utils import get_exception_trace


def _normalize_language_code(code: Optional[str]) -> str:
    """UI入力などで与えられた言語コードを 'en' / 'ja' に正規化する。"""
    return "ja" if code == "ja" else "en"


def _language_directives(code: Optional[str]) -> Tuple[str, str, str]:
    """LLMプロンプトに埋め込む言語指定（コード/ラベル/指示文）をまとめて返す。"""
    normalized = _normalize_language_code(code)
    if normalized == "ja":
        label = "Japanese"
        instruction = (
            "Output language: Japanese. Respond ONLY in Japanese sentences except for unavoidable proper nouns."
        )
    else:
        label = "English"
        instruction = "Output language: English. Respond ONLY in English sentences."
    return normalized, label, instruction


def _should_use_responses_api(model_name: str) -> bool:
    if not model_name:
        return False
    target = model_name.strip().lower()
    return any(target.startswith(prefix) for prefix in config.RESPONSES_MODEL_PREFIXES)


def _build_responses_input(system_prompt: str, user_prompt: str):
    def build_block(role: str, text: str):
        return {
            "role": role,
            "content": [
                {
                    "type": "input_text",
                    "text": text or "",
                }
            ],
        }

    blocks = []
    if system_prompt is not None:
        blocks.append(build_block("system", system_prompt))
    blocks.append(build_block("user", user_prompt or ""))
    return blocks


def _temperature_hint_for_responses(model_name: str, temperature: float) -> str:
    if temperature is None:
        return ""
    if not _should_use_responses_api(model_name):
        return ""
    level = "balanced"
    if temperature <= 0.35:
        level = "precision / low randomness"
    elif temperature >= 0.75:
        level = "bold / high creativity"
    hint = (
        "\n\n[Legacy temperature emulation]\n"
        f"- Treat creativity strength as {level} (legacy temperature {temperature:.2f}).\n"
        "- Mirror the randomness level implied above even though the API ignores `temperature`.\n"
        "- Lower values mean deterministic phrasing; higher values allow freer rewording and bolder stylistic exploration."
    )
    return hint


def _append_temperature_hint(prompt_text: str, model_name: str, temperature: float) -> str:
    hint = _temperature_hint_for_responses(model_name, temperature)
    if hint:
        return f"{prompt_text}{hint}"
    return prompt_text


def _compose_openai_payload(
    system_prompt: str, user_prompt: str, temperature: float, max_tokens: int, include_temperature: bool, model_name: str
):
    model = model_name or config.LLM_MODEL
    use_responses = _should_use_responses_api(model)
    payload = {"model": model}
    if use_responses:
        payload["input"] = _build_responses_input(system_prompt, user_prompt)
        if max_tokens is not None:
            payload["max_output_tokens"] = max_tokens
        endpoint = config.RESPONSES_API_URL
        response_kind = "responses"
    else:
        payload["messages"] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        if max_tokens is not None:
            payload["max_completion_tokens"] = max_tokens
        endpoint = config.CHAT_COMPLETIONS_URL
        response_kind = "chat"
    send_temperature = include_temperature and (temperature is not None) and not use_responses
    if send_temperature:
        payload["temperature"] = temperature
    return endpoint, payload, response_kind


def _parse_openai_response(response_kind: str, data: dict):
    if response_kind == "responses":
        output = data.get("output", [])
        texts: List[str] = []
        finish_reason = ""
        for item in output or []:
            finish_reason = finish_reason or item.get("stop_reason", "")
            if item.get("type") != "message":
                continue
            for content in item.get("content", []):
                if content.get("type") in ("text", "output_text"):
                    texts.append(content.get("text", ""))
        if not texts:
            output_text = data.get("output_text")
            if isinstance(output_text, list):
                texts.append("".join(output_text))
            elif isinstance(output_text, str):
                texts.append(output_text)
        return "".join(texts).strip(), finish_reason or data.get("status", "")
    choices = data.get("choices", [])
    if not choices:
        return "", ""
    message = choices[0].get("message", {}) or {}
    text = (message.get("content") or "").strip()
    finish_reason = choices[0].get("finish_reason", "")
    return text, finish_reason


def _summarize_http_error_response(resp: requests.Response) -> str:
    """OpenAI HTTPエラーの概要を抽出し、リトライ判定やUI表示に使いやすい形にまとめる。"""
    if resp is None:
        return ""
    try:
        data = resp.json()
    except ValueError:
        data = None
    request_id = resp.headers.get("x-request-id") or resp.headers.get("x-requestid")
    summary = ""
    if isinstance(data, dict):
        err = data.get("error") or data
        if isinstance(err, dict):
            parts = []
            if err.get("message"):
                parts.append(f"message='{err['message']}'")
            if err.get("code"):
                parts.append(f"code={err['code']}")
            if err.get("type"):
                parts.append(f"type={err['type']}")
            summary = ", ".join(parts) or str(err)
        else:
            summary = str(err)
    else:
        raw_text = (resp.text or "").strip()
        if len(raw_text) > 600:
            raw_text = raw_text[:600] + "...(truncated)"
        summary = raw_text
    if request_id:
        return f"{summary} (request_id={request_id})"
    return summary


def _build_user_error_message(status_code, summary: str) -> str:
    """ユーザー通知用のLLMエラーメッセージを生成する。"""
    base = f"LLMリクエストに失敗しました (ステータス: {status_code})"
    if summary:
        return f"{base}: {summary}"
    return base


def _log_llm_failure(model_name: str, endpoint: str, status, message: str, retry_count: int):
    """サポート調査しやすいよう、構造化したエントリで失敗ログを残す。"""
    logging.error(
        "event=llm_request_failed model=%s endpoint=%s status=%s retries=%s message=\"%s\"",
        model_name or config.LLM_MODEL,
        endpoint,
        status,
        retry_count,
        message,
    )


def send_llm_request(
    api_key: str,
    system_prompt: str,
    user_prompt: str,
    temperature: float,
    max_tokens: int,
    timeout: int,
    model_name: str,
    include_temperature: bool = True,
):
    """OpenAI呼び出しを共通化し、限定的リトライとUI向けのエラー情報を併せて返す。"""
    endpoint, payload, response_kind = _compose_openai_payload(
        system_prompt, user_prompt, temperature, max_tokens, include_temperature, model_name
    )
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    retry_count = 0
    backoff = 1.0
    max_retries = 2
    while True:
        try:
            resp = requests.post(endpoint, headers=headers, json=payload, timeout=timeout)
            status = resp.status_code
            if (status == 429 or status >= 500) and retry_count < max_retries:
                summary = _summarize_http_error_response(resp)
                user_message = _build_user_error_message(status, summary)
                _log_llm_failure(model_name, endpoint, status, user_message, retry_count)
                retry_count += 1
                time.sleep(backoff)
                backoff *= 2
                continue
            resp.raise_for_status()
            data = resp.json()
            text, finish_reason = _parse_openai_response(response_kind, data)
            return text, finish_reason, data, retry_count, "", status
        except requests.exceptions.HTTPError as http_err:
            resp = getattr(http_err, "response", None)
            status = resp.status_code if resp is not None else "unknown"
            summary = _summarize_http_error_response(resp)
            user_message = _build_user_error_message(status, summary)
            _log_llm_failure(model_name, endpoint, status, user_message, retry_count)
            if isinstance(status, int) and (status == 429 or status >= 500) and retry_count < max_retries:
                retry_count += 1
                time.sleep(backoff)
                backoff *= 2
                continue
            return "", "", None, retry_count, user_message, status
        except requests.exceptions.RequestException as req_err:
            status = getattr(getattr(req_err, "response", None), "status_code", "network_error")
            user_message = _build_user_error_message(status, str(req_err))
            _log_llm_failure(model_name, endpoint, status, user_message, retry_count)
            if retry_count < max_retries:
                retry_count += 1
                time.sleep(backoff)
                backoff *= 2
                continue
            return "", "", None, retry_count, user_message, status


def sanitize_to_english(text: str) -> str:
    """基本的に英語出力を維持するための軽いサニタイズ。"""
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
    for k, v in replacements.items():
        out = out.replace(k, v)
    return out


def _extract_anchor_terms(text: str, max_terms: int = 8) -> List[str]:
    """原文から保持すべきアンカー語句（名詞・象徴語）を抽出する。"""
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
        for t in tokens:
            score = 1
            lt = t.lower()
            if lt in priority:
                score += 3
            if any(
                k in lt
                for k in ["garden", "temple", "shrine", "lantern", "blossom", "bamboo", "maple", "tea", "zen"]
            ):
                score += 1
            scored.append((score, t))
        scored.sort(reverse=True)
        anchors = []
        seen = set()
        for _, w in scored:
            lw = w.lower()
            if lw not in seen:
                anchors.append(w)
                seen.add(lw)
            if len(anchors) >= max_terms:
                break
        return anchors
    except Exception:
        return []


def _generate_hybrid_cues(anchors: List[str], preset: str, guidance: str, max_items: int = 5) -> List[str]:
    """アンカー語をスタイル語彙と合成し、ハイブリッド化を促すサジェストを生成する。"""
    try:
        if not anchors:
            return []
        preset_l = (preset or "").lower()
        guidance_l = (guidance or "").lower()

        keys = [preset_l, guidance_l]
        style = "generic"
        if any("cyber" in k for k in keys):
            style = "cyberpunk"
        elif any("noir" in k for k in keys):
            style = "noir"
        elif any(k in ("sci-fi", "scifi", "science fiction") for k in keys):
            style = "scifi"
        elif any("vapor" in k for k in keys):
            style = "vaporwave"

        vocab = {
            "cyberpunk": {
                "materials": [
                    "brushed metal",
                    "titanium inlays",
                    "carbon-fiber",
                    "chromed edges",
                    "micro-etched steel",
                    "polymer plates",
                ],
                "lighting": [
                    "neon rim-light",
                    "cyan underglow",
                    "magenta accent light",
                    "dynamic LED seams",
                    "HUD glow",
                    "soft holographic glow",
                ],
                "vfx": ["holographic flicker", "pixel shimmer", "AR overlay", "scanline sheen", "volumetric haze"],
                "detail": ["micro-circuit veins", "fiber-optic threads", "embedded sensors", "heat vents", "panel seams", "thin cabling"],
            },
            "noir": {
                "materials": ["matte enamel", "lacquered wood", "worn steel", "velvet texture"],
                "lighting": ["hard rim-light", "moody backlight", "rain-soaked reflections", "venetian blind shadows"],
                "vfx": ["film grain", "soft bloom", "cigarette smoke wisps"],
                "detail": ["sleek rivets", "aged patina", "subtle scratches"],
            },
            "scifi": {
                "materials": ["brushed alloy", "ceramic composite", "graphene panels", "satin titanium"],
                "lighting": ["cool rim-light", "ambient panel glow", "bioluminescent accents"],
                "vfx": ["force-field shimmer", "ionized haze", "specular flares"],
                "detail": ["hex-mesh patterns", "micro-actuators", "servo joints"],
            },
            "vaporwave": {
                "materials": ["pastel plastic", "glossy acrylic", "pearlescent enamel"],
                "lighting": ["pink-cyan gradient glow", "retro grid light", "soft bloom"],
                "vfx": ["CRT scanlines", "pixel dust", "checkerboard reflections"],
                "detail": ["chrome trims", "90s decals", "retro stickers"],
            },
            "generic": {
                "materials": ["brushed metal", "ceramic-metal composite", "polished steel"],
                "lighting": ["edge underglow", "accent rim-light", "soft backlight"],
                "vfx": ["subtle holographic shimmer", "fine grain", "soft bloom"],
                "detail": ["micro-engraving", "thin inlays", "fiber threads"],
            },
        }
        lex = vocab.get(style, vocab["generic"])
        templates = [
            "{a} with {materials} accents and {lighting}",
            "{a} featuring {detail} and a hint of {vfx}",
            "part of the {a} converted to {materials} with {lighting}",
            "{a} showing {detail} beneath the surface and subtle {vfx}",
            "{a} integrating {materials} inlays and {lighting}",
        ]
        cues = []
        for i, a in enumerate(anchors):
            if len(cues) >= max_items:
                break
            t = templates[i % len(templates)]
            cue = t.format(
                a=a,
                materials=lex["materials"][i % len(lex["materials"])],
                lighting=lex["lighting"][i % len(lex["lighting"])],
                vfx=lex["vfx"][i % len(lex["vfx"])],
                detail=lex["detail"][i % len(lex["detail"])],
            )
            cues.append(cue)
        return cues
    except Exception:
        return []


class LLMWorker(QtCore.QObject):
    """LLM 呼び出しをバックグラウンドで実行するワーカー。UI スレッドをブロックしない。"""

    finished = QtCore.Signal(str)
    failed = QtCore.Signal(str)

    def __init__(self, text: str, model: str, length_hint: str, length_limit: int = 0, output_language: str = "en"):
        super().__init__()
        self.text = text
        self.model = model
        self.length_hint = length_hint
        self.length_limit = length_limit
        self.output_language = _normalize_language_code(output_language)

    @QtCore.Slot()
    def run(self):
        try:
            api_key = os.getenv(config.OPENAI_API_KEY_ENV)
            if not api_key:
                self.failed.emit(f"{config.OPENAI_API_KEY_ENV} が未設定です。環境変数にAPIキーを設定してください。")
                return

            limit_instruction = ""
            if self.length_limit > 0:
                limit_instruction = f"\nIMPORTANT: Strictly limit the output to under {self.length_limit} characters."
            _, language_label, language_sentence = _language_directives(self.output_language)

            user_prompt = (
                f"Length adjustment request (target: {self.length_hint})\n"
                f"Instruction: Adjust length ONLY. Preserve meaning, style, and technical parameters.\n"
                f"{language_sentence}\n"
                f"Text: {self.text}"
            )
            system_prompt = _append_temperature_hint(
                "You are a text length adjustment specialist. Keep style but meet length hint."
                + limit_instruction
                + f"\nRespond strictly in {language_label}.",
                self.model,
                config.LLM_TEMPERATURE,
            )
            content, finish_reason, _, retry_count, error_message, status_code = send_llm_request(
                api_key=api_key,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=config.LLM_TEMPERATURE,
                max_tokens=config.LLM_MAX_COMPLETION_TOKENS,
                timeout=config.LLM_TIMEOUT,
                model_name=self.model,
                include_temperature=config.LLM_INCLUDE_TEMPERATURE,
            )
            if error_message:
                self.failed.emit(f"{error_message} (リトライ回数: {retry_count}, ステータス: {status_code})")
                return
            if retry_count:
                logging.info("LLM length adjustment succeeded after retries=%s", retry_count)
            if finish_reason in config.LENGTH_LIMIT_REASONS:
                self.failed.emit("LLM応答がトークン制限に達しました。短くして再試行してください。")
                return
            self.finished.emit(content)
        except Exception:
            self.failed.emit(get_exception_trace())


class MovieLLMWorker(QtCore.QObject):
    """動画用整形のためにメインテキストをLLMで改良するワーカー。"""

    finished = QtCore.Signal(str)
    failed = QtCore.Signal(str)

    def __init__(
        self,
        text: str,
        model: str,
        mode: str,
        details: List[str],
        video_style: str = "",
        content_flags: str = "",
        length_limit: int = 0,
        output_language: str = "en",
    ):
        super().__init__()
        self.text = text
        self.model = model
        self.mode = mode
        self.details = details or []
        self.video_style = video_style
        self.content_flags = content_flags
        self.length_limit = length_limit
        self.output_language = _normalize_language_code(output_language)

    @QtCore.Slot()
    def run(self):
        try:
            api_key = os.getenv(config.OPENAI_API_KEY_ENV)
            if not api_key:
                self.failed.emit(f"{config.OPENAI_API_KEY_ENV} が未設定です。環境変数にAPIキーを設定してください。")
                return
            system_prompt, user_prompt = self._build_prompts()
            content, finish_reason, _, retry_count, error_message, status_code = send_llm_request(
                api_key=api_key,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=config.LLM_TEMPERATURE,
                max_tokens=config.LLM_MAX_COMPLETION_TOKENS,
                timeout=config.LLM_TIMEOUT,
                model_name=self.model,
                include_temperature=config.LLM_INCLUDE_TEMPERATURE,
            )
            if error_message:
                self.failed.emit(f"{error_message} (リトライ回数: {retry_count}, ステータス: {status_code})")
                return
            if retry_count:
                logging.info("Movie prompt transformation succeeded after retries=%s", retry_count)
            if finish_reason in config.LENGTH_LIMIT_REASONS:
                self.failed.emit("LLM応答がトークン制限に達しました。短くして再試行してください。")
                return
            self.finished.emit((content or "").strip())
        except Exception:
            self.failed.emit(get_exception_trace())

    def _build_prompts(self) -> Tuple[str, str]:
        detail_lines = "\n".join(f"- {d}" for d in self.details)

        style_instruction = ""
        if self.video_style:
            style_instruction = (
                f"\n\n[Target Video Style]\n{self.video_style}\n"
                "IMPORTANT: Adapt the visual description (lighting, camera movement, atmosphere) "
                "to strictly match the parameters defined in the Target Video Style above."
            )
        content_flags_instruction = ""
        if self.content_flags:
            content_flags_instruction = (
                f"\n\n[Content Flags]\n{self.content_flags}\n"
                "IMPORTANT: Reflect these audio/subtitle/text overlay indicators explicitly in the rewritten description."
            )
        style_context_block = ""
        if style_instruction or content_flags_instruction:
            style_context_block = f"{style_instruction}{content_flags_instruction}\n"

        limit_instruction = ""
        if self.length_limit > 0:
            limit_instruction = f"\nIMPORTANT: Strictly limit the output summary to under {self.length_limit} characters."
        _, language_label, language_sentence = _language_directives(self.output_language)

        if self.mode == "world":
            system_prompt = _append_temperature_hint(
                "You refine disjoint visual fragments into one coherent world description for a single 10-second cinematic clip. "
                "Focus on the most impactful visual elements and atmosphere to fit the short duration. "
                f"Do not narrate events in sequence; describe one continuous world in natural {language_label}."
                f"{limit_instruction}\n{language_sentence}",
                self.model,
                config.LLM_TEMPERATURE,
            )
            user_prompt = (
                "Convert the following fragments into a single connected world description that fits a 10-second video.\n"
                "Omit minor details to keep it concise and impactful.\n"
                f"{style_context_block}"
                f"Source summary: {self.text}\n"
                f"Fragments:\n{detail_lines}\n"
                f"{language_sentence}\n"
                f"Output one concise paragraph that links every fragment into one world.{limit_instruction}"
            )
            return system_prompt, user_prompt

        system_prompt = _append_temperature_hint(
            "You craft a single continuous storyboard beat for a 10-second shot. "
            "Ensure actions and camera moves are simple enough to complete within 10 seconds, even if the pace is slightly fast. "
            f"Blend all elements into a flowing moment without hard scene cuts while writing in natural {language_label}."
            f"{limit_instruction}\n{language_sentence}",
            self.model,
            config.LLM_TEMPERATURE,
        )
        user_prompt = (
            "Turn the fragments into a 10-second single-shot storyboard.\n"
            "Condense the sequence to fit the time limit, merging or simplifying transitions where necessary.\n"
            f"{style_context_block}"
            f"Source summary: {self.text}\n"
            f"Fragments:\n{detail_lines}\n"
            f"{language_sentence}\n"
            f"Describe a vivid, fast-paced but coherent sequence in one paragraph, focusing on visual continuity.{limit_instruction}"
        )
        return system_prompt, user_prompt


class ChaosMixLLMWorker(QtCore.QObject):
    """断片化したメインプロンプトを単一シーンへ強制結合するワーカー。"""

    finished = QtCore.Signal(str)
    failed = QtCore.Signal(str)

    def __init__(
        self,
        text: str,
        fragments: List[str],
        model: str,
        video_style: str = "",
        content_flags: str = "",
        length_limit: int = 0,
        output_language: str = "en",
    ):
        super().__init__()
        self.text = text
        self.fragments = fragments or []
        self.model = model
        self.video_style = video_style
        self.content_flags = content_flags
        self.length_limit = length_limit
        self.output_language = _normalize_language_code(output_language)

    @QtCore.Slot()
    def run(self):
        try:
            api_key = os.getenv(config.OPENAI_API_KEY_ENV)
            if not api_key:
                self.failed.emit(f"{config.OPENAI_API_KEY_ENV} が未設定です。環境変数にAPIキーを設定してください。")
                return
            system_prompt, user_prompt = self._build_prompts()
            content, finish_reason, _, retry_count, error_message, status_code = send_llm_request(
                api_key=api_key,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=config.LLM_TEMPERATURE,
                max_tokens=config.LLM_MAX_COMPLETION_TOKENS,
                timeout=config.LLM_TIMEOUT,
                model_name=self.model,
                include_temperature=config.LLM_INCLUDE_TEMPERATURE,
            )
            if error_message:
                self.failed.emit(f"{error_message} (リトライ回数: {retry_count}, ステータス: {status_code})")
                return
            if retry_count:
                logging.info("Chaos mix succeeded after retries=%s", retry_count)
            if finish_reason in config.LENGTH_LIMIT_REASONS:
                self.failed.emit("LLM応答がトークン制限に達しました。短くして再試行してください。")
                return
            self.finished.emit((content or "").strip())
        except Exception:
            self.failed.emit(get_exception_trace())

    def _build_prompts(self) -> Tuple[str, str]:
        import uuid

        limit_instruction = ""
        if self.length_limit > 0:
            limit_instruction = f"\nIMPORTANT: Keep the final description under {self.length_limit} characters."
        _, language_label, language_sentence = _language_directives(self.output_language)
        language_block = f"\n{language_sentence}"

        detail_lines = "\n".join(f"- {sanitize_to_english(fragment)}" for fragment in self.fragments if fragment)
        if not detail_lines:
            detail_lines = "- (no sentence split detected)"

        anchor_terms = _extract_anchor_terms(self.text, max_terms=8)
        anchor_line = ", ".join(anchor_terms) if anchor_terms else "(none)"
        nonce = uuid.uuid4().hex[:8]

        style_instruction = ""
        if self.video_style:
            style_instruction = (
                f"\n\n[Target Video Style]\n{self.video_style}\n"
                "IMPORTANT: Even though this is a chaotic blended scene, camera work, lighting and atmosphere\n"
                "must still follow the Target Video Style above."
            )
        content_flags_instruction = ""
        if self.content_flags:
            content_flags_instruction = (
                f"\n\n[Content Flags]\n{self.content_flags}\n"
                "IMPORTANT: Preserve these audio/subtitle/text overlay requirements within the chaotic blended scene."
            )
        style_context_block = ""
        if style_instruction or content_flags_instruction:
            style_context_block = f"{style_instruction}{content_flags_instruction}\n"

        system_prompt = _append_temperature_hint(
            "You are a chaotic scene blender. Force every fragment from a Midjourney prompt to coexist in the same physical location and the same moment. "
            "Describe the result as one vivid, continuous tableau packed with overlapping motifs, lighting, and props. "
            f"Keep syntax clean, keep it in {language_label}, and never drop the essential nouns from the source."
            f"{limit_instruction}{language_block}",
            self.model,
            config.LLM_TEMPERATURE,
        )
        user_prompt = (
            "Task: Smash all fragments into a single overwhelming scene. Every subject must appear simultaneously; do NOT split into multiple shots.\n"
            "- Mention the collisions and impossible overlaps explicitly.\n"
            "- Keep anchor terms verbatim where possible.\n"
            "- Treat lighting/atmosphere cues as happening together.\n"
            f"- Output exactly one paragraph in {language_label}.\n"
            f"Nonce: {nonce}\n"
            f"{style_context_block}"
            f"Original prompt body:\n{sanitize_to_english(self.text)}\n\n"
            f"Sentence fragments:\n{detail_lines}\n"
            f"Anchor terms: {anchor_line}\n"
            "Output:"
        )
        return system_prompt, user_prompt


class ArrangeLLMWorker(QtCore.QObject):
    """画像プロンプトのアレンジ・リファインを実行するワーカー。"""

    finished = QtCore.Signal(str)
    failed = QtCore.Signal(str)

    def __init__(
        self,
        text: str,
        model: str,
        preset_label: str,
        strength: int,
        guidance: str,
        length_adjust: str,
        length_limit: int,
        output_language: str,
    ):
        super().__init__()
        self.text = text
        self.model = model
        self.preset_label = preset_label
        self.strength = strength
        self.guidance = guidance
        self.length_adjust = length_adjust
        self.length_limit = length_limit
        self.output_language = _normalize_language_code(output_language)

    @QtCore.Slot()
    def run(self):
        try:
            api_key = os.getenv(config.OPENAI_API_KEY_ENV)
            if not api_key:
                self.failed.emit(f"{config.OPENAI_API_KEY_ENV} が未設定です。環境変数にAPIキーを設定してください。")
                return

            # 文字数目標の計算
            original_length = len(self.text)
            length_multipliers = {
                "半分": 0.5,
                "2割減": 0.8,
                "同程度": 1.0,
                "2割増": 1.2,
                "倍": 2.0,
            }
            multiplier = length_multipliers.get(self.length_adjust, 1.0)
            target_length = int(original_length * multiplier)

            # ブレンド・アンカー・ハイブリッド
            blend_weight_map = {0: 20, 1: 35, 2: 65, 3: 80}
            blend_weight = blend_weight_map.get(self.strength, 55)
            anchor_terms = _extract_anchor_terms(self.text, max_terms=8)
            hybrid_cues = _generate_hybrid_cues(anchor_terms, self.preset_label, self.guidance, max_items=5)
            must_keep_count = 3 if self.strength <= 2 else 2

            strength_descriptions = {
                0: "Apply very subtle, minimal changes. Keep almost everything the same, just minor word improvements.",
                1: "Apply gentle, tasteful variations. Improve wording and style while keeping the core concept intact.",
                2: "Apply moderate creative variations. Enhance style, add vivid descriptors, and improve composition.",
                3: "Apply bold, creative transformations. Enhance style and add dramatic descriptors while preserving the original subject and key elements.",
            }
            strength_instruction = strength_descriptions.get(self.strength, strength_descriptions[2])

            system_prompt = ""
            user_prompt = ""

            import uuid

            nonce = uuid.uuid4().hex[:8]

            limit_instruction = ""
            if self.length_limit > 0:
                limit_instruction = f"\nIMPORTANT: Strictly limit the output to under {self.length_limit} characters."
            _, _, language_sentence = _language_directives(self.output_language)
            language_block = f"\n{language_sentence}"

            # 強度3用のプロンプト
            if self.strength == 3:
                system_prompt = (
                    f"You are a creative prompt artist. Transform this Midjourney prompt with {strength_instruction}. "
                    f"If guidance is provided, it SHOULD influence style but MUST BLEND with the original content. "
                    f"Do NOT eliminate original cultural/subject elements; preserve and merge them with the guidance. "
                    f"Be BOLD and CREATIVE - enhance the visual style with dramatic effects and vivid cinematic language. "
                    f"Output only the transformed prompt.{limit_instruction}{language_block}"
                )
                user_prompt = (
                    f"Preset: {self.preset_label}, Strength: {self.strength} (MAXIMUM CREATIVITY)\n"
                    f"Nonce: {nonce}\n"
                    + (f"Guidance: {self.guidance}\n" if self.guidance else "")
                    + f"Blend weight target: ~{blend_weight}% guidance / ~{100 - blend_weight}% original\n"
                    + (f"Anchor terms (verbatim): {', '.join(anchor_terms)}\n" if anchor_terms else "")
                    + f"CRITICAL: Include at least {must_keep_count} of the anchor terms verbatim. Keep the original subject and cultural motifs.\n"
                    + ("Hybridization suggestions: " + "; ".join(hybrid_cues) + "\n" if hybrid_cues else "")
                    + f"Length adjustment: {self.length_adjust} (target: ~{target_length} chars, original: {original_length} chars)\n"
                    + f"CRITICAL: Make the output {'shorter' if target_length < original_length else 'longer' if target_length > original_length else 'similar'} than the original\n"
                    + f"{language_sentence}\n"
                    + f"Prompt: {self.text}{limit_instruction}"
                )
            else:
                # 通常(0-2)用のプロンプト
                guidance_instruction = ""
                if self.strength == 0:
                    guidance_instruction = "Apply guidance very subtly if at all. Focus on minimal improvements."
                elif self.strength == 1:
                    guidance_instruction = "Apply guidance gently. Blend it subtly with the original content."
                elif self.strength == 2:
                    guidance_instruction = "Apply guidance moderately. Enhance the style while keeping core elements."

                system_prompt = (
                    f"Rewrite Midjourney prompts with {strength_instruction}. "
                    f"{guidance_instruction} "
                    f"Keep core content. Output only the prompt.{limit_instruction}{language_block}"
                )
                user_prompt = (
                    f"Preset: {self.preset_label}, Strength: {self.strength} (0=minimal, 3=bold)\n"
                    f"Nonce: {nonce}\n"
                    + (f"Guidance: {self.guidance}\n" if self.guidance else "")
                    + f"Guidance instruction: {guidance_instruction}\n"
                    f"Blend weight target: ~{blend_weight}% guidance / ~{100 - blend_weight}% original\n"
                    + (f"Anchor terms (verbatim): {', '.join(anchor_terms)}\n" if anchor_terms else "")
                    + f"CRITICAL: Include at least {must_keep_count} of the anchor terms verbatim. Keep the original subject and cultural motifs.\n"
                    + ("Hybridization suggestions: " + "; ".join(hybrid_cues) + "\n" if hybrid_cues else "")
                    + f"Length adjustment: {self.length_adjust} (target: ~{target_length} chars, original: {original_length} chars)\n"
                    + f"CRITICAL: Make the output {'shorter' if target_length < original_length else 'longer' if target_length > original_length else 'similar'} than the original\n"
                    + f"{language_sentence}\n"
                    + f"Prompt: {self.text}{limit_instruction}"
                )

            if not system_prompt or not user_prompt:
                self.failed.emit("プロンプト構築に失敗しました。")
                return

            content, finish_reason, _, retry_count, error_message, status_code = send_llm_request(
                api_key=api_key,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=config.LLM_TEMPERATURE,
                max_tokens=config.LLM_MAX_COMPLETION_TOKENS,
                timeout=config.LLM_TIMEOUT,
                model_name=self.model,
                include_temperature=config.LLM_INCLUDE_TEMPERATURE,
            )
            if error_message:
                self.failed.emit(f"{error_message} (リトライ回数: {retry_count}, ステータス: {status_code})")
                return
            if retry_count:
                logging.info("Arrange prompt succeeded after retries=%s", retry_count)
            if finish_reason in config.LENGTH_LIMIT_REASONS:
                self.failed.emit("LLM応答がトークン制限に達しました。短くして再試行してください。")
                return
            self.finished.emit((content or "").strip())
        except Exception:
            self.failed.emit(get_exception_trace())


class GeneratePromptLLMWorker(QtCore.QObject):
    """通常生成をLLMでまとめて行うワーカー。行数と属性条件からプロンプト群を生成する。"""

    finished = QtCore.Signal(str)
    failed = QtCore.Signal(str)

    def __init__(
        self,
        model: str,
        total_lines: int,
        attribute_conditions: List[dict],
        exclusion_words: List[str],
        chaos_level: int,
        output_language: str = "en",
    ):
        super().__init__()
        self.model = model
        self.total_lines = max(1, int(total_lines) if total_lines else 1)
        self.attribute_conditions = attribute_conditions or []
        self.exclusion_words = exclusion_words or []
        self.output_language = output_language if output_language in ("en", "ja") else "en"
        try:
            level = int(chaos_level)
        except Exception:
            level = 1
        self.chaos_level = max(1, min(10, level))

    def _effective_temperature(self) -> float:
        """カオス度から、このワーカー専用の実効temperatureを算出する。"""
        base = config.LLM_TEMPERATURE if config.LLM_TEMPERATURE is not None else 0.7
        center_level = 5.0
        span = 0.6
        delta = (self.chaos_level - center_level) / 9.0
        temp = base + delta * span
        return max(0.1, min(1.5, temp))

    @QtCore.Slot()
    def run(self):
        try:
            api_key = os.getenv(config.OPENAI_API_KEY_ENV)
            if not api_key:
                self.failed.emit(f"{config.OPENAI_API_KEY_ENV} が未設定です。環境変数にAPIキーを設定してください。")
                return
            effective_temp = self._effective_temperature()
            system_prompt, user_prompt = self._build_prompts(effective_temp)
            content, finish_reason, _, retry_count, error_message, status_code = send_llm_request(
                api_key=api_key,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=effective_temp,
                max_tokens=config.LLM_MAX_COMPLETION_TOKENS,
                timeout=config.LLM_TIMEOUT,
                model_name=self.model,
                include_temperature=config.LLM_INCLUDE_TEMPERATURE,
            )
            if error_message:
                self.failed.emit(f"{error_message} (リトライ回数: {retry_count}, ステータス: {status_code})")
                return
            if retry_count:
                logging.info(
                    "Prompt LLM generation succeeded after retries=%s (chaos_level=%s, effective_temp=%.3f)",
                    retry_count,
                    self.chaos_level,
                    effective_temp,
                )
            if finish_reason in config.LENGTH_LIMIT_REASONS:
                self.failed.emit("LLM応答がトークン制限に達しました。行数を減らすかプロンプトを短くして再試行してください。")
                return
            self.finished.emit((content or "").strip())
        except Exception:
            self.failed.emit(get_exception_trace())

    def _build_prompts(self, temperature: float) -> Tuple[str, str]:
        """通常生成用の属性条件と除外語句から、LLMへのプロンプトを構築する。"""

        attr_lines: List[str] = []
        for cond in self.attribute_conditions:
            name = str(cond.get("attribute_name", "") or "")
            detail = str(cond.get("detail", "") or "")
            requested = cond.get("requested_count", 0) or 0
            if requested > 0:
                line = f"- {detail} (attribute: {name}, approx {requested} fragments)"
            else:
                line = f"- {detail} (attribute: {name})"
            attr_lines.append(line)

        if attr_lines:
            attr_block = "\n".join(attr_lines)
        else:
            attr_block = "- (no specific attribute constraints; freely mix subjects, environments, materials and styles)"

        if self.exclusion_words:
            excl_block = ", ".join(sorted({w for w in self.exclusion_words if w}))
        else:
            excl_block = "(none)"

        if self.chaos_level <= 2:
            chaos_desc = "very stable, low randomness"
        elif self.chaos_level <= 4:
            chaos_desc = "mild variation with mostly stable structure"
        elif self.chaos_level <= 6:
            chaos_desc = "noticeable creative variation without losing overall coherence"
        elif self.chaos_level <= 8:
            chaos_desc = "strongly varied, experimental compositions"
        else:
            chaos_desc = "maximum chaos: wild, highly unexpected compositions and mixtures"

        is_japanese = self.output_language == "ja"
        if is_japanese:
            language_label = "Japanese"
            language_sentence = (
                "Output language: Japanese. Return only Japanese text in each fragment; "
                "do not append English translations."
            )
        else:
            language_label = "English"
            language_sentence = (
                "Output language: English. Return only English text in each fragment; "
                "do not append Japanese translations."
            )

        system_prompt = _append_temperature_hint(
            "You generate diverse, high-quality prompt fragments for image generation models like Midjourney. "
            "Follow the requested attribute mix and avoid forbidden words while keeping outputs concise and visual. "
            + language_sentence,
            self.model,
            temperature,
        )
        user_prompt = (
            f"Generate {self.total_lines} distinct prompt fragments for image generation in {language_label}.\n"
            "Formatting rules:\n"
            "- Output exactly one fragment per line.\n"
            "- Do NOT prepend numbers, bullets, or labels.\n"
            "- Each fragment should be a single concise sentence, compatible with Midjourney-style prompts.\n"
            "- Avoid producing identical fragments.\n\n"
            "Chaos control:\n"
            f"- Chaos level: {self.chaos_level} ({chaos_desc}).\n"
            "- Lower levels (1-3) should keep structure and style relatively consistent across fragments.\n"
            "- Medium levels (4-6) may change composition and style moderately, but keep subjects readable and not absurd.\n"
            "- Higher levels (7-10) may aggressively remix subjects, environments and materials; allow unusual angles and combinations.\n"
            "- At level 5 or above, ensure fragments feel clearly distinct and non-repetitive.\n\n"
            "Attribute preferences (approximate distribution across the fragments):\n"
            f"{attr_block}\n\n"
            "Words or themes to avoid (if these substrings appear, treat it as a hard prohibition): "
            f"{excl_block}\n\n"
            "If no attributes are given, create a varied but coherent mix of subjects, environments, materials, and visual styles."
        )
        return system_prompt, user_prompt
