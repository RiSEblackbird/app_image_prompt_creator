# AGENTS.md

## Overview

PySide6デスクトップアプリ。画像生成AI（Midjourney等）と動画生成AI（Sora等）の
プロンプト作成ツール。詳細は @README.md を参照。

## Commands

```bash
# 起動
python app_image_prompt_creator_qt.py

# テスト
python -m pytest tests/test_generate_text_qt.py -v

# UIレイアウト/Qt挙動まわりを重点確認
python -m pytest tests/test_generate_text_qt.py -k "splitter or attribute" -v

# 必須ファイル確認
python scripts/check_required_files.py
```

## Testing Policy

- UIに限らず、改修時は「何が壊れていたか」を先に言語化し、その失敗を再現できるテストを優先して追加する
- 不具合修正では、対症療法ではなく根本原因を検知できる観点でテストを書く
- 新機能追加では、正例だけでなく主要な境界値・無効入力・回帰リスクも最低1つ確認する
- 既存不具合の再発防止として、修正コードだけでなく利用者操作や公開メソッド経由でも期待どおりになるかを確認する
- 完了報告前に、変更範囲に関係するテストを実行し、実行していない場合は未実行であることを明示する
- このリポジトリでは少なくとも `python -m pytest tests/test_generate_text_qt.py -v` を実行候補として確認する
- PySide6 のUI改修では、見た目だけで完了扱いにせず `tests/test_generate_text_qt.py` に再現テストを追加する
- レイアウト不具合では `isVisible()` だけでなく `sizes()` / `height()` / ハンドルのドラッグ結果まで確認する
- `QSplitter` の不具合確認では `moveSplitter()` だけでなく、可能なら `QtTest.QTest` で実ドラッグも検証する
- 折りたたみUIでは「展開時」「格納時」「格納後も仕切り操作可能か」を別ケースで確認する

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
