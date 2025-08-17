# 画像プロンプトランダム生成ツール

<img width="1246" height="1102" alt="image" src="https://github.com/user-attachments/assets/4c5c9c6d-c324-4343-827c-9a678fe4ddaf" />

## 概要
Midjourney 向けの画像生成プロンプトを、SQLite の属性データからランダム合成して生成するデスクトップツールです。GUI で「どの属性をどれくらい使うか」を指定し、抽出・整形した文を自動で結合します。さらに、LLM を用いた英語出力の「アレンジ（味変）」と「文字数調整」も搭載し、作例づくりから量産までを効率化します。

このツールは以下のようなユースケースを想定しています。
- Midjourney 用の英語プロンプトを多数作りたい
- 属性（被写体・環境・マテリアル・画風など）から特徴を組み合わせたい
- `--ar`, `--s`, `--chaos`, `--q`, `--weird` などのオプションを簡単に付与したい
- LLM で英語表現を軽く磨きたい／強めに味変したい
- 依頼用途で「同テーマのバリエーション」を素早く作りたい

## 主な機能
- **属性ベース生成**: DBの属性を組み合わせてプロンプトを生成
- **ランダム化**: 指定行数ぶんをランダム抽出・整形
- **Midjourneyオプション付与**: `--ar`, `--s`, `--chaos`, `--q`, `--weird`
- **除外語句**: CSV管理。入力内容は自動追記・再利用可能
- **CSVインポート/エクスポート**: DBへの投入ウィンドウと、確認用エクスポート
- **クリップボード**: 全文コピー、オプション部のみコピー
- **アレンジ（LLM）**: プリセット＋強度スライダーで英語出力に味付け
- **プリセットYAML**: `arrange_presets.yaml` から読込
- **文字数調整（LLM）**: 「半分/2割減/同程度/2割増/倍」や固定文字数を指定して調整

### 追加の特長
- **自動整形**: 末尾の句読点を補正し、文単位で自然につながるよう軽く整形します
- **自動反映モード**: UI 変更を随時反映できるため、試行錯誤が高速
- **詳細なエラーダイアログ**: LLM 実行時の失敗要因をまとめて表示・コピー可能
- **Windows/Mac/Linux 対応のCSVオープン**: 除外語句CSVをOS標準エディタで開けます

## 前提／セットアップ
- **Python**: 3.10+ 推奨
- **依存ライブラリ**: `requests`, `PyYAML`
```bash
pip install requests PyYAML
```
- **設定ファイル**: `app_image_prompt_creator/desktop_gui_settings.yaml`
  - 例は `app_image_prompt_creator/desktop_gui_settings.yaml.example`
- **OpenAI APIキー**: 環境変数に設定（例: PowerShell）
```powershell
setx OPENAI_API_KEY "sk-xxxxx"
```

他シェルでの例:
- Windows (cmd.exe):
  ```bat
  setx OPENAI_API_KEY "sk-xxxxx"
  ```
- macOS/Linux (bash/zsh):
  ```bash
  export OPENAI_API_KEY="sk-xxxxx"
  ```

## 起動方法
```bash
python app_image_prompt_creator/app_image_prompt_creator_2.py
```

起動後、右側にメイン設定、左側に出力欄とサブ操作が表示されます。初回は DB の前提テーブル（後述）が用意されている必要があります。

## 使い方（基本）
1. **属性を選ぶ**
   - 各属性タイプのプルダウンから特徴を選択
   - 使用回数を 0-10 の範囲で指定
2. **行数の入力**
   - 生成する行数を入力（例: 10）
   - 「自動反映」をオンにするとUI変更で自動更新
3. **オプション設定**
   - 末尾固定文（任意）
   - `--ar`, `--s`, `--chaos`, `--q`, `--weird` を選択
4. **除外語句（任意）**
   - カンマ区切りで入力。ONのとき検索条件に反映、CSVに追記
   - 「除外語句CSVを開く」で履歴CSVをエディタで開く
5. **生成とコピー**
   - 「生成」→ 出力欄に表示
   - 「生成とコピー（全文）」／「クリップボードにコピー(全文)」
   - 「クリップボードにコピー(options)」でオプションのみ

### ワークフロー例
- 例1: 「被写体×環境×質感」を各2行ずつ、合計10行で生成 → 和風テイストの固定文を足し、`--ar 16:9 --s 200` を付与 → そのままコピー
- 例2: まずは生成のみ → 出力を見て除外語句に「rain, crowd」を追加 → 再生成 → 「アレンジ(LLM)」でプリセット「和風」を強度1で味付け → コピー

## アレンジ機能（LLM）
- **プリセット**: `app_image_prompt_creator/arrange_presets.yaml` から読込（例: ファンタジー、サイバーパンク、和風、浮世絵、ゴシック、アール・デコ、アール・ヌーヴォー、アニメ、漫画、水彩画、ノワール、ヴェイパーウェーブ、パステル 等）
- **強度スライダー（0-3）**
  - 0: 最小限、1: 穏やか、2: 中程度、3: 大胆
  - スライダー上に0.3秒ホバーで日本語ツールチップ
- **実行**: 「アレンジ(LLM)」/「アレンジしてコピー(LLM)」
- **英語出力ポリシー**: LLMへ英語出力を要求。混入した日本語の代表語は英訳へ置換
- **再試行**: 同一内容などの際は内部で再試行（最大2回）
- **エラー時**: 詳細エラーダイアログを表示（内容のコピー可）

アレンジは「原文の主題・構図を保ちつつ、言い回しや質感描写を磨く」ことを目標にしています。強度3ではより大胆なスタイルブレンドを試みますが、元の重要語句（アンカー）を維持するよう指示されます。モデルが `temperature` に非対応の場合は自動で温度パラメータを外すフォールバックを試行します。

## 文字数調整機能（LLM）
- **設定**:
  - 「半分 / 2割減 / 同程度 / 2割増 / 倍」から選択
  - 「固定」文字数を指定した場合は固定が優先
- **実行**:
  - 「文字数調整のみ」/「文字数調整してコピー」
- **ポリシー**:
  - 文章の意味や構図、末尾の `--options` を維持したまま文字数のみを調整
  - 短縮時は強く圧縮する指示を付与。精度担保のため内部でノンス付与

短縮が必要な場合は「長さ優先で攻める」ガイダンスを内部付与します。冗長語の削除、形容表現の集約、短い同義語への置換などで強く圧縮します。拡張の場合は主題を変えずに描写の密度を上げます。

## CSVインポート/エクスポート
- **インポート**: 「CSVをDBに投入」ボタンでウィンドウが開き、CSVを貼り付けて「投入」
  - 期待フォーマット（1行1レコード）
    ```csv
    "<content>","<attribute_detail_id_1,attribute_detail_id_2,...>"
    ```
  - 例:
    ```csv
    "A serene zen garden with stone lantern.","12,34,56"
    ```
  - 貼付け内容から `prompts` と `prompt_attribute_details` に登録します
- **エクスポート**: 「(DB確認用CSV出力)」で現在のDB内容を確認用CSVに出力

補足:
- 行頭末尾はダブルクォートで囲んでください（ツール側で `","` で分割）
- 行が空、または `citation[oaicite` を含む行、````` を含む行はスキップされます
- 3重クォート `"""` は自動で `"` に置換してから処理します

## Midjourneyオプション
- **--ar**: 16:9 / 9:16 / 4:3 / 3:4
- **--s**: 0-1000
- **--chaos**: 0-100
- **--q**: 1-2
- **--weird**: 0-3000

各オプションはチェックボックスで有効化し、プルダウンから値を選びます。出力欄右の「optionsのみコピー」で末尾の `--options` のみを取得できます。

## 設定ファイル（desktop_gui_settings.yaml）
- 主なキー
  - `POSITION_FILE`: ウィンドウ位置記録（互換目的。保存/復元は現状オフ）
  - `BASE_FOLDER`: 本アプリのベースフォルダ
  - `DEFAULT_TXT_PATH`: プロンプト部品テキスト（任意）
  - `DEFAULT_DB_PATH`: SQLite3 DBパス
  - `EXCLUSION_CSV`: 除外語句CSV
  - `ARRANGE_PRESETS_YAML`: アレンジプリセットYAMLのパス
  - `LLM_ENABLED`: LLM機能の有効/無効
  - `LLM_MODEL`: 例 `gpt-5-mini`
  - `LLM_MAX_COMPLETION_TOKENS`: 応答最大トークン（アレンジ/文字数調整共通）
  - `LLM_TIMEOUT`: タイムアウト秒
  - `OPENAI_API_KEY_ENV`: APIキーの環境変数名（例 `OPENAI_API_KEY`）
  - `LLM_INCLUDE_TEMPERATURE`: temperature を送るか（未対応モデルもあるため既定は false 推奨）
  - `LLM_TEMPERATURE`: 送る場合の値

例（抜粋）:
```yaml
app_image_prompt_creator:
  BASE_FOLDER: "/path/to/base"
  DEFAULT_DB_PATH: "app_image_prompt_creator/data.sqlite3"
  EXCLUSION_CSV: "app_image_prompt_creator/exclusions.csv"
  ARRANGE_PRESETS_YAML: "app_image_prompt_creator/arrange_presets.yaml"
  LLM_ENABLED: true
  LLM_MODEL: "gpt-5-mini"
  LLM_MAX_COMPLETION_TOKENS: 4500
  LLM_TIMEOUT: 30
  OPENAI_API_KEY_ENV: "OPENAI_API_KEY"
  LLM_INCLUDE_TEMPERATURE: false
  LLM_TEMPERATURE: 0.7
```

### プリセットYAMLの仕様
`arrange_presets.yaml` は以下のような配列を含みます。各要素は `id`（内部キー）、`label`（UIに表示）、`guidance`（任意の説明/指示）を持ちます。
```yaml
presets:
  - id: "auto"
    label: "auto"
    guidance: ""
  - id: "和風"
    label: "和風"
    guidance: "和素材・照明・質感を穏やかにブレンド"
  - id: "cyberpunk"
    label: "サイバーパンク"
    guidance: "neon, brushed metal, holographic glow を織り交ぜる"
```

YAML が読めない場合はコード内のフォールバックプリセットが使用されます。

## 注意事項/既知の挙動
- **ウィンドウ位置保存**: コード上は保存/復元処理がコメントアウトされており、現状は無効（互換目的でキーのみ保持）
- **オプション保持**: LLMアレンジ/文字数調整では末尾の `--options` を維持する前提
- **英語出力**: 基本は英語で出力。代表的な日本語語句は最終段で英訳に置換
- **DB前提**: `attribute_types` / `attribute_details` が事前に用意されている前提で動作します

補足:
- `prompts` / `prompt_attribute_details` はCSV投入時に存在しなければ自動作成されます
- `attribute_types` / `attribute_details` は本ツールでは作成しないため、別途準備が必要です
- 除外語句 CSV はフレーズ（カンマ区切り文字列）として保存され、重複登録は抑制されます
- OS ごとの既定エディタ呼び分け: Windowsは Notepad、macOSは TextEdit、Linuxは `xdg-open`

## トラブルシューティング
- **LLMが動かない**
  - `desktop_gui_settings.yaml` の `LLM_ENABLED: true` を確認
  - `OPENAI_API_KEY_ENV` で示される環境変数にAPIキーを設定
  - ネットワーク疎通やモデル名の有効性を確認
  - エラーダイアログの「エラー詳細をコピー」で報告用ログを取得
- **除外語句が反映されない**
  - チェックボックスがオンか確認
  - CSVに追記されているか確認（重複防止のためフレーズ単位で保存）

追加のヒント:
- HTTP 400 + `temperature` が原因の場合は `LLM_INCLUDE_TEMPERATURE: false` にする、または対応モデルへ切替
- タイムアウトが出る場合は `LLM_TIMEOUT` を延ばす、ネットワーク状態を確認
- `finish_reason: length` が発生する場合は `LLM_MAX_COMPLETION_TOKENS` を増やすか、入力プロンプトを短縮
- APIキー未設定時はGUIに警告が出ます。環境変数名が設定と一致しているか確認

## データベース前提（参考）
本ツールは以下のテーブルを前提に動作します（名称は固定）。

- `attribute_types`: `id`, `attribute_name`, `description`
- `attribute_details`: `id`, `attribute_type_id`, `description`, `value`
- `prompts`: `id`, `content`（CSV投入で作成/追記）
- `prompt_attribute_details`: `prompt_id`, `attribute_detail_id`（CSV投入で作成/追記）

生成時は、選択した属性に紐づく `prompts.content` を JOIN で抽出し、指定回数だけランダムサンプリングします。残数は全体からランダム補完され、最後に文の末尾記号を簡易整形して結合します。

## よくある質問（FAQ）
- **なぜ英語出力なのですか？**
  - Midjourney では英語の方が安定した挙動になりやすいため、基本は英語出力を採用しています。混入した代表的な日本語は最終段で英訳へ置換します。
- **日本語のニュアンスは残せますか？**
  - アレンジ時にプリセットやガイダンスを和風寄せにする、固定文で和要素を補うなどで方向性を維持できます。
- **大量生成はできますか？**
  - 行数を増やして繰り返し生成・コピーしてください。DBに十分な `prompts` があるほど多彩になります。
- **モデル／APIコストは？**
  - LLM機能を使う操作（アレンジ/文字数調整）のみAPIを呼びます。モデルや利用量に応じた課金をご確認ください。

## 開発・拡張のヒント
- 属性の追加: `attribute_types` と `attribute_details` に行を追加することで UI に自動反映されます（content_count>0 の詳細のみ選択肢に表示）
- プリセット追加: `arrange_presets.yaml` に `id/label/guidance` を追加
- オプション初期値の変更: `app_image_prompt_creator_2.py` の定数や YAML 側の値を調整
- エラーハンドリング: LLM 部分は詳細ログを標準出力へ出します。必要に応じてログ収集を追加してください

