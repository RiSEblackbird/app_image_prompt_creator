# AGENTS.md

## Overview

PySide6デスクトップアプリ。画像生成AI（Midjourney等）と動画生成AI（Sora等）の
プロンプト作成ツール。詳細は @README.md を参照。

## Commands

```bash
# 起動
python app_image_prompt_creator/app_image_prompt_creator_qt.py

# テスト
python -m pytest tests/test_generate_text_qt.py -v

# 必須ファイル確認
python scripts/check_required_files.py
```

## Project Structure

エントリポイント: `app_image_prompt_creator_qt.py`
メインウィンドウ: `app_image_prompt_creator_2.py`（肥大化中。責務追加禁止）
機能モジュール: `modules/` 配下に関心事ごとに分離。
新機能は `modules/` に独立モジュールとして作成すること。

## Research-First Policy

改修提案前に、関連する画像/動画生成モデルおよび周辺ツールの
最新動向をWeb検索で調査し、妥当性を考察してから着手する。
プロンプトテンプレートやLLMシステムプロンプトの変更時は、
対象モデルの公式ドキュメントおよび評価の高い非公式ソースで
ベストプラクティスを調査し、採用根拠を回答に含めること。

## Do

- PySide6を使う（PyQtではない）
- YAML設定はsettings_loaderを経由する
- LLMモデル切替時はResponses API / Chat Completionsの分岐を意識する
- 動画系出力はvideo_promptルートの単一JSONに統合する（Sora向け）
- 新機能は `modules/` 配下に独立モジュールとして作成する

## Don't

- 動画モードでMidjourneyオプション(--ar等)を付与しない
- `app_image_prompt_creator_2.py` / `_qt.py` にこれ以上の責務を追加しない

## Safety

Allowed without asking: ファイル読み取り、lint、単体テスト実行
Ask first: 依存追加/削除、DBスキーマ変更、設定フォーマット変更

## Known Gotchas

- gpt-5系はtemperature未対応。`LLM_INCLUDE_TEMPERATURE: false` を確認
- ストーリーボードJSON全体はSora入力上限 ≈2000文字
- 画像/動画生成AIの仕様は頻繁に変わる。疑わしい場合はWeb検索で確認
