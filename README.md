# 画像・動画プロンプト生成ツール

<img width="800" alt="image" src="https://github.com/user-attachments/assets/97f16892-7b02-45ca-824d-b7929db4d002" />

## 概要

画像生成AI（Midjourney等）と動画生成AI（Sora2等）の両方に対応したプロンプト作成デスクトップツールです。SQLite の属性データからランダム合成する「DB生成」と、LLM で直接生成する「LLM生成」の2モードを搭載しています。

| 用途 | 画像生成 | 動画生成 |
|------|----------|----------|
| 属性ベースのプロンプト合成 | ✓ | ✓ |
| 末尾プリセット | `image` プリセット | `movie` プリセット（JSON） |
| オプション付与 | `--ar`, `--s`, `--chaos` 等 | `video_style` / `content_flags` |
| LLMアレンジ・文字数調整 | ✓ | ✓ |
| JSON構造化出力 | — | `world_description` / `storyboard` |

---

## 機能一覧

### 共通
- **属性ベース生成**: 被写体・環境・質感・画風などの属性を組み合わせてプロンプトを生成
- **生成モード**: DB生成（ランダム抽出）または LLM生成（1回のAPIで指定行数を生成）
- **除外語句**: CSV管理で入力内容を自動追記・再利用
- **LLMアレンジ**: プリセットと強度スライダーで出力を味付け
- **文字数調整**: 半分〜倍の範囲または固定文字数で調整
- **フォントスケール**: 標準→大→特大→4Kの4段階でUI全体を拡大

### 画像生成向け
- **Midjourneyオプション**: `--ar`, `--s`, `--chaos`, `--q`, `--weird` を付与
- **末尾プリセット（image）**: 高精細写真・イラスト向けの固定文

### 動画生成向け
- **末尾プリセット（movie）**: `{"video_style": ...}` JSON で動画スタイルを指定
- **content_flags**: ナレーション・BGM・字幕・カット数などをJSONで付与
- **JSON整形**: メインテキストを `world_description` や `storyboard` に変換
- **LLM改良**: 世界観整形 / ストーリー構築 / カオスミックス

---

## セットアップ

### 前提条件
- Python 3.10+
- 依存ライブラリ: `requests`, `PyYAML`, `PySide6`

```bash
pip install requests PyYAML PySide6
```

### 設定ファイル
`app_image_prompt_creator/desktop_gui_settings.yaml` を作成します。テンプレートは `desktop_gui_settings.yaml.example` を参照してください。

### APIキー
LLM機能を使用する場合は、OpenAI APIキーを環境変数に設定します。

```powershell
# Windows
setx OPENAI_API_KEY "sk-xxxxx"
```

```bash
# macOS / Linux
export OPENAI_API_KEY="sk-xxxxx"
```

### 起動

```bash
python app_image_prompt_creator/app_image_prompt_creator_qt.py
```

---

## 使い方

### 基本操作

1. **属性を選ぶ**: 各属性タイプのプルダウンから特徴を選択し、使用回数（0-10）を指定
2. **生成方法を選ぶ**: DB生成またはLLM生成を選択。LLM生成ではカオス度（1〜10）で創造性を調整できます
3. **末尾プリセットを選ぶ**: 画像向けなら `image`、動画向けなら `movie` を選択
4. **生成**: 「生成」ボタンで出力欄に表示、「生成とコピー」で即座にクリップボードへ

### 画像生成の例

```
[属性選択] → [image プリセット] → [Midjourney オプション] → [生成] → [コピー]
```

被写体・環境・質感を組み合わせて10行生成し、末尾プリセット `image` と `--ar 16:9 --s 200` を付与してコピーします。必要に応じて「アレンジ(LLM)」タブでプリセット（和風、ゴシック等）を適用して仕上げます。

### 動画生成の例

```
[属性選択] → [movie プリセット] → [content_flags] → [生成] → [JSON整形] → [コピー]
```

末尾プリセット `movie` で `{"video_style":...}` を選び、content_flags でナレーション・BGM・カット数などを設定して生成します。生成後、「動画用に整形(JSON)」パネルで「世界観整形」や「ストーリー構築」をクリックすると、断片的なプロンプトを自然な世界描写やストーリーボードに変換できます。

---

## 末尾プリセット

「末尾プリセット用途」で `image` / `movie` を切り替え、用途に応じた固定文を付与します。

### image プリセット
高解像度写真、8K、イラスト系の文末テキストを収録しています。

### movie プリセット
JSON形式で `video_style` を定義します。TV番組系（ニュース、旅番組、ドキュメンタリー等）、映画系（歴史超大作、青春映画、ファンタジー等）、報道・現地リポート、ロケ・体験番組など多数のカテゴリから選択できます。

> **注意**: `movie` 用プリセットを使う場合は、末尾プリセット用途を `movie` に切り替えてから選択してください。`image` のままだとJSONが正しく付与されません。

### プリセット定義ファイル

プリセットは `app_image_prompt_creator/tail_presets.yaml` で定義します。

```yaml
tails:
  image:
    - id: "photo_8k"
      description_ja: "超高解像度写真 (8K)"  # UIに表示される名前
      prompt: "A high resolution photograph. Very high resolution. 8K photo"
  movie:
    - id: "movie_70mm"
      description_ja: "70mmフィルムのシネマティック全編"
      prompt: "{\"video_style\":{...}}"
```

`description_ja` はUI表示専用で、プロンプトには `prompt` フィールドのみが付与されます。アプリ起動中にYAMLを保存すると自動でリロードされます。

---

## content_flags（動画専用）

左ペイン「スタイル・オプション」タブの「末尾2 (JSONフラグ)」グループで、動画のメタ情報をJSONとして付与します。

| 項目 | 説明 |
|------|------|
| 末尾2を反映 | マスタースイッチ。ONにしないとJSONは付与されません |
| ナレーション / BGM / 環境音 | 音声要素の有無 |
| 人物 / 人物のセリフ | 映像内の人物とセリフの有無 |
| セリフ字幕 / テロップ | 画面上のテキスト要素 |
| 登場人物 | なし / 1+ / 1〜4 / many（群衆） |
| 構成カット数 | Auto / 1〜6 / many（高速モンタージュ） |
| 動画中の言語 | Auto / 日本語 / 英語 |

出力例:
```json
{"content_flags":{"narration":true,"bgm":true,"ambient_sound":true,"planned_cuts":3,"spoken_language":"ja"}}
```

---

## 動画用JSON整形

「動画用に整形(JSON)」パネルで、メインテキストをJSON構造に変換します。

| モード | 説明 |
|--------|------|
| JSONデータ化 | LLMなしで単純にJSON化 |
| 世界観整形 | 断片を自然な世界描写へ変換 |
| ストーリー構築 | ストーリーボード形式に再構成 |
| カオスミックス | 全要素を1つの場面に押し込む |

「スタイル反映」をONにすると、選択中の `video_style` と `content_flags` がLLMへ伝達され、スタイルに沿った描写が生成されます。出力言語は英語/日本語から選択できます。

---

## LLM機能

### アレンジ
`arrange_presets.yaml` から読み込んだプリセット（ファンタジー、サイバーパンク、和風、ゴシック等）と強度スライダー（0-3）で出力を味付けします。強度0は最小限、3は大胆なアレンジです。

### 文字数調整
文章の意味を維持したまま、半分〜倍の範囲または固定文字数で調整します。

### 対応モデル
| モデル | API |
|--------|-----|
| gpt-4o-mini | Chat Completions（デフォルト） |
| gpt-4o | Chat Completions |
| gpt-5.1 | Responses API |

画面右上のドロップダウンでモデルを即時切替できます。gpt-5.1 では temperature の代わりにシステムプロンプトで強弱を指示します。

---

## Midjourneyオプション（画像専用）

| オプション | 範囲 |
|------------|------|
| `--ar` | 16:9 / 9:16 / 4:3 / 3:4 |
| `--s` | 0-1000 |
| `--chaos` | 0-100 |
| `--q` | 1-2 |
| `--weird` | 0-3000 |

チェックボックスで有効化し、プルダウンから値を選択します。「optionsのみコピー」で末尾の `--options` 部分だけを取得することもできます。

---

## CSVインポート/エクスポート

### インポート
「CSVをDBに投入」ボタンでウィンドウを開き、以下の形式でCSVを貼り付けます。

```csv
"<プロンプト内容>","<attribute_detail_id_1,attribute_detail_id_2,...>"
```

例:
```csv
"A serene zen garden with stone lantern.","12,34,56"
```

空行や不正な行はスキップされ、失敗した行は `failed_csv_rows_*.csv` に出力されます。

### エクスポート
「(DB確認用CSV出力)」で現在のDB内容を確認用CSVとして出力できます。

---

## 設定ファイル

`desktop_gui_settings.yaml` の主な設定項目:

```yaml
app_image_prompt_creator:
  DEFAULT_DB_PATH: "app_image_prompt_creator/data.sqlite3"
  EXCLUSION_CSV: "app_image_prompt_creator/exclusions.csv"
  ARRANGE_PRESETS_YAML: "app_image_prompt_creator/arrange_presets.yaml"
  LLM_ENABLED: true
  LLM_MODEL: "gpt-4o-mini"
  LLM_MAX_COMPLETION_TOKENS: 4500
  LLM_TIMEOUT: 30
  OPENAI_API_KEY_ENV: "OPENAI_API_KEY"
  LLM_INCLUDE_TEMPERATURE: false
```

| キー | 説明 |
|------|------|
| `LLM_ENABLED` | LLM機能の有効/無効 |
| `LLM_MODEL` | 使用モデル |
| `LLM_MAX_COMPLETION_TOKENS` | 応答最大トークン |
| `LLM_TIMEOUT` | タイムアウト秒 |
| `LLM_INCLUDE_TEMPERATURE` | temperature パラメータを送るか |

---

## トラブルシューティング

| 症状 | 対処 |
|------|------|
| LLMが動かない | `LLM_ENABLED: true` を確認、APIキーを設定、ネットワーク疎通を確認 |
| 除外語句が反映されない | チェックボックスがONか確認 |
| HTTP 400 + temperature エラー | `LLM_INCLUDE_TEMPERATURE: false` に設定 |
| タイムアウト | `LLM_TIMEOUT` を延長 |
| 応答が途中で切れる | `LLM_MAX_COMPLETION_TOKENS` を増加 |

エラーの詳細はダイアログの「エラー詳細をコピー」で取得できます。コンソールには `HTTPエラー詳細: message='...' (request_id=...)` が出力されます。

---

## データベース

本ツールは以下のテーブルを前提に動作します。

| テーブル | 用途 |
|----------|------|
| `attribute_types` | 属性タイプの定義（事前準備が必要） |
| `attribute_details` | 属性の詳細値（事前準備が必要） |
| `prompts` | プロンプト本文（CSV投入で作成） |
| `prompt_attribute_details` | プロンプトと属性の紐付け（CSV投入で作成） |

---

## FAQ

**Q: なぜ英語出力が推奨されていますか？**

Midjourney や Sora2 では英語の方が安定した挙動になりやすいためです。日本語出力が必要な場合は各UIで言語を切り替えられます。

**Q: APIコストはどのくらいかかりますか？**

LLM機能（LLM生成/アレンジ/文字数調整/JSON整形等）を使用したときのみAPIが呼び出されます。DB生成のみを使う場合はAPIは呼ばれません。LLM生成は行数に関わらず1回のリクエストで処理されます。

---

## 開発・拡張

- **属性を追加**: `attribute_types` / `attribute_details` テーブルに行を追加するとUIに自動反映されます
- **プリセットを追加**: `arrange_presets.yaml` / `tail_presets.yaml` にエントリを追加します
- **ログ確認**: LLM処理の詳細ログは標準出力に出力されます
