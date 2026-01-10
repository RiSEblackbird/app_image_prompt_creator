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

## Sora2向けJSON形式（動画共通）

- すべての動画系出力は `video_prompt` ルートを持つ単一JSONに統合されます（Web/iOS版Sora想定、API用ではありません）。
- Midjourney系オプション（`--ar` など）は動画モードでは付与しません。

正例（最小形）:
```json
{
  "video_prompt": {
    "prompt": "A serene zen garden at dawn with soft mist.",
    "video_style": {"scope": "full_movie", "description": "gentle cinematic look"},
    "content_flags": {"narration": true, "bgm": true, "planned_cuts": 3}
  }
}
```

負例（Sora Web/iOSでは推奨しない）:
```
<prompt> --ar 16:9 --s 200
```
※ 動画モードで `--ar` などのMJオプションを足さないでください。

---

## ストーリーボード

「ストーリーボード」タブでは、複数カット構成の動画用プロンプトを時系列で管理できます。

### 基本操作

1. **テンプレートを選択**: カット構成のテンプレートを選びます
2. **総尺を設定**: 10〜30秒（5秒刻み）から選択（LLM自動構成ON時は目安値）
3. **カット生成方法を選択**:
   - **「テンプレートから初期化」**: 選択したテンプレートでカットを生成
   - **「現在のプロンプトから生成」**: 出力欄のプロンプトを文単位で分割してカット化
   - **「カット数/尺をLLM自動決定」**: ONにするとLLMがプロンプト内容からカット数(目安:3〜6)と総尺(目安:8〜24秒)を推定し、duration_sec付きで返します。OFFの場合は手動指定のカット数・総尺をそのまま使います。
4. **各カットを編集**: 説明、開始時刻、尺、カメラワークを設定
5. **「JSON出力&コピー」**: ストーリーボードをJSON形式でコピー

### プロンプトからのLLM生成

「現在のプロンプトから生成(LLM)」ボタンを押すと、出力欄のプロンプト全文（末尾固定部含む）をLLMで解析し、シネマティックなカットに分割します。

- プロンプト全文がLLMに送信されます
- **元の言語が維持されます**（日本語のプロンプトは日本語のまま）
- LLMがカット数に応じてシーンを分割し、カメラワークも提案します
- 生成後、各カットを手動で編集できます
- Soraの入力上限（約2000文字）を考慮し、LLMに「JSON全体を1900文字以内に収め、必要なら各カットの description だけを簡潔化する」指示を付与しています（メタ情報やカメラ指定は維持）
  - 正例: 3カット合計1500文字 → そのまま生成（1900文字未満）
  - 負例: 5カットで長文化しがちな場合 → LLMがdescription表現を圧縮して1900文字内を目指す

### テキスト欄への反映

「テキスト欄に反映」ボタンを押すと、出力欄をストーリーボードJSONで上書きします。

### テンプレート

| テンプレート | 説明 |
|--------------|------|
| （テンプレートなし） | カットを均等配分 |
| 画像スタート（呪縛解除） | 添付画像から始めて0.3秒でシーンにジャンプ。Soraで画像添付時の「静止画問題」を解消 |
| オープニング重視 | 導入カットを総尺の40%に |
| クライマックス重視 | 最終カットを総尺の40%に |

> **画像呪縛解除テンプレートについて**: Soraに画像を添付して動画生成すると、その画像に忠実であろうとするあまりほぼ静止画のような動画になることがあります。0.0秒を添付画像、0.3秒目に「シーンにジャンプ」と指示することで、画像の構図は維持しつつ動きのある動画が生成されやすくなります。

### 連続性強化

「連続性強化」チェックボックスを有効にすると、LLM生成時に「各カットの冒頭で前のカットから滑らかに遷移するよう描写せよ」という指示がLLMに追加されます。

**重要**: 定型的なフォーマット（`(Following: ...)` など）は使用しません。代わりに、LLMがカット説明自体に遷移の描写を自然に織り込みます。

**例**:
- カット1: 「夜明け前、まだ薄暗い空の下に広がる東京のパノラマ...」
- カット2: 「空が次第に明るさを増し、朝日がビルのガラスに反射し始めた新宿の高層ビル街...」

2番目のカットは「空が次第に明るさを増し」という遷移表現から始まり、前のカット（夜明け前）から自然に繋がっています。

- **LLM生成時**: 連続性強化が有効ならLLMが自動的に遷移を織り込む
- **手動編集時**: `continuity_enhanced: true` フラグがJSONに記録される（描写は手動で調整）

### LLM自動構成（カット数/尺の自動決定）

- 「カット数/尺をLLM自動決定」をONにすると、カット数(目安:3〜6)と総尺(目安:8〜24秒)をLLMが推定し、`duration_sec` 付きで返します。総尺は推定値が優先され、UIのプルダウンは目安表示として扱います。
- スタイル反映・連続性強化の指示は自動構成でも有効です。

正例（ON、プロンプト全文から自動構成）:
```json
{
  "total_duration_sec": 12.4,
  "cuts": [
    {"cut": 1, "duration_sec": 3.6, "description": "A misty alpine lake at blue hour...", "camera": "drone"},
    {"cut": 2, "duration_sec": 4.0, "description": "The camera glides closer...", "camera": "tracking"},
    {"cut": 3, "duration_sec": 4.8, "description": "Sunlight breaks through...", "camera": "zoom_out"}
  ]
}
```

負例（NG例: duration_sec を含まない配列を手動で貼り付けると均等割りになり、意図した尺配分になりません）:
```
[
  {"cut": 1, "description": "opening", "camera": "pan"},
  {"cut": 2, "description": "ending", "camera": "static"}
]
```
→ 各カットに `duration_sec` を付けるか、自動構成をOFFにして総尺・カット数を手動指定してください。

### スタイル反映

「スタイル反映」チェックボックスを有効にすると、入力プロンプトから抽出した `video_style`（カメラ・照明・雰囲気）と `content_flags`（音声・人物・テロップ情報）をLLMに背景補足情報として渡します。

**効果**: 各カットの説明がスタイルや制約に自然に沿った内容になります。LLMはこれらの情報をそのまま出力するのではなく、雰囲気や演出意図を描写に反映させます。

**例**: `video_style` に「フィルム調・暖色系の照明」が設定されている場合、カット説明には「暖かな光に包まれた」「フィルムグレインが漂う」といった表現が自然に織り込まれます。

### 出力例

入力プロンプトに含まれる `video_style` や `content_flags` は自動抽出され、`video_prompt` ルートにまとめて配置されます。これにより各カットの説明に冗長なメタデータを含めずに済みます。

```json
{
  "video_prompt": {
    "video_style": {
      "scope": "full_movie",
      "description": "atmospheric 1960s film print",
      "grade": "film emulation"
    },
    "content_flags": {
      "narration": false,
      "bgm": true,
      "ambient_sound": true,
      "dialogue": true
    },
    "storyboard": {
      "total_duration_sec": 10,
      "template": "image_unbind",
      "continuity_enhanced": true,
      "cuts": [
        {
          "index": 0,
          "start_sec": 0.0,
          "duration_sec": 0.3,
          "description": "[Attached image]",
          "is_image_placeholder": true
        },
        {
          "index": 1,
          "start_sec": 0.3,
          "duration_sec": 9.7,
          "description": "The scene within this image comes alive as the camera begins to move, revealing the world...",
          "camera_work": "zoom_out",
          "characters": ["@example.character1"]
        }
      ]
    }
  }
}
```
> 時間指定は `start_sec` + `duration_sec` で表し、`end` は冗長のため持ちません（`end = start + duration` で導出）。内部では0.01秒単位に丸めますが、誤差吸収のため最後のカットで総尺に合わせて微調整します。より厳密にしたい場合はミリ秒整数（`start_ms`/`duration_ms`）へ拡張してください。

---

## Soraキャラクター

Soraに登録したキャラクターをストーリーボードのカットに埋め込むことができます。

### 設定ファイル

`sora_characters.yaml` を作成してキャラクター情報を定義します（サンプルは `sora_characters.yaml.example` を参照）。

```yaml
characters:
  - id: "@abc.alien"
    name: "タコ足配線くん"
    pronoun_3rd: "彼"
```

| フィールド | 説明 |
|------------|------|
| `id` | Soraに登録したキャラクターの識別子（@で始まる） |
| `name` | UIに表示する名前 |
| `pronoun_3rd` | 三人称代名詞（彼/彼女/それ等） |

> **注意**: `sora_characters.yaml` は個人情報を含むため gitignore 対象です。リポジトリにはコミットされません。

### キャラクター一覧ダイアログ

「キャラクター一覧...」ボタンで一覧ダイアログを開き、各フィールドの値をクリップボードにコピーできます。

### プロンプトからの自動検出
- 出力欄に `@...` が含まれている場合、それをキャラクターIDとして検出し、ストーリーボード全カットの `characters` に付与します（各カットでの言及文面はシーン次第でLLMに任せます）。
- 未登録のIDが見つかると「不足キャラクターの登録」ダイアログが開き、名前（必須）と3人称（任意）を入力して `sora_characters.yaml` に追記するか、「登録せず続行」を選べます。キャンセルすると生成を中断します。
- 正例: `@example.character1 深夜の高速道路で追跡劇` → 自動で `["@example.character1"]` が全カットに付き、JSONの `cuts[].characters` に反映。
- 負例: `foo@bar.com` のようなメールアドレスは検出対象外（@直前が英数字のため）。

---

## LLM機能

### アレンジ
`arrange_presets.yaml` から読み込んだプリセット（ファンタジー、サイバーパンク、和風、ゴシック等）と強度スライダー（0-3）で出力を味付けします。強度0は最小限、3は大胆なアレンジです。

### 文字数調整
文章の意味を維持したまま、半分〜倍の範囲または固定文字数で調整します。

### 対応モデル
| モデル | API |
|--------|-----|
| gpt-5.2 | Responses API（デフォルト） |
| gpt-5.1 | Responses API |
| gpt-4o | Chat Completions |
| gpt-4o-mini | Chat Completions |

画面右上のドロップダウンでモデルを即時切替できます。gpt-5系（gpt-5.2 / gpt-5.1）は Responses API を使用するため、temperature の代わりにシステムプロンプトで強弱を指示します。

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
> **動画モードでは自動付与しません**（Sora Web/iOS向け最適化のため）。

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
  SORA_CHARACTERS_YAML: "app_image_prompt_creator/sora_characters.yaml"
  LLM_ENABLED: true
  LLM_MODEL: "gpt-5.2"
  LLM_MAX_COMPLETION_TOKENS: 4500
  LLM_TIMEOUT: 30
  OPENAI_API_KEY_ENV: "OPENAI_API_KEY"
  LLM_INCLUDE_TEMPERATURE: false
```

| キー | 説明 |
|------|------|
| `SORA_CHARACTERS_YAML` | Soraキャラクター定義ファイルのパス |
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
