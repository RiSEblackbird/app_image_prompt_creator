# -*- coding: utf-8 -*-
# アプリ名: 9. 画像プロンプトランダム生成ツール

import sys
import os
import traceback
import subprocess
import tkinter as tk
import tkinter.filedialog
import tkinter.scrolledtext
from tkinter import filedialog, messagebox, ttk
from tkinter import font as tkfont
import random
import csv
import socket
import sqlite3
import yaml
import requests
from pathlib import Path
from export_prompts_to_csv import MJImage
import re

# 定数の定義
WINDOW_TITLE = "画像プロンプトランダム生成ツール"
LABEL_FILE = "Base txt"
BUTTON_SELECT = "選択"
LABEL_ROW_NUM = "行数: "
DEFAULT_ROW_NUM = 10
BUTTON_GENERATE = "生成"
BUTTON_ALL_COPY = "クリップボートにコピー(全文)"
BUTTON_OPTIONS_COPY = "クリップボートにコピー(options)"
FONT_SIZE = 16  # 基本フォントサイズ
SELECT_FILE_FONT_SIZE = 6
TAIL_FREE_FONT_SIZE = 10
OUTPUT_FONT_SIZE = 12
SUB_BUTTONS_FONT = 14
LABEL_TAIL_FREE1 = "末尾1: "
LABEL_TAIL_S     = "s オプション: "
LABEL_TAIL_AR    = "ar オプション: "
LABEL_TAIL_CHAOS = "chaos オプション: "
LABEL_TAIL_Q     = "q オプション: "
LABEL_TAIL_WEIRD = "weird オプション: "
LABEL_TAIL_MEDIA_TYPE = "末尾プリセット用途: "
DEFAULT_TAIL_MEDIA_TYPE = "image"
TAIL_PRESET_CHOICES = {
    # 静止画向けの末尾プリセット
    "image": [
        "",
        "A high resolution photograph. Very high resolution. 8K photo",
        "a Japanese ink painting. Zen painting",
        "a Medieval European painting."
    ],
    # 映像（動画）向けの末尾プリセット
    "movie": [
        "",
        "{\"video_style\":{\"scope\":\"full_movie\",\"description\":\"sweeping cinematic sequence shot on 70mm film\",\"look\":\"dramatic lighting\"}}",
        "{\"video_style\":{\"scope\":\"full_movie\",\"description\":\"dynamic tracking shot captured as ultra high fidelity footage\",\"format\":\"4K HDR\"}}",
        "{\"video_style\":{\"scope\":\"full_movie\",\"description\":\"moody arthouse short film\",\"camera\":\"deliberate movement\"}}",
        "{\"video_style\":{\"scope\":\"full_movie\",\"description\":\"fast-paced montage cut like a modern sci-fi trailer\",\"grade\":\"Dolby Vision\"}}"
    ]
}
S_OPTIONS = ["", "0", "10", "20", "30", "40", "50", "100", "150", "200", "250", "300", "400", "500", "600", "700", "800", "900", "1000"]
AR_OPTIONS = ["", "16:9", "9:16", "4:3", "3:4"]  # 'ar'オプションの項目
CHAOS_OPTIONS = ["", "0", "10", "20", "30", "40", "50", "60", "70", "80", "90", "100"]  # 'chaos'オプションの項目
Q_OPTIONS = ["", "1", "2"]
WEIRD_OPTIONS = ["", "0", "10", "20", "30", "40", "50", "100", "150", "200", "250", "500", "750", "1000", "1250", "1500", "1750", "2000", "2250", "2500", "2750", "3000"]  # 'weird'オプションの項目

SCRIPT_DIR = Path(__file__).resolve().parent

def _resolve_path(path_value, base_dir=SCRIPT_DIR):
    """
    受け取ったパスをスクリプト配置ディレクトリ基準で解決する。
    絶対パスが渡された場合はそのまま返す。
    """
    if path_value is None:
        return base_dir
    if isinstance(path_value, Path):
        path = path_value
    else:
        path = Path(str(path_value))
    if path.is_absolute():
        return path
    return base_dir / path

AVAILABLE_LLM_MODELS = [
    "gpt-5.1",
    "gpt-4o-mini",
    "gpt-4o"
]

LABEL_EXCLUSION_WORDS = "除外語句："
# DEFAULT_EXCLUSION_WORDS = ["", "sculpture", "ring", "rain", "sphere", "stature", "sphere, rain, people, sculpture"]

# OpenAIエンドポイントの定義（gpt-5系はResponses APIを要求する）
CHAT_COMPLETIONS_URL = "https://api.openai.com/v1/chat/completions"
RESPONSES_API_URL = "https://api.openai.com/v1/responses"
RESPONSES_MODEL_PREFIXES = ("gpt-5",)
LENGTH_LIMIT_REASONS = {"length", "max_output_tokens"}

# 定数としてホスト名を取得
HOSTNAME = socket.gethostname()

# YAMLファイルを読み込むための関数
def load_yaml_settings(file_path):
    """
    指定されたパスのYAMLファイルを読み込んで、設定を辞書として返す。
    """
    resolved_path = _resolve_path(file_path)
    with open(resolved_path, 'r', encoding="utf-8") as file:
        # yamlモジュールを使用して設定ファイルを読み込む
        settings = yaml.safe_load(file)
    return settings

## windowの位置を保存する機能は一旦コメントアウト(明示が無い限り削除しないで！)
# def save_position(root):
#     """
#     ウィンドウの位置とサイズをCSVファイルに保存する。
#     """
#     print("ウィンドウ位置を保存中...")
#     position_data = [HOSTNAME, root.geometry()]
#     print(f"保存データ: {position_data}")
#     with open(POSITION_FILE, 'w', newline='', encoding="utf_8_sig") as csvfile:
#         writer = csv.writer(csvfile)
#         writer.writerow(position_data)
#     print("保存完了")
#
# def restore_position(root):
#     """
#     CSVファイルからウィンドウの位置とサイズを復元する。
#     """
#     print("ウィンドウ位置を復元中...")
#     try:
#         with open(POSITION_FILE, newline='', encoding="utf_8_sig") as csvfile:
#             reader = csv.reader(csvfile)
#             for row in reader:
#                 if row[0] == HOSTNAME:
#                     print(f"復元データ: {row[1]}")
#                     root.geometry(row[1])
#                     break
#     except FileNotFoundError:
#         print("位置情報ファイルが見つかりません。")

# アプリケーションの終了時の処理をカスタマイズする
def on_close():
    # save_position(root)  # ウィンドウの位置を保存
    root.destroy()  # ウィンドウを破壊する

def get_exception_trace():
    '''例外のトレースバックを取得'''
    t, v, tb = sys.exc_info()
    trace = traceback.format_exception(t, v, tb)
    return trace

class DelayedTooltip:
    def __init__(self, widget, text_provider, delay=300):
        self.widget = widget
        self.text_provider = text_provider  # callable -> str
        self.delay = delay
        self._after_id = None
        self.tipwindow = None
        widget.bind('<Enter>', self._on_enter)
        widget.bind('<Leave>', self._on_leave)
        widget.bind('<ButtonPress>', self._on_leave)

    def _on_enter(self, event=None):
        self._schedule()

    def _on_leave(self, event=None):
        self._cancel()
        self._hide()

    def _schedule(self):
        self._cancel()
        self._after_id = self.widget.after(self.delay, self._show)

    def _cancel(self):
        if self._after_id:
            try:
                self.widget.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None

    def _show(self):
        if self.tipwindow is not None:
            return
        try:
            x, y = self.widget.winfo_pointerxy()
        except Exception:
            x = self.widget.winfo_rootx() + 10
            y = self.widget.winfo_rooty() + 10
        text = self.text_provider() if callable(self.text_provider) else str(self.text_provider)
        self.tipwindow = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x+12}+{y+12}")
        label = tk.Label(
            tw, text=text, justify='left', relief='solid', borderwidth=1,
            background='#ffffe0', foreground='#000000', padx=6, pady=4
        )
        label.pack(ipadx=1)

    def _hide(self):
        if self.tipwindow is not None:
            try:
                self.tipwindow.destroy()
            except Exception:
                pass
            self.tipwindow = None

class CSVImportWindow:
    def __init__(self, master, update_callback):
        self.window = tk.Toplevel(master)
        self.window.title("CSV Import")

        # "画像プロンプトランダム生成ツール" ウインドウの位置を取得
        master_x = master.winfo_x()
        master_y = master.winfo_y()

        # "画像プロンプトランダム生成ツール" ウインドウの少し右下側に設定
        offset_x = 50  # 右側へのオフセット
        offset_y = 50  # 下側へのオフセット
        self.window.geometry(f"500x355+{master_x + offset_x}+{master_y + offset_y}")
        
        self.update_callback = update_callback

        self.text_area = tk.Text(self.window, wrap=tk.WORD, width=25, height=6)
        self.text_area.pack(padx=10, pady=10, expand=True, fill=tk.BOTH)

        self.import_button = tk.Button(self.window, text="投入", command=self.import_csv)
        self.import_button.pack(pady=10)

    def import_csv(self):
        csv_content = self.text_area.get("1.0", tk.END).strip()
        if not csv_content:
            messagebox.showerror("エラー", "CSVデータを入力してください。")
            return

        try:
            self.process_csv(csv_content)
            messagebox.showinfo("成功", "CSVデータが正常に処理されました。")
            self.update_callback()  # コールバック関数を呼び出してUIを更新
            self.window.destroy()  # ウィンドウを閉じる
        except Exception as e:
            messagebox.showerror("エラー", f"CSVの処理中にエラーが発生しました: {get_exception_trace()}")

    def process_csv(self, csv_content):
        conn = sqlite3.connect(DEFAULT_DB_PATH)
        cursor = conn.cursor()

        cursor.execute('''
        CREATE TABLE IF NOT EXISTS prompts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content TEXT
        )
        ''')

        cursor.execute('''
        CREATE TABLE IF NOT EXISTS prompt_attribute_details (
            prompt_id INTEGER,
            attribute_detail_id INTEGER,
            FOREIGN KEY (prompt_id) REFERENCES prompts (id),
            FOREIGN KEY (attribute_detail_id) REFERENCES attribute_details (id)
        )
        ''')

        for line in csv_content.splitlines():
            try:
                if "citation[oaicite" in line or '```' in line: continue # ``` &#8203;:citation[oaicite:0]{index=0}&#8203;
                if line.strip() and len(line) > 10 and [line[0], line[-1]] == ['"', '"']:  # 空行をスキップ
                    # 最初と最後の引用符を削除し、中央のカンマで分割                
                    line = line.replace('"""', '"')
                    try:
                        content, attribute_detail_ids = line.strip('"').split('","')
                    except:
                        content, attribute_detail_ids = line.strip('"').split('", "')

                    cursor.execute('INSERT INTO prompts (content) VALUES (?)', (content,))
                    prompt_id = cursor.lastrowid
                    
                    for attribute_detail_id in attribute_detail_ids.split(','):
                        cursor.execute('INSERT INTO prompt_attribute_details (prompt_id, attribute_detail_id) VALUES (?, ?)',
                                    (prompt_id, int(attribute_detail_id)))
            except:
                messagebox.showerror("エラー", f"CSVの処理中にエラーが発生しました: line: [{line}], {get_exception_trace()}")
                raise Exception("投入プロセス強制終了")

        conn.commit()
        conn.close()

class TextGeneratorApp:
    def __init__(self, master):
        self.master = master
        self.master.title(WINDOW_TITLE)
        self.attribute_type_frames = {}
        self.attribute_detail_combos = {}
        self.attribute_count_combos = {}
        self.llm_model_var = tk.StringVar(value=LLM_MODEL)
        self.available_model_choices = list(dict.fromkeys([self.llm_model_var.get(), *AVAILABLE_LLM_MODELS]))
        self.load_attribute_data()

        # デフォルトフォントの設定
        self.default_font = tkfont.Font(size=FONT_SIZE)  # デフォルトフォントサイズ
        self.master.option_add("*Font", self.default_font)  # すべてのウィジェットにデフォルトフォントを適用
        self.select_file_font = tkfont.Font(size=SELECT_FILE_FONT_SIZE) # ファイル選択行のフォントサイズ
        self.tail_free_font = tkfont.Font(size=TAIL_FREE_FONT_SIZE)
        self.output_font = tkfont.Font(size=OUTPUT_FONT_SIZE)  # 出力エリアのフォントサイズ
        self.sub_buttons_font = tkfont.Font(size=SUB_BUTTONS_FONT)  # オプショナルボタンのフォント
        self.combo_font = tkfont.Font(family="Helvetica", size=12)  # フォントを指定

        # フレームの設定
        self.main_frame = tk.Frame(master)
        self.main_frame.pack(padx=10, pady=10, side='right')
        
        self.sub_frame = tk.Frame(master)
        self.sub_frame.pack(padx=10, pady=10, side='left')

        self.create_llm_model_selector_ui()
        
        # CSV投入ボタン（「行数」の上に移動）
        self.button_csv_import = tk.Button(self.main_frame, text="CSVをDBに投入", command=self.open_csv_import_window)
        self.button_csv_import.pack(pady=5, fill='x')

        # CSV出力ボタン
        self.button_csv_output = tk.Button(self.main_frame, text="(DB確認用CSV出力)", command=MJImage().run)
        self.button_csv_output.pack(pady=5, fill='x',)

        # 行数入力UI
        self.row_num_frame = tk.Frame(self.main_frame)
        self.row_num_frame.pack(fill='x')
        self.entry_row_num = tk.Entry(self.row_num_frame, width=5)
        self.entry_row_num.pack(side='right')
        self.entry_row_num.insert(0, DEFAULT_ROW_NUM)
        self.label_row_num = tk.Label(self.row_num_frame, text=LABEL_ROW_NUM)
        self.label_row_num.pack(side='left')
        
        # 属性メニュー
        self.create_attribute_type_ui()

        # 自動反映設定
        self.autofix_frame = tk.Frame(self.main_frame)
        self.autofix_frame.pack(fill='x')
        self.autofix_var = tk.BooleanVar()
        self.checkbox_autofix = tk.Checkbutton(self.autofix_frame, variable=self.autofix_var)
        self.checkbox_autofix.pack(side='right')
        self.label_autofix = tk.Label(self.autofix_frame, text="自動反映: ")
        self.label_autofix.pack(side='left')
        
        # 末尾プリセットの媒体種別を切り替えるUI
        self.tail_media_type_frame = tk.Frame(self.main_frame)
        self.tail_media_type_frame.pack(fill='x')
        self.tail_media_type_var = tk.StringVar(value=DEFAULT_TAIL_MEDIA_TYPE)
        self.label_tail_media_type = tk.Label(self.tail_media_type_frame, text=LABEL_TAIL_MEDIA_TYPE)
        self.label_tail_media_type.pack(side='left')
        self.combo_tail_media_type = ttk.Combobox(
            self.tail_media_type_frame,
            values=list(TAIL_PRESET_CHOICES.keys()),
            textvariable=self.tail_media_type_var,
            width=10,
            state="readonly"
        )
        self.combo_tail_media_type.pack(side='right')
        self.combo_tail_media_type.bind("<<ComboboxSelected>>", self.on_tail_media_type_change)

        # 末尾テキスト入力UI(固定文1)
        self.tail_free_text_frame1 = tk.Frame(self.main_frame)
        self.tail_free_text_frame1.pack(fill='x')
        self.add_tail_free_text_var1 = tk.BooleanVar()
        self.checkbox_tail_free_text1 = tk.Checkbutton(self.tail_free_text_frame1, variable=self.add_tail_free_text_var1, font=TAIL_FREE_FONT_SIZE)
        self.checkbox_tail_free_text1.pack(side='right')
        self.combo_tail_free_text1 = ttk.Combobox(
            self.tail_free_text_frame1,
            values=TAIL_PRESET_CHOICES[DEFAULT_TAIL_MEDIA_TYPE],
            width=25,
            font=TAIL_FREE_FONT_SIZE
        )
        self.combo_tail_free_text1.pack(side='right')
        self.combo_tail_free_text1.bind("<<ComboboxSelected>>", self.auto_update)
        self.label_tail_free_text1 = tk.Label(self.tail_free_text_frame1, text=LABEL_TAIL_FREE1)
        self.label_tail_free_text1.pack(side='left')
        self.update_tail_free_text_choices(reset_selection=True)

        # 末尾テキスト入力UI(--ar)
        self.tail_ar_text_frame = tk.Frame(self.main_frame)
        self.tail_ar_text_frame.pack(fill='x')
        self.add_tail_ar_text_var = tk.BooleanVar()
        self.checkbox_tail_ar_text = tk.Checkbutton(self.tail_ar_text_frame, variable=self.add_tail_ar_text_var)
        self.checkbox_tail_ar_text.pack(side='right')
        self.combo_tail_ar = ttk.Combobox(self.tail_ar_text_frame, values=AR_OPTIONS, width=5)
        self.combo_tail_ar.pack(side='right')
        self.combo_tail_ar.bind("<<ComboboxSelected>>", self.auto_update)
        self.label_tail_ar_text = tk.Label(self.tail_ar_text_frame, text=LABEL_TAIL_AR)
        self.label_tail_ar_text.pack(side='left')
        
        # 末尾テキスト入力UI(--s)
        self.tail_s_text_frame = tk.Frame(self.main_frame)
        self.tail_s_text_frame.pack(fill='x')
        self.add_tail_s_text_var = tk.BooleanVar()
        self.checkbox_tail_s_text = tk.Checkbutton(self.tail_s_text_frame, variable=self.add_tail_s_text_var)
        self.checkbox_tail_s_text.pack(side='right')
        self.combo_tail_s_text = ttk.Combobox(self.tail_s_text_frame, values=S_OPTIONS, width=5)
        self.combo_tail_s_text.pack(side='right')
        self.combo_tail_s_text.bind("<<ComboboxSelected>>", self.auto_update)
        self.label_tail_s_text = tk.Label(self.tail_s_text_frame, text=LABEL_TAIL_S)
        self.label_tail_s_text.pack(side='left')
        
        # 末尾テキスト入力UI(--chaos)
        self.tail_chaos_text_frame = tk.Frame(self.main_frame)
        self.tail_chaos_text_frame.pack(fill='x')
        self.add_tail_chaos_text_var = tk.BooleanVar()
        self.checkbox_tail_chaos_text = tk.Checkbutton(self.tail_chaos_text_frame, variable=self.add_tail_chaos_text_var)
        self.checkbox_tail_chaos_text.pack(side='right')
        self.combo_tail_chaos = ttk.Combobox(self.tail_chaos_text_frame, values=CHAOS_OPTIONS, width=5)
        self.combo_tail_chaos.pack(side='right')
        self.combo_tail_chaos.bind("<<ComboboxSelected>>", self.auto_update)
        self.label_tail_chaos_text = tk.Label(self.tail_chaos_text_frame, text=LABEL_TAIL_CHAOS)
        self.label_tail_chaos_text.pack(side='left')
        
        # 末尾テキスト入力UI(--q)
        self.tail_q_text_frame = tk.Frame(self.main_frame)
        self.tail_q_text_frame.pack(fill='x')
        self.add_tail_q_text_var = tk.BooleanVar()
        self.checkbox_tail_q_text = tk.Checkbutton(self.tail_q_text_frame, variable=self.add_tail_q_text_var)
        self.checkbox_tail_q_text.pack(side='right')
        self.combo_tail_q = ttk.Combobox(self.tail_q_text_frame, values=Q_OPTIONS, width=5)
        self.combo_tail_q.pack(side='right')
        self.combo_tail_q.bind("<<ComboboxSelected>>", self.auto_update)
        self.label_tail_q_text = tk.Label(self.tail_q_text_frame, text=LABEL_TAIL_Q)
        self.label_tail_q_text.pack(side='left')
        
        # 末尾テキスト入力UI(--weird)
        self.tail_weird_text_frame = tk.Frame(self.main_frame)
        self.tail_weird_text_frame.pack(fill='x')
        self.add_tail_weird_text_var = tk.BooleanVar()
        self.checkbox_tail_weird_text = tk.Checkbutton(self.tail_weird_text_frame, variable=self.add_tail_weird_text_var)
        self.checkbox_tail_weird_text.pack(side='right')
        self.combo_tail_weird = ttk.Combobox(self.tail_weird_text_frame, values=WEIRD_OPTIONS, width=5)
        self.combo_tail_weird.pack(side='right')
        self.combo_tail_weird.bind("<<ComboboxSelected>>", self.auto_update)
        self.label_tail_weird_text = tk.Label(self.tail_weird_text_frame, text=LABEL_TAIL_WEIRD)
        self.label_tail_weird_text.pack(side='left')
        
        # 除外語句入力UI
        self.exclusion_words_frame = tk.Frame(self.main_frame)
        self.exclusion_words_frame.pack(fill='x')
        self.add_exclusion_words_var = tk.BooleanVar()
        self.checkbox_exclusion_words = tk.Checkbutton(self.exclusion_words_frame, variable=self.add_exclusion_words_var)
        self.checkbox_exclusion_words.pack(side='right')
        self.combo_exclusion_words = ttk.Combobox(self.exclusion_words_frame, values=DEFAULT_EXCLUSION_WORDS, width=50)
        self.combo_exclusion_words.pack(side='right')
        self.combo_exclusion_words.bind("<<ComboboxSelected>>", self.auto_update)
        self.label_exclusion_words = tk.Label(self.exclusion_words_frame, text=LABEL_EXCLUSION_WORDS)
        self.label_exclusion_words.pack(side='left')

        # 生成ボタン
        self.button_generate = tk.Button(self.main_frame, text=BUTTON_GENERATE, command=self.generate_text)
        self.button_generate.pack(pady=5, fill='x')

        # クリップボードにコピーするボタン(全文)
        self.button_all_copy = tk.Button(self.main_frame, text=BUTTON_ALL_COPY, command=self.copy_all_to_clipboard)
        self.button_all_copy.pack(pady=5, fill='x')
        
        # 生成＆クリップボードにコピーするボタン(全文)
        self.button_generate_and_all_copy = tk.Button(self.main_frame, text="生成とコピー（全文）", command=self.generate_and_copy_all_to_clipboard)
        self.button_generate_and_all_copy.pack(pady=5, fill='x')

        # テキスト出力エリア
        self.text_output = tk.scrolledtext.ScrolledText(self.sub_frame, padx=2, pady=2, width=40, height=20, font=self.output_font)
        self.text_output.pack(expand=True, fill='both')

        # サブボタンのフレーム
        self.sub_buttons_frame = tk.Frame(self.sub_frame)
        self.sub_buttons_frame.pack(fill='x')

        # 末尾固定文のみ更新ボタン
        self.button_update_tail_free_texts = tk.Button(self.sub_buttons_frame, text="末尾固定部のみ更新", padx=5, width=30, font=self.sub_buttons_font, command=self.update_tail_free_texts)
        self.button_update_tail_free_texts.pack(pady=5, fill='none')

        # オプションのみ更新ボタン
        self.button_update_option = tk.Button(self.sub_buttons_frame, text="オプションのみ更新", padx=5, width=30, font=self.sub_buttons_font, command=self.update_option)
        self.button_update_option.pack(pady=5, fill='none')

        # クリップボードにコピーするボタン(options)
        self.button_options_copy = tk.Button(self.sub_buttons_frame, text=BUTTON_OPTIONS_COPY, padx=5, width=30, font=self.sub_buttons_font, command=self.copy_options_to_clipboard)
        self.button_options_copy.pack(pady=5, fill='none')

        # 除外語句CSVを開くボタン
        self.button_open_exclusion_csv = tk.Button(self.sub_buttons_frame, text="除外語句CSVを開く", padx=5, width=30, font=self.sub_buttons_font, command=self.open_exclusion_csv)
        self.button_open_exclusion_csv.pack(pady=5, fill='none')

        # アレンジ（LLM）UI
        self.arrange_frame = tk.Frame(self.sub_buttons_frame)
        self.arrange_frame.pack(fill='x')

        # 文字数調整オプション
        self.length_adjust_frame = tk.Frame(self.sub_buttons_frame)
        self.length_adjust_frame.pack(fill='x')
        
        self.label_length_adjust = tk.Label(self.length_adjust_frame, text="文字数調整:")
        self.label_length_adjust.pack(side='left')
        
        self.length_adjust_var = tk.StringVar(value="同程度")
        self.combo_length_adjust = ttk.Combobox(
            self.length_adjust_frame,
            values=["半分", "2割減", "同程度", "2割増", "倍"],
            textvariable=self.length_adjust_var,
            width=8,
            state="readonly"
        )
        self.combo_length_adjust.pack(side='left', padx=5)
        
        
        # 固定文字数（優先）
        self.label_fixed_length = tk.Label(self.length_adjust_frame, text="固定:")
        self.label_fixed_length.pack(side='left')
        self.fixed_length_var = tk.StringVar(value="")
        self.combo_fixed_length = ttk.Combobox(
            self.length_adjust_frame,
            values=["", "50", "100", "150", "200", "250", "300"],
            textvariable=self.fixed_length_var,
            width=5,
            state="readonly"
        )
        self.combo_fixed_length.pack(side='left', padx=5)
        

        # アレンジプリセット（YAMLから読み込み）
        self.arrange_presets = load_arrange_presets(ARRANGE_PRESETS_YAML)
        if not self.arrange_presets:
            # フォールバック
            fallback = [
                "auto","cinematic","illustration","noir","vaporwave","sci-fi",
                "gear","composition","palette","wild","paraphrase","fantasy","cyberpunk","和風","浮世絵","steampunk"
            ]
            self.arrange_presets = [
                {"id": v, "label": v, "guidance": ""} for v in fallback
            ]
            print(f"フォールバックプリセットを使用: {fallback}")
        else:
            print(f"YAMLからプリセットを読み込み: {len(self.arrange_presets)}個")
            for preset in self.arrange_presets:
                print(f"  - {preset['label']} (id: {preset['id']}, guidance: {preset.get('guidance', 'なし')})")
        
        preset_labels = [p["label"] for p in self.arrange_presets]
        print(f"UIに設定するプリセットラベル: {preset_labels}")

        self.combo_arrange = ttk.Combobox(
            self.arrange_frame,
            values=preset_labels,
            width=10,
            state="readonly",
        )
        self.combo_arrange.set(preset_labels[0] if preset_labels else "auto")
        self.combo_arrange.pack(side='left')

        self.scale_arrange = ttk.Scale(self.arrange_frame, from_=0, to=3, orient='horizontal')
        self.scale_arrange.set(1)
        self.scale_arrange.pack(side='left', padx=5)
        # 数値ラベル
        self.label_arrange_value = tk.Label(self.arrange_frame, text=str(int(self.scale_arrange.get())))
        self.label_arrange_value.pack(side='left')
        self.scale_arrange.bind('<B1-Motion>', self._on_arrange_scale_change)
        self.scale_arrange.bind('<ButtonRelease-1>', self._on_arrange_scale_change)

        self.arrange_use_llm_var = tk.BooleanVar(value=True)
        self.checkbox_arrange_use_llm = tk.Checkbutton(self.arrange_frame, text="LLM", variable=self.arrange_use_llm_var)
        self.checkbox_arrange_use_llm.pack(side='left', padx=5)
        # ツールチップ（0.3秒後）
        def _tooltip_text():
            v = int(round(self.scale_arrange.get()))
            mapping = {
                0: "最小限の変更（単語の改善のみ）",
                1: "穏やかな改善（スタイルと表現の向上）",
                2: "中程度の創造的変更（より鮮やかな描写）",
                3: "大胆な創造的変換（劇的な視覚的強化）",
            }
            return f"強度: {v} — " + mapping.get(v, "アレンジの強さを表します")
        DelayedTooltip(self.scale_arrange, _tooltip_text, delay=300)

        self.button_arrange_llm = tk.Button(
            self.sub_buttons_frame,
            text="アレンジ(LLM)",
            padx=5,
            width=30,
            font=self.sub_buttons_font,
            command=self.handle_arrange_llm,
        )
        self.button_arrange_llm.pack(pady=5, fill='none')

        self.button_arrange_llm_copy = tk.Button(
            self.sub_buttons_frame,
            text="アレンジしてコピー(LLM)",
            padx=5,
            width=30,
            font=self.sub_buttons_font,
            command=self.handle_arrange_llm_and_copy,
        )
        self.button_arrange_llm_copy.pack(pady=5, fill='none')

        # 文字数調整のみボタン
        self.button_length_adjust_only = tk.Button(
            self.sub_buttons_frame,
            text="文字数調整のみ",
            padx=5,
            width=30,
            font=self.sub_buttons_font,
            command=self.handle_length_adjust_only,
        )
        self.button_length_adjust_only.pack(pady=5, fill='none')

        # 文字数調整してコピーボタン
        self.button_length_adjust_and_copy = tk.Button(
            self.sub_buttons_frame,
            text="文字数調整してコピー",
            padx=5,
            width=30,
            font=self.sub_buttons_font,
            command=self.handle_length_adjust_and_copy,
        )
        self.button_length_adjust_and_copy.pack(pady=5, fill='none')

        # 変数初期化
        self.file_lines = []
        self.main_prompt = ""
        self.option_prompt = ""
        self.tail_free_texts = ""
        self.last_arranged_output = None
        self._last_error_details = []  # エラー詳細を保存する変数

        self._log_current_model("initial")

    def load_attribute_data(self):
        conn = sqlite3.connect(DEFAULT_DB_PATH)
        cursor = conn.cursor()

        # attribute_types の取得
        cursor.execute("SELECT id, attribute_name, description FROM attribute_types")
        self.attribute_types = [{'id': row[0], 'attribute_name': row[1], 'description': row[2]} for row in cursor.fetchall()]

        # attribute_details の取得（content数も含める）
        cursor.execute("""
            SELECT ad.id, ad.attribute_type_id, ad.description, ad.value, COUNT(DISTINCT pad.prompt_id) as content_count
            FROM attribute_details ad
            LEFT JOIN prompt_attribute_details pad ON ad.id = pad.attribute_detail_id
            GROUP BY ad.id
        """)
        self.attribute_details = [
            {'id': row[0], 'attribute_type_id': row[1], 'description': row[2], 'value': row[3], 'content_count': row[4]}
            for row in cursor.fetchall()
        ]

        conn.close()

    def create_llm_model_selector_ui(self):
        """LLMモデルの選択UIを構築する。
        環境変数（YAML設定）で指定されたモデルを起動時にプルダウンで選択済みにする。
        """
        frame = tk.Frame(self.main_frame)
        frame.pack(fill='x')
        tk.Label(frame, text="LLMモデル:").pack(side='left')
        self.combo_llm_model = ttk.Combobox(
            frame,
            values=self.available_model_choices,
            textvariable=self.llm_model_var,
            width=15,
            state="readonly"
        )
        self.combo_llm_model.pack(side='left', padx=5)
        
        # 環境変数（YAML設定）のモデルをプルダウンで選択済みにする
        current_model = self.llm_model_var.get()
        if current_model in self.available_model_choices:
            self.combo_llm_model.current(self.available_model_choices.index(current_model))
        
        self.combo_llm_model.bind("<<ComboboxSelected>>", self.on_model_change)
        self.label_current_model = tk.Label(frame, text=f"選択中: {self.llm_model_var.get()}")
        self.label_current_model.pack(side='left', padx=5)

    def on_model_change(self, event=None):
        model = self.get_selected_model()
        self.label_current_model.configure(text=f"選択中: {model}")
        self._log_current_model("changed via UI")

    def _log_current_model(self, note: str = ""):
        model = self.get_selected_model()
        suffix = f" ({note})" if note else ""
        print(f"[LLM] 現在のモデル: {model}{suffix}")

    def get_selected_model(self) -> str:
        value = (self.llm_model_var.get() or "").strip()
        return value or LLM_MODEL

    def _append_temperature_hint_for_model(self, prompt_text: str, temperature_value: float) -> str:
        return _append_temperature_hint(prompt_text, self.get_selected_model(), temperature_value)

    def open_csv_import_window(self):
        CSVImportWindow(self.master, self.update_attribute_details)

    def open_exclusion_csv(self):
        try:
            if os.name == 'nt':  # Windows
                subprocess.Popen(['notepad.exe', EXCLUSION_CSV])
            elif os.name == 'posix':  # macOS and Linux
                if sys.platform == 'darwin':  # macOS
                    subprocess.call(['open', '-a', 'TextEdit', EXCLUSION_CSV])
                else:  # Linux
                    subprocess.call(['xdg-open', EXCLUSION_CSV])
        except Exception as e:
            messagebox.showerror("エラー", f"CSVファイルを開けませんでした: {str(e)}")

    def update_attribute_details(self):
        self.load_attribute_data()
        for attribute_type in self.attribute_types:
            detail_combo = self.attribute_detail_combos[attribute_type['id']]
            detail_values = ['-'] + [
                f"{detail['description']} ({detail['content_count']})"
                for detail in self.attribute_details
                if detail['attribute_type_id'] == attribute_type['id'] and detail['content_count'] > 0
            ]
            detail_combo['values'] = detail_values
            detail_combo.set('-')

    def select_file(self):
        file_path = tkinter.filedialog.askopenfilename()
        if file_path:
            self.entry_file_path.delete(0, tk.END)
            self.entry_file_path.insert(0, file_path)
            with open(file_path, 'r', encoding='utf-8') as file:
                self.file_lines = file.readlines()

    def create_attribute_type_ui(self):
        for attribute_type in self.attribute_types:
            frame = tk.Frame(self.main_frame)
            frame.pack(fill='x')
            
            label = tk.Label(frame, text=attribute_type['description'], width=15, anchor='w')
            label.pack(side='left')
            
            detail_values = ['-'] + [
                f"{detail['description']} ({detail['content_count']})"
                for detail in self.attribute_details
                if detail['attribute_type_id'] == attribute_type['id'] and detail['content_count'] > 0
            ]
            detail_combo = ttk.Combobox(frame, values=detail_values, width=67, style="TCombobox", font=12, state="readonly")
            detail_combo.pack(side='left')
            detail_combo.set('-')
            
            count_combo = ttk.Combobox(frame, values=['-'] + list(range(11)), width=5, style="TCombobox", font=18)
            count_combo.pack(side='left')
            # count_combo.set('-')
            count_combo.set(0)
            
            self.attribute_type_frames[attribute_type['id']] = frame
            self.attribute_detail_combos[attribute_type['id']] = detail_combo
            self.attribute_count_combos[attribute_type['id']] = count_combo

            # プルダウンメニューのフォントを設定
            detail_combo.option_add('*TCombobox*Listbox.font', self.combo_font)
            count_combo.option_add('*TCombobox*Listbox.font', self.combo_font)

    def generate_text(self):
        try:
            conn = sqlite3.connect(DEFAULT_DB_PATH)
            cursor = conn.cursor()
            
            total_lines = int(self.entry_row_num.get())
            selected_lines = []
            
            exclusion_words = [word.strip() for word in self.combo_exclusion_words.get().split(',') if word.strip()]
            if self.add_exclusion_words_var.get() and exclusion_words:
                self.update_exclusion_words()  # 除外語句を更新
            for attribute_type in self.attribute_types:
                detail_combo = self.attribute_detail_combos[attribute_type['id']]
                count_combo = self.attribute_count_combos[attribute_type['id']]
                
                detail = detail_combo.get()
                count = count_combo.get()
                
                if detail != '-' and count != '-':
                    count = int(count)
                    if count > 0:
                        detail_description = detail.split(' (')[0]  # Remove the content count
                        detail_value = next((d['value'] for d in self.attribute_details if d['description'] == detail_description), None)
                        if detail_value:
                            if self.add_exclusion_words_var.get() and exclusion_words:
                                exclusion_condition = ' AND ' + ' AND '.join(f"p.content NOT LIKE ?" for _ in exclusion_words)
                                query = f'''
                                    SELECT p.content 
                                    FROM prompts p
                                    JOIN prompt_attribute_details pad ON p.id = pad.prompt_id
                                    JOIN attribute_details ad ON pad.attribute_detail_id = ad.id
                                    WHERE ad.value = ? {exclusion_condition}
                                '''
                                params = [detail_value] + [f'%{word}%' for word in exclusion_words]
                                cursor.execute(query, params)
                            else:
                                cursor.execute('''
                                    SELECT p.content 
                                    FROM prompts p
                                    JOIN prompt_attribute_details pad ON p.id = pad.prompt_id
                                    JOIN attribute_details ad ON pad.attribute_detail_id = ad.id
                                    WHERE ad.value = ?
                                ''', (detail_value,))
                            matching_lines = cursor.fetchall()
                            selected_lines.extend(random.sample(matching_lines, min(count, len(matching_lines))))
            
            remaining_lines = total_lines - len(selected_lines)
            if remaining_lines > 0:
                # cursor.execute('SELECT content FROM prompts')
                if self.add_exclusion_words_var.get() and exclusion_words:
                    exclusion_condition = ' AND ' + ' AND '.join(f"content NOT LIKE ?" for _ in exclusion_words)
                    query = f'SELECT content FROM prompts WHERE 1=1 {exclusion_condition}'
                    cursor.execute(query, [f'%{word}%' for word in exclusion_words])
                else:
                    cursor.execute('SELECT content FROM prompts')
                all_prompts = cursor.fetchall()
                remaining_pool = [line for line in all_prompts if line not in selected_lines]
                selected_lines.extend(random.sample(remaining_pool, remaining_lines))
            
            conn.close()
            
            random.shuffle(selected_lines)
            
            processed_lines = []
            for line in selected_lines:
                line = line[0].strip()  # タプルから文字列を取り出し、余分な空白を削除
                if line.endswith((",", "、", ";", ":", "；", "：", "!", "?", "\n")):
                    line = line[:-1] + "."
                elif not line.endswith("."):
                    line += "."
                processed_lines.append(line)
            
            self.main_prompt = ' '.join(processed_lines)
            self.update_option()
        except ValueError:
            messagebox.showerror("エラー", "行数は整数で入力してください。")
        except Exception as e:
            messagebox.showerror("エラー", f"エラーが発生しました: {get_exception_trace()}")

    def make_option_prompt(self):
        # オプションテキストの生成
        tail_ar_text    = " --ar "    + self.combo_tail_ar.get() if self.combo_tail_ar.get() and self.add_tail_ar_text_var.get() else ''
        tail_s_text    = " --s "    + self.combo_tail_s_text.get() if self.combo_tail_s_text.get() and self.add_tail_s_text_var.get() else ''
        tail_chaos_text = " --chaos " + self.combo_tail_chaos.get() if self.combo_tail_chaos.get() and self.add_tail_chaos_text_var.get() else ''
        tail_q_text = " --q " + self.combo_tail_q.get() if self.combo_tail_q.get() and self.add_tail_q_text_var.get() else ''
        tail_weird_text = " --weird " + self.combo_tail_weird.get() if self.combo_tail_weird.get() and self.add_tail_weird_text_var.get() else ''
        
        # オプションプロンプトの更新
        self.option_prompt = tail_ar_text + tail_s_text + tail_chaos_text + tail_q_text + tail_weird_text

    def make_free_texts(self):
        # 末尾固定文の生成
        tail_free_text1    = " " + self.combo_tail_free_text1.get() if self.combo_tail_free_text1.get() and self.add_tail_free_text_var1.get() else ''
        self.tail_free_texts = tail_free_text1

    def _get_tail_preset_choices(self, media_type=None):
        """image/movieなど媒体種別ごとに適切な末尾プリセットを返す。"""
        media_type = (media_type or self.tail_media_type_var.get() or DEFAULT_TAIL_MEDIA_TYPE).strip()
        return TAIL_PRESET_CHOICES.get(media_type, TAIL_PRESET_CHOICES[DEFAULT_TAIL_MEDIA_TYPE])

    def update_tail_free_text_choices(self, reset_selection=False):
        """媒体種別切替時にコンボボックスの候補と選択値を整合させる。"""
        presets = self._get_tail_preset_choices()
        current_value = self.combo_tail_free_text1.get()
        self.combo_tail_free_text1['values'] = presets
        if reset_selection or current_value not in presets:
            self.combo_tail_free_text1.set(presets[0])

    def on_tail_media_type_change(self, event=None):
        """image/movie選択の変更を受けて候補を刷新し、自動反映中は即時で出力を更新。"""
        self.update_tail_free_text_choices(reset_selection=True)
        self.auto_update(event=None)

    def update_option(self):
        try:
            # オプションのみ更新
            self.make_option_prompt()
            
            # 連結
            result = self.main_prompt + self.tail_free_texts + self.option_prompt
            self.text_output.delete('1.0', tk.END)
            self.text_output.insert(tk.END, result)
        except Exception:
            print(get_exception_trace())

    def update_tail_free_texts(self):
        try:
            # 末尾固定文のみ更新
            self.make_free_texts()
            
            # 連結
            result = self.main_prompt + self.tail_free_texts + self.option_prompt
            self.text_output.delete('1.0', tk.END)
            self.text_output.insert(tk.END, result)
        except Exception:
            print(get_exception_trace())

    def auto_update(self, event):
        try:
            if self.autofix_var.get():
                self.make_free_texts()
                self.make_option_prompt()
                
                # 連結
                result = self.main_prompt + self.tail_free_texts + self.option_prompt
                self.text_output.delete('1.0', tk.END)
                self.text_output.insert(tk.END, result)
        except Exception:
            print(get_exception_trace())

    def copy_all_to_clipboard(self):
        self.master.clipboard_clear()
        self.master.clipboard_append(self.text_output.get("1.0", tk.END))

    def copy_options_to_clipboard(self):
        self.make_option_prompt()
        self.master.clipboard_clear()
        self.master.clipboard_append(self.option_prompt)

    def generate_and_copy_all_to_clipboard(self):
        self.generate_text()
        self.copy_all_to_clipboard()
        
    def handle_arrange_llm(self):
        try:
            if not self.arrange_use_llm_var.get():
                messagebox.showwarning("注意", "LLMがオフになっています。LLMチェックを有効にしてください。")
                return False
            preset_label = self.combo_arrange.get()
            selected_preset = next((p for p in self.arrange_presets if p['label'] == preset_label), None)
            preset = selected_preset['id'] if selected_preset else preset_label
            guidance = selected_preset.get('guidance') if selected_preset else ""
            strength = int(round(self.scale_arrange.get()))
            src = self.text_output.get("1.0", tk.END).strip()
            if not src:
                messagebox.showwarning("注意", "まずプロンプトを生成してください。")
                return False
            llm_src, movie_tail = self._detach_movie_tail_for_llm(src)
            if self.last_arranged_output:
                prev_output_clean, _ = self._detach_movie_tail_for_llm(self.last_arranged_output)
            else:
                prev_output_clean = None
            
            # アレンジ処理の実行
            arranged = self.arrange_with_llm(llm_src, preset, strength, guidance, prev_output=prev_output_clean)
            
            if arranged:
                # 念のため最終出力にも継承サニタイズを適用し、movie JSON を復元
                arranged = self._inherit_options_if_present(llm_src, arranged)
                arranged = self._restore_movie_tail_after_llm(arranged, movie_tail)
                # アレンジ前後の比較表示ダイアログを表示
                self.show_arrange_comparison_dialog(src, arranged, preset_label, strength)
                self.text_output.delete('1.0', tk.END)
                self.text_output.insert(tk.END, arranged)
                self.last_arranged_output = arranged
                try:
                    self.master.update_idletasks()
                except Exception:
                    pass
                return True
            else:
                # アレンジが失敗した場合のエラーダイアログ
                # エラー詳細を取得（arrange_with_llmで設定されたerror_detailsを使用）
                error_details = getattr(self, '_last_error_details', [])
                print(f"取得したエラー詳細: {error_details}")  # デバッグ出力
                
                if error_details:
                    error_details_text = "\n".join([f"• {detail}" for detail in error_details])
                else:
                    error_details_text = "• エラー詳細が取得できませんでした"
                
                current_model = self.get_selected_model()
                error_message = f"アレンジ処理が失敗しました。\n\nプリセット: {preset_label}\n強度: {strength}\n\nエラー詳細:\n{error_details_text}\n\n考えられる原因:\n• APIキーが正しく設定されていない\n• ネットワーク接続の問題\n• OpenAI APIの一時的な障害\n• プリセット '{preset_label}' が無効\n• モデル '{current_model}' が利用できない"
                
                # 詳細なエラーダイアログを表示
                self.show_detailed_error_dialog("アレンジ失敗", error_message, preset_label, strength)
                return False
        except Exception as e:
            error_message = f"LLMアレンジ処理中にエラーが発生しました:\n\nプリセット: {self.combo_arrange.get()}\n強度: {int(round(self.scale_arrange.get()))}\nモデル: {self.get_selected_model()}\n\nエラー詳細:\n{get_exception_trace()}"
            messagebox.showerror("エラー", error_message)
            return False

    def handle_arrange_llm_and_copy(self):
        if self.handle_arrange_llm():
            self.copy_all_to_clipboard()

    def handle_length_adjust_only(self):
        """文字数のみを調整する機能"""
        try:
            src = self.text_output.get("1.0", tk.END).strip()
            if not src:
                messagebox.showwarning("注意", "まずプロンプトを生成してください。")
                return False
            llm_src, movie_tail = self._detach_movie_tail_for_llm(src)
            
            # 文字数調整の設定を取得
            length_adjust = self.length_adjust_var.get()
            original_length = len(llm_src)
            
            # 固定文字数が選択されていれば優先
            fixed_value = (self.fixed_length_var.get() or "").strip()
            if fixed_value.isdigit():
                target_length = int(fixed_value)
                length_adjust_display = f"固定{fixed_value}文字"
            else:
                # 文字数調整の倍率を計算
                length_multipliers = {
                    "半分": 0.5,
                    "2割減": 0.8,
                    "同程度": 1.0,
                    "2割増": 1.2,
                    "倍": 2.0
                }
                target_length_multiplier = length_multipliers.get(length_adjust, 1.0)
                target_length = int(original_length * target_length_multiplier)
                length_adjust_display = length_adjust
            
            print(f"文字数調整処理開始:")
            print(f"  調整設定: {length_adjust_display}")
            print(f"  元の文字数: {original_length}")
            print(f"  目標文字数: {target_length}")
            
            # 文字数調整のみのプロンプトを生成
            adjusted_text = self.adjust_text_length_only(llm_src, target_length)
            
            if adjusted_text:
                # 念のため最終出力にも継承サニタイズを適用し、movie JSON を復元
                adjusted_text = self._inherit_options_if_present(llm_src, adjusted_text)
                adjusted_text = self._restore_movie_tail_after_llm(adjusted_text, movie_tail)
                # 調整前後の比較表示ダイアログを表示
                self.show_length_adjust_comparison_dialog(src, adjusted_text, length_adjust_display)
                self.text_output.delete('1.0', tk.END)
                self.text_output.insert(tk.END, adjusted_text)
                return True
            else:
                messagebox.showerror("エラー", "文字数調整に失敗しました。")
                return False
                
        except Exception as e:
            error_message = f"文字数調整処理中にエラーが発生しました:\n\n調整設定: {self.length_adjust_var.get()}\n\nエラー詳細:\n{get_exception_trace()}"
            messagebox.showerror("エラー", error_message)
            return False

    def handle_length_adjust_and_copy(self):
        """文字数調整してコピーする機能"""
        if self.handle_length_adjust_only():
            self.copy_all_to_clipboard()

    def adjust_text_length_only(self, text, target_length):
        """意味を本質的に変えずに文字数のみを調整する"""
        try:
            if not LLM_ENABLED:
                error_msg = "LLMが無効化されています。YAMLの LLM_ENABLED を true にしてください。"
                print(f"  {error_msg}")
                messagebox.showwarning("注意", error_msg)
                return None
            
            import os, uuid
            api_key = os.getenv(OPENAI_API_KEY_ENV)
            if not api_key:
                error_msg = f"{OPENAI_API_KEY_ENV} が未設定です。環境変数にAPIキーを設定してください。"
                print(f"  {error_msg}")
                messagebox.showerror("エラー", error_msg)
                return None
            
            print(f"  APIキー確認: {'設定済み' if api_key else '未設定'}")
            selected_model = self.get_selected_model()
            print(f"  使用モデル: {selected_model}")
            
            # 文字数調整専用のシステムプロンプト
            is_reduction = target_length < len(text)
            reduction_emphasis = ""
            if is_reduction:
                reduction_emphasis = (
                    "MANDATORY LENGTH REDUCTION: You MUST cut the text to approximately {target_length} characters. "
                    "This is NOT optional - you MUST reduce the length aggressively. "
                    "Prioritize length reduction over preserving every detail. "
                    "If you cannot reach the exact target, make it significantly shorter than the original. "
                    "AGGRESSIVE REDUCTION TECHNIQUES:\n"
                    "- Remove ALL redundant and repetitive words\n"
                    "- Combine multiple adjectives into single strong ones\n"
                    "- Eliminate unnecessary articles (a, an, the) where possible\n"
                    "- Remove prepositions that don't add meaning\n"
                    "- Use shorter synonyms for ANY long words\n"
                    "- Cut descriptive phrases in half\n"
                    "- Remove any words that don't add essential meaning\n"
                    "- Combine similar concepts aggressively\n"
                    "- Shorten technical parameters where possible\n"
                    "- Remove any repetitive style descriptions\n"
                    "CRITICAL: Length reduction is MORE important than preserving every detail. "
                    "Make it shorter even if some details are lost."
                )
            
            system_prompt = (
                "You are a text length adjustment specialist. Your task is to adjust the length of the given text "
                f"{'by AGGRESSIVELY REDUCING it' if is_reduction else 'while preserving its core meaning and essence'}. "
                "Do NOT change the visual style, artistic direction, or creative elements. "
                f"{'AGGRESSIVELY adjust the length by:' if is_reduction else 'Only adjust the length by:'}\n"
                "- Adding or removing descriptive words\n"
                "- Expanding or condensing phrases\n"
                "- Maintain all technical parameters if they exist (--ar, --s, --chaos, --q, --weird). Do NOT add any new parameters if not present.\n"
                "- Keep the same subject and composition\n"
                "- IMPORTANT: If and only if the original ends with --options, preserve them exactly; otherwise do NOT add any --options.\n\n"
                f"{reduction_emphasis}"
                "CRITICAL: The output must be approximately the target length. "
                f"Target: {target_length} characters (original: {len(text)}). "
                f"{'FORCE REDUCTION - LENGTH IS PRIORITY' if is_reduction else 'LENGTH ADJUSTMENT REQUIRED'}. "
                "Output only the adjusted prompt."
            )
            
            nonce = uuid.uuid4().hex[:8]
            is_reduction = target_length < len(text)
            reduction_instruction = ""
            if is_reduction:
                reduction_instruction = (
                    f"FORCE REDUCTION: You MUST cut {len(text) - target_length} characters from the text. "
                    "This is MANDATORY - not optional. Be extremely aggressive in shortening. "
                    "Remove words aggressively, combine concepts, cut descriptions in half. "
                    "Length reduction is MORE important than preserving meaning. "
                    "If you cannot reach the target, make it as short as possible. "
                    "DO NOT preserve every detail - prioritize shortness. "
                )
            
            user_prompt = (
                f"Length adjustment request\n"
                f"Nonce: {nonce}\n"
                f"Target length: {target_length} characters (current: {len(text)})\n"
                f"{reduction_instruction}"
                f"Instruction: Adjust length ONLY. Preserve meaning, style, and all technical parameters.\n"
                f"Text: {text}"
            )
            
            # 文字数削減の場合はより積極的な温度設定
            base_temperature = 0.3
            if is_reduction:
                # 削減の場合は高い温度でより積極的な変更を促す
                adjusted_temperature = min(base_temperature * 2.0, 0.8)
            else:
                adjusted_temperature = base_temperature
            
            system_prompt = self._append_temperature_hint_for_model(system_prompt, adjusted_temperature)
            
            raw_content, finish_reason, data = send_llm_request(
                api_key=api_key,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=adjusted_temperature,
                max_tokens=LLM_MAX_COMPLETION_TOKENS,
                timeout=LLM_TIMEOUT,
                model_name=selected_model,
                include_temperature=not _should_use_responses_api(selected_model)
            )
            print(f"    生レスポンス: '{raw_content}'")
            print(f"    終了理由: {finish_reason}")
            
            if not raw_content:
                print(f"    警告: レスポンスが空です")
                return None
                    
            content = sanitize_to_english(raw_content)
            print(f"    文字数調整成功: {len(content)} 文字")
            
            # 同一チェック
            if content.strip() == text.strip():
                print(f"    同一内容のため調整失敗")
                return None
            
            # 元にオプションがなければ付与しない。ある場合のみ継承
            return self._inherit_options_if_present(text, content)
                
        except requests.HTTPError as e:
            error_msg = f"HTTPエラー: {e}"
            print(f"    {error_msg}")
            messagebox.showerror("エラー", f"文字数調整中にHTTPエラーが発生しました: {error_msg}")
            return None
            
        except requests.exceptions.Timeout as e:
            error_msg = f"タイムアウト: {e}"
            print(f"    {error_msg}")
            messagebox.showerror("エラー", f"文字数調整中にタイムアウトが発生しました: {error_msg}")
            return None
            
        except requests.exceptions.ConnectionError as e:
            error_msg = f"接続エラー: {e}"
            print(f"    {error_msg}")
            messagebox.showerror("エラー", f"文字数調整中に接続エラーが発生しました: {error_msg}")
            return None
            
        except Exception as e:
            error_msg = f"予期しないエラー: {e}"
            print(f"    {error_msg}")
            messagebox.showerror("エラー", f"文字数調整中に予期しないエラーが発生しました: {error_msg}")
            return None

    def _on_arrange_scale_change(self, event=None):
        try:
            v = int(round(self.scale_arrange.get()))
            self.label_arrange_value.configure(text=str(v))
        except Exception:
            pass

    def arrange_with_llm(self, text, preset, strength, guidance="", prev_output=None):
        if not LLM_ENABLED:
            error_msg = "LLMが無効化されています。YAMLの LLM_ENABLED を true にしてください。"
            print(f"  {error_msg}")
            self._last_error_details = [error_msg]
            messagebox.showwarning("注意", error_msg)
            return None
        
        # 文字数調整の設定を取得
        length_adjust = self.length_adjust_var.get()
        original_length = len(text)
        
        # 固定文字数が選択されていれば優先
        fixed_value = (getattr(self, 'fixed_length_var', tk.StringVar(value="")).get() or "").strip()
        if fixed_value.isdigit():
            target_length = int(fixed_value)
        else:
            # 文字数調整の倍率を計算
            length_multipliers = {
                "半分": 0.5,
                "2割減": 0.8,
                "同程度": 1.0,
                "2割増": 1.2,
                "倍": 2.0
            }
            target_length_multiplier = length_multipliers.get(length_adjust, 1.0)
            target_length = int(original_length * target_length_multiplier)
        
        print(f"  文字数調整: {length_adjust} (元: {original_length}文字 → 目標: {target_length}文字)")
        selected_model = self.get_selected_model()
        print(f"  使用モデル: {selected_model}")

        import os, uuid
        api_key = os.getenv(OPENAI_API_KEY_ENV)
        if not api_key:
            error_msg = f"{OPENAI_API_KEY_ENV} が未設定です。環境変数にAPIキーを設定してください。"
            print(f"  {error_msg}")
            self._last_error_details = [error_msg]
            messagebox.showerror("エラー", error_msg)
            return None
        
        print(f"  APIキー確認: {'設定済み' if api_key else '未設定'}")
        if api_key:
            print(f"  APIキー長: {len(api_key)} 文字")
            print(f"  APIキー先頭: {api_key[:10]}...")

        # デバッグ情報を出力
        print(f"アレンジ処理開始:")
        print(f"  プリセット: {preset}")
        print(f"  強度: {strength}")
        print(f"  ガイダンス: {guidance}")
        print(f"  テキスト長: {len(text)} 文字")

        # エラー詳細を初期化
        self._last_error_details = []

        # ブレンド・アンカー設定
        blend_weight_map = {0: 20, 1: 35, 2: 65, 3: 80}  # guidance割合の目安（%）
        blend_weight = blend_weight_map.get(strength, 55)
        anchor_terms = self._extract_anchor_terms(text, max_terms=8)
        hybrid_cues = self._generate_hybrid_cues(anchor_terms, preset, guidance, max_items=5)
        must_keep_count = 3 if strength <= 2 else 2

        # 強度に応じたシステムプロンプトを動的に生成
        strength_descriptions = {
            0: "Apply very subtle, minimal changes. Keep almost everything the same, just minor word improvements.",
            1: "Apply gentle, tasteful variations. Improve wording and style while keeping the core concept intact.",
            2: "Apply moderate creative variations. Enhance style, add vivid descriptors, and improve composition.",
            3: "Apply bold, creative transformations. Enhance style and add dramatic descriptors while preserving the original subject and key elements."
        }
        
        strength_instruction = strength_descriptions.get(strength, strength_descriptions[2])
        
        # 強度3の場合はより具体的で強力な指示を使用
        if strength == 3:
            system_prompt = (
                f"You are a creative prompt artist. Transform this Midjourney prompt with {strength_instruction}. "
                f"If guidance is provided, it SHOULD influence style but MUST BLEND with the original content. "
                f"Do NOT eliminate original cultural/subject elements; preserve and merge them with the guidance. "
                f"Be BOLD and CREATIVE - enhance the visual style with dramatic effects and vivid cinematic language. "
                f"STYLE BLENDING RULES:\n"
                f"- Express guidance via lighting, palette, materials, VFX, and subtle accessories\n"
                f"- Avoid replacing the identities of original subjects; avoid introducing brand-new subjects\n"
                f"- Keep cultural cues (e.g., traditional motifs) and merge them with the guidance style\n"
                f"CONTENT PRESERVATION RULES:\n"
                f"- Keep the scene's core setting and composition\n"
                f"- Preserve original environmental motifs and objects whenever possible\n"
                f"PROPER NOUN ABSTRACTION RULES:\n"
                f"- REPLACE: Brand names (Nike → sports brand), company names (Apple → tech company), product names (iPhone → smartphone)\n"
                f"- REPLACE: Person names (John Smith → a person), celebrity names (Beyoncé → a famous singer)\n"
                f"- REPLACE: Movie/TV titles (Star Wars → sci-fi franchise), book titles (Harry Potter → fantasy series)\n"
                f"- KEEP: Geographic terms (Japan, Tokyo, Paris, New York, Asia, Europe)\n"
                f"- KEEP: Temporal terms (medieval, renaissance, 1920s, modern, futuristic)\n"
                f"- KEEP: Cultural styles (zen, art deco, cyberpunk, traditional)\n"
                f"CRITICAL LENGTH REQUIREMENT: The output must be {'shorter' if target_length < original_length else 'longer' if target_length > original_length else 'similar'} than the original. "
                f"Target: approximately {target_length} characters (original: {original_length}). "
                f"IMPORTANT: If and only if the original ends with --options, preserve them exactly; otherwise do NOT add any --options. Output only the transformed prompt."
            )
        else:
            # 強度に応じてガイダンスの適用度を調整
            guidance_system_instruction = ""
            if strength == 0:
                guidance_system_instruction = "If guidance is provided, apply it very subtly or ignore it. Focus on minimal improvements only."
            elif strength == 1:
                guidance_system_instruction = "If guidance is provided, apply it gently and blend it subtly with the original content."
            elif strength == 2:
                guidance_system_instruction = "If guidance is provided, apply it moderately via hybridization of materials, textures, lighting while keeping core elements."
            
            system_prompt = (
                f"Rewrite Midjourney prompts with {strength_instruction}. "
                f"{guidance_system_instruction} "
                f"Keep core content. IMPORTANT: If and only if the original ends with --options, preserve them exactly; otherwise do NOT add any --options. "
                f"STYLE BLENDING RULES:\n"
                f"- Blend guidance via lighting, palette, materials, VFX, and subtle accessories\n"
                f"- Do not replace the identities of original subjects; avoid new subjects unless present\n"
                f"- Keep cultural/setting cues and merge them with the guidance style\n"
                f"CONTENT PRESERVATION RULES:\n"
                f"- Keep the scene's core setting and composition\n"
                f"- Preserve original environmental motifs and objects whenever possible\n"
                f"PROPER NOUN ABSTRACTION RULES:\n"
                f"- REPLACE: Brand names (Nike → sports brand), company names (Apple → tech company), product names (iPhone → smartphone)\n"
                f"- REPLACE: Person names (John Smith → a person), celebrity names (Beyoncé → a famous singer)\n"
                f"- REPLACE: Movie/TV titles (Star Wars → sci-fi franchise), book titles (Harry Potter → fantasy series)\n"
                f"- KEEP: Geographic terms (Japan, Tokyo, Paris, New York, Asia, Europe)\n"
                f"- KEEP: Temporal terms (medieval, renaissance, 1920s, modern, futuristic)\n"
                f"- KEEP: Cultural styles (zen, art deco, cyberpunk, traditional)\n"
                f"CRITICAL LENGTH REQUIREMENT: The output must be {'shorter' if target_length < original_length else 'longer' if target_length > original_length else 'similar'} than the original. "
                f"Target: approximately {target_length} characters (original: {original_length}). "
                f"Output only the prompt."
            )
        base_system_prompt = system_prompt
        # 最大2回まで再試行。毎回異なるノンスでバリエーションを促す
        attempts = 2
        last_error = None
        error_details = []
        allow_temperature = not _should_use_responses_api(selected_model)
        
        for attempt in range(attempts):
            print(f"  試行 {attempt + 1}/{attempts}")
            nonce = uuid.uuid4().hex[:8]
            guidance_block = f"[Guidance] {guidance}\n" if guidance else ""
            # 強度に応じた具体的な指示を生成（簡潔版）
            strength_rules = {
                0: ["minimal changes", "keep structure", "preserve concepts"],
                1: ["gentle improvements", "enhance descriptors", "maintain structure"],
                2: ["moderate enhancements", "vivid language", "improve composition"],
                3: ["bold transformations", "dramatic descriptors", "cinematic style"]
            }
            
            current_rules = strength_rules.get(strength, strength_rules[2])
            
            # プロンプトを簡潔にしてトークン使用量を削減
            if strength == 3:
                user_prompt = (
                    f"Preset: {preset}, Strength: {strength} (MAXIMUM CREATIVITY)\n"
                    f"Nonce: {nonce}\n"
                    + (f"Guidance: {guidance}\n" if guidance else "") +
                    f"Rules: Be BOLD and CREATIVE while preserving original elements\n"
                    f"Strength rules: {'; '.join(current_rules)}\n"
                    f"Blend weight target: ~{blend_weight}% guidance / ~{100 - blend_weight}% original\n"
                    + (f"Anchor terms (verbatim): {', '.join(anchor_terms)}\n" if anchor_terms else "") +
                    f"CRITICAL: Include at least {must_keep_count} of the anchor terms verbatim. Keep the original subject and cultural motifs.\n"
                    + ("Hybridization suggestions: " + "; ".join(hybrid_cues) + "\n" if hybrid_cues else "") +
                    f"VISIBLE HYBRIDIZATION: Apply 3–5 hybrid changes to surfaces or objects (materials, textures, subtle tech details).\n"
                    f"Express guidance mainly via lighting, palette, materials, VFX, and accessories. Do NOT replace the entire scene; avoid introducing brand-new subjects.\n"
                    f"Length adjustment: {length_adjust} (target: ~{target_length} chars, original: {original_length} chars)\n"
                    f"CRITICAL: Make the output {'shorter' if target_length < original_length else 'longer' if target_length > original_length else 'similar'} than the original\n"
                    f"Prompt: {text}"
                )
            else:
                # 強度に応じてガイダンスの適用度を調整
                guidance_instruction = ""
                if strength == 0:
                    guidance_instruction = "Apply guidance very subtly if at all. Focus on minimal improvements."
                elif strength == 1:
                    guidance_instruction = "Apply guidance gently. Blend it subtly with the original content."
                elif strength == 2:
                    guidance_instruction = "Apply guidance moderately. Enhance the style while keeping core elements."
                
                user_prompt = (
                    f"Preset: {preset}, Strength: {strength} (0=minimal, 3=bold)\n"
                    f"Nonce: {nonce}\n"
                    + (f"Guidance: {guidance}\n" if guidance else "") +
                    f"Guidance instruction: {guidance_instruction}\n"
                    f"Rules: Keep core content, enhance style per strength level. If and only if the original ends with --options, preserve them exactly; otherwise do NOT add any --options\n"
                    f"Strength rules: {'; '.join(current_rules)}\n"
                    f"Blend weight target: ~{blend_weight}% guidance / ~{100 - blend_weight}% original\n"
                    + (f"Anchor terms (verbatim): {', '.join(anchor_terms)}\n" if anchor_terms else "") +
                    f"CRITICAL: Include at least {must_keep_count} of the anchor terms verbatim. Keep the original subject and cultural motifs.\n"
                    + ("Hybridization suggestions: " + "; ".join(hybrid_cues) + "\n" if hybrid_cues else "") +
                    f"VISIBLE HYBRIDIZATION: Apply 3–5 hybrid changes to surfaces or objects (materials, textures, subtle tech details).\n"
                    f"Express guidance mainly via lighting, palette, materials, VFX, and accessories. Do NOT replace the entire scene; avoid introducing brand-new subjects.\n"
                    f"Length adjustment: {length_adjust} (target: ~{target_length} chars, original: {original_length} chars)\n"
                    f"CRITICAL: Make the output {'shorter' if target_length < original_length else 'longer' if target_length > original_length else 'similar'} than the original\n"
                    f"Important: Adjust length to {'shorter' if target_length < original_length else 'longer' if target_length > original_length else 'similar'} than original\n"
                    f"Prompt: {text}"
                )

            system_prompt = base_system_prompt
            # 強度に応じてtemperatureを調整（より創造的な変化を促す）
            base_temperature = LLM_TEMPERATURE if LLM_INCLUDE_TEMPERATURE and LLM_TEMPERATURE is not None else 0.7
            strength_temperature = {
                0: min(base_temperature * 0.5, 0.3),  # 低い創造性
                1: min(base_temperature * 0.8, 0.6),  # 中程度の創造性
                2: min(base_temperature * 1.2, 0.9),  # 高い創造性
                3: min(base_temperature * 1.5, 1.0)   # 最大の創造性
            }
            adjusted_temperature = strength_temperature.get(strength, base_temperature)
            system_prompt = self._append_temperature_hint_for_model(system_prompt, adjusted_temperature)
            
            try:
                print(f"    プロンプト長: {len(user_prompt)} 文字")
                print(f"    システムプロンプト長: {len(system_prompt)} 文字")
                print(f"    トークン制限: {LLM_MAX_COMPLETION_TOKENS}")
                raw_content, finish_reason, data = send_llm_request(
                    api_key=api_key,
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    temperature=adjusted_temperature,
                    max_tokens=LLM_MAX_COMPLETION_TOKENS,
                    timeout=LLM_TIMEOUT,
                    model_name=selected_model,
                    include_temperature=allow_temperature
                )
            except requests.HTTPError as e:
                resp = getattr(e, "response", None)
                resp_text = ""
                if resp is not None:
                    try:
                        resp_text = resp.text
                    except Exception:
                        resp_text = ""
                error_msg = f"HTTPエラー: {e}"
                error_hint = _summarize_http_error_response(resp)
                print(f"    {error_msg}")
                if error_hint:
                    print(f"    HTTPエラー詳細: {error_hint}")
                detail_entry = f"試行{attempt + 1}: {error_msg}"
                if error_hint:
                    detail_entry = f"{detail_entry} | {error_hint}"
                error_details.append(detail_entry)
                last_error = e
                if resp is not None and resp.status_code == 400 and 'temperature' in (resp_text or ""):
                    print(f"    temperature未対応のため再試行")
                    try:
                        raw_content, finish_reason, data = send_llm_request(
                            api_key=api_key,
                            system_prompt=system_prompt,
                            user_prompt=user_prompt,
                            temperature=adjusted_temperature,
                            max_tokens=LLM_MAX_COMPLETION_TOKENS,
                            timeout=LLM_TIMEOUT,
                            model_name=selected_model,
                            include_temperature=False
                        )
                        print(f"    temperature除去フォールバック成功")
                    except Exception as fallback_error:
                        fallback_msg = f"フォールバック失敗: {fallback_error}"
                        print(f"    {fallback_msg}")
                        error_details.append(f"試行{attempt + 1}: {fallback_msg}")
                        last_error = fallback_error
                        continue
                else:
                    continue
            except requests.exceptions.Timeout as e:
                error_msg = f"タイムアウト: {e}"
                print(f"    {error_msg}")
                error_details.append(f"試行{attempt + 1}: {error_msg}")
                last_error = e
                continue
            except requests.exceptions.ConnectionError as e:
                error_msg = f"接続エラー: {e}"
                print(f"    {error_msg}")
                error_details.append(f"試行{attempt + 1}: {error_msg}")
                last_error = e
                continue
            except Exception as e:
                error_msg = f"予期しないエラー: {e}"
                print(f"    {error_msg}")
                error_details.append(f"試行{attempt + 1}: {error_msg}")
                last_error = e
                continue

            print(f"    レスポンス構造: {data.keys()}")
            if "choices" in data and len(data["choices"]) > 0:
                print(f"    choices[0]構造: {data['choices'][0].keys()}")
            elif "output" in data and len(data["output"]) > 0:
                print(f"    output[0]構造: {data['output'][0].keys()}")
            print(f"    生レスポンス: '{raw_content}'")
            print(f"    終了理由: {finish_reason}")
            
            if finish_reason in LENGTH_LIMIT_REASONS:
                usage_info = data.get("usage", {})
                prompt_tokens = usage_info.get("prompt_tokens", usage_info.get("input_tokens", 0))
                completion_tokens = usage_info.get("completion_tokens", usage_info.get("output_tokens", 0))
                total_tokens = usage_info.get("total_tokens", prompt_tokens + completion_tokens)
                print(f"    警告: トークン制限に達しました。")
                print(f"      プロンプトトークン: {prompt_tokens}")
                print(f"      完了トークン: {completion_tokens}")
                print(f"      総トークン: {total_tokens}")
                print(f"      制限: {LLM_MAX_COMPLETION_TOKENS}")
                print(f"    対策: プロンプトを短縮するか、トークン制限を増やしてください。")
                error_details.append(
                    f"試行{attempt + 1}: トークン制限に達しました (prompt:{prompt_tokens}, completion:{completion_tokens}, limit:{LLM_MAX_COMPLETION_TOKENS})"
                )
                continue
            
            if not raw_content:
                print(f"    警告: レスポンスが空です")
                print(f"    完全なレスポンス: {data}")
                error_details.append(f"試行{attempt + 1}: レスポンスが空です")
                continue
                    
            content = sanitize_to_english(raw_content)
            print(f"    レスポンス取得成功: {len(content)} 文字")
            
            # 同一チェック：完全一致ならもう一度試行
            if content.strip() == text.strip():
                print(f"    同一内容のため再試行")
                error_details.append(f"試行{attempt + 1}: 同一内容が返されました")
                continue
            # 元にオプションがなければ付与しない。ある場合のみ継承
            return self._inherit_options_if_present(text, content)

        # ここまで到達したらエラー表示
        print(f"  全試行失敗")
        print(f"  収集したエラー詳細: {error_details}")
        
        if last_error is not None:
            try:
                error_summary = f"LLMアレンジが繰り返し失敗しました:\n\nプリセット: {preset}\n強度: {strength}\n\nエラー詳細:\n" + "\n".join(error_details)
                print(f"LLMアレンジエラー詳細:\n{error_summary}")
                # エラー詳細をインスタンス変数に保存（呼び出し元で取得するため）
                self._last_error_details = error_details
                print(f"  エラー詳細を保存: {self._last_error_details}")
            except Exception as e:
                print(f"LLMアレンジエラー（詳細不明）: {str(e)}")
                self._last_error_details = [f"エラー詳細の取得に失敗: {str(e)}"]
                print(f"  エラー詳細保存失敗: {self._last_error_details}")
        else:
            self._last_error_details = ["エラーの詳細が不明です"]
            print(f"  エラー詳細不明: {self._last_error_details}")
        
        print(f"  最終的なエラー詳細: {self._last_error_details}")
        return None

    def update_exclusion_words(self):
        new_words = [word.strip() for word in self.combo_exclusion_words.get().split(',') if word.strip()]
        new_words.sort()
        new_phrase = ", ".join(new_words)
        
        current_words = load_exclusion_words()
        if new_phrase and new_phrase not in current_words:
            with open(EXCLUSION_CSV, 'a', encoding='utf-8', newline='') as file:
                writer = csv.writer(file, quotechar='"', quoting=csv.QUOTE_ALL)
                writer.writerow([new_phrase])
            
            # プルダウンメニューを更新
            updated_words = load_exclusion_words()
            self.combo_exclusion_words['values'] = updated_words

    def _split_prompt_and_options(self, text: str):
        """末尾の Midjourney オプション群（--ar/--s/--chaos/--q/--weird）を検出して主文と分離する。
        戻り値: (main_text, options_tail, has_options)
        - 末尾が許可された --key とその値（最大1トークン）だけの連続ならそれを尾部とみなす。
        - それ以外は尾部なしとして扱う。
        """
        try:
            tokens = (text or "").strip().split()
            if not tokens:
                return "", "", False
            allowed = {"--ar", "--s", "--chaos", "--q", "--weird"}
            # 末尾側からスキャンして最初の許可オプション位置を見つける
            start_idx = None
            i = len(tokens) - 1
            while i >= 0:
                if tokens[i] in allowed:
                    start_idx = i
                    # 値を1トークン許容
                    i -= 1
                    if i >= 0 and tokens[i] not in allowed and not tokens[i].startswith("--"):
                        # 値だったのでさらにもう一つ戻る
                        i -= 1
                    # 続くオプション塊の先頭まで戻る
                    while i >= 0:
                        if tokens[i] in allowed:
                            i -= 1
                            if i >= 0 and tokens[i] not in allowed and not tokens[i].startswith("--"):
                                i -= 1
                        else:
                            break
                    # i は主文末の位置なので、オプション開始は i+1
                    start_idx = i + 1
                    break
                else:
                    i -= 1
            if start_idx is not None and 0 <= start_idx < len(tokens):
                # 妥当性チェック：start_idx 以降が allowed 群のみで構成されるか
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

    def _inherit_options_if_present(self, original_text: str, new_text: str) -> str:
        orig_main, orig_opts, has_opts = self._split_prompt_and_options(original_text)
        if has_opts:
            # 出力側は新規オプションを許さず、元の尾部のみ厳密継承
            new_main, _, _ = self._split_prompt_and_options(new_text)
            return (new_main + orig_opts)
        else:
            # 元に無い場合は、文中・末尾のどこにあってもオプション断片を全削除
            return self._strip_all_options(new_text)

    def _strip_all_options(self, text: str) -> str:
        try:
            # --ar / --s / --chaos / --q / --weird と、直後の値(1トークン)を削除。繰り返し対応
            pattern = r"(?:(?<=\s)|^)--(?:ar|s|chaos|q|weird)(?:\s+(?!-)[^\s]+)?"
            cleaned = re.sub(pattern, "", text)
            # 余分な空白を整理
            cleaned = re.sub(r"\s+", " ", cleaned).strip()
            return cleaned
        except Exception:
            return (text or "").strip()

    def _current_movie_tail_value(self) -> str:
        """現在のUI設定に基づき、movie用途で有効化されているJSON文字列を返す。"""
        try:
            if getattr(self, 'tail_media_type_var', None) is None:
                return ""
            if self.tail_media_type_var.get() != "movie":
                return ""
            if not getattr(self, 'add_tail_free_text_var1', None):
                return ""
            if not self.add_tail_free_text_var1.get():
                return ""
            value = (self.combo_tail_free_text1.get() or "").strip()
            return value
        except Exception:
            return ""

    def _detach_movie_tail_for_llm(self, text: str):
        """映画用JSONをLLM処理から除外するために主文から取り除く。"""
        text = (text or "").strip()
        tail_value = self._current_movie_tail_value()
        if not tail_value:
            return text, ""

        main_text, options_tail, _ = self._split_prompt_and_options(text)
        main_text = (main_text or "").rstrip()
        if main_text.endswith(tail_value):
            truncated = main_text[:-len(tail_value)].rstrip()
            if not truncated:
                # すべてがJSONだった場合は除去を見送り、変換前の全文を返す
                return text, ""
            rebuilt = (truncated + options_tail).strip()
            return rebuilt, tail_value
        return text, ""

    def _restore_movie_tail_after_llm(self, text: str, tail_value: str):
        """LLM処理後に映画用JSONを元の位置（オプションより前）へ戻す。"""
        text = (text or "").strip()
        if not tail_value:
            return text

        main_text, options_tail, _ = self._split_prompt_and_options(text)
        main_text = (main_text or "").rstrip()
        if main_text:
            restored_main = f"{main_text} {tail_value}".strip()
        else:
            restored_main = tail_value
        return (restored_main + options_tail).strip()

    def _visible_length_without_movie_tail(self, text: str) -> int:
        """UI上で提示する文字数（movie JSONを除外した長さ）を返す。"""
        cleaned, _ = self._detach_movie_tail_for_llm(text)
        return len(cleaned or "")

    def _extract_anchor_terms(self, text: str, max_terms: int = 8):
        """原文から保持すべきアンカー語句（名詞・象徴語）を抽出する簡易ロジック。
        - 英単語のうち、文化・自然・建築・和要素などを優先
        - 記号を除去し、短すぎる語を除く
        """
        try:
            cleaned = re.sub(r"[^A-Za-z0-9\-\s]", " ", text)
            tokens = [t.strip('-') for t in cleaned.split()]
            tokens = [t for t in tokens if len(t) >= 3]
            # 和風・自然・建築などのキーワードを優先
            priority = set([
                'cherry', 'blossom', 'blossoms', 'lantern', 'lanterns', 'temple', 'shrine', 'garden',
                'tea', 'bamboo', 'maple', 'zen', 'wabi', 'sabi', 'imperfection', 'architecture', 'wood', 'paper',
                'stone', 'bridge', 'pond', 'kimono', 'tatami', 'shoji', 'bonsai'
            ])
            scored = []
            for t in tokens:
                score = 1
                lt = t.lower()
                if lt in priority:
                    score += 3
                if any(k in lt for k in ['garden', 'temple', 'shrine', 'lantern', 'blossom', 'bamboo', 'maple', 'tea', 'zen']):
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

    def _generate_hybrid_cues(self, anchors, preset: str, guidance: str, max_items: int = 5):
        """任意のアンカー語をスタイル語彙と合成し、置き換えではなく“ハイブリッド化”を促すサジェストを動的生成する。"""
        try:
            if not anchors:
                return []
            preset_l = (preset or "").lower()
            guidance_l = (guidance or "").lower()
            def _style_key():
                keys = [preset_l, guidance_l]
                if any("cyber" in k for k in keys):
                    return "cyberpunk"
                if any("noir" in k for k in keys):
                    return "noir"
                if any(k in ("sci-fi", "scifi", "science fiction") for k in keys):
                    return "scifi"
                if any("vapor" in k for k in keys):
                    return "vaporwave"
                return "generic"
            style = _style_key()
            # スタイル別語彙
            vocab = {
                "cyberpunk": {
                    "materials": ["brushed metal", "titanium inlays", "carbon-fiber", "chromed edges", "micro-etched steel", "polymer plates"],
                    "lighting": ["neon rim-light", "cyan underglow", "magenta accent light", "dynamic LED seams", "HUD glow", "soft holographic glow"],
                    "vfx": ["holographic flicker", "pixel shimmer", "AR overlay", "scanline sheen", "glitch speckles", "volumetric haze"],
                    "detail": ["micro-circuit veins", "fiber-optic threads", "embedded sensors", "heat vents", "panel seams", "thin cabling"]
                },
                "noir": {
                    "materials": ["matte enamel", "lacquered wood", "worn steel", "velvet texture"],
                    "lighting": ["hard rim-light", "moody backlight", "rain-soaked reflections", "venetian blind shadows"],
                    "vfx": ["film grain", "soft bloom", "cigarette smoke wisps"],
                    "detail": ["sleek rivets", "aged patina", "subtle scratches"]
                },
                "scifi": {
                    "materials": ["brushed alloy", "ceramic composite", "graphene panels", "satin titanium"],
                    "lighting": ["cool rim-light", "ambient panel glow", "bioluminescent accents"],
                    "vfx": ["force-field shimmer", "ionized haze", "specular flares"],
                    "detail": ["hex-mesh patterns", "micro-actuators", "servo joints"]
                },
                "vaporwave": {
                    "materials": ["pastel plastic", "glossy acrylic", "pearlescent enamel"],
                    "lighting": ["pink-cyan gradient glow", "retro grid light", "soft bloom"],
                    "vfx": ["CRT scanlines", "pixel dust", "checkerboard reflections"],
                    "detail": ["chrome trims", "90s decals", "retro stickers"]
                },
                "generic": {
                    "materials": ["brushed metal", "ceramic-metal composite", "polished steel"],
                    "lighting": ["edge underglow", "accent rim-light", "soft backlight"],
                    "vfx": ["subtle holographic shimmer", "fine grain", "soft bloom"],
                    "detail": ["micro-engraving", "thin inlays", "fiber threads"]
                }
            }
            lex = vocab.get(style, vocab["generic"])
            templates = [
                "{a} with {materials} accents and {lighting}",
                "{a} featuring {detail} and a hint of {vfx}",
                "part of the {a} converted to {materials} with {lighting}",
                "{a} showing {detail} beneath the surface and subtle {vfx}",
                "{a} integrating {materials} inlays and {lighting}"
            ]
            cues = []
            # アンカーごとにテンプレートと語彙をローテーション
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

    def show_arrange_comparison_dialog(self, original_text, arranged_text, preset_label, strength):
        """アレンジ前後のプロンプトを比較表示するダイアログ"""
        dialog = tk.Toplevel(self.master)
        dialog.title("アレンジ完了 - プロンプト比較")
        
        # メインウィンドウの位置を取得してダイアログを配置
        master_x = self.master.winfo_x()
        master_y = self.master.winfo_y()
        dialog.geometry(f"800x600+{master_x + 50}+{master_y + 50}")
        
        # ダイアログをモーダルにする
        dialog.transient(self.master)
        dialog.grab_set()
        
        # ヘッダー情報
        header_frame = tk.Frame(dialog)
        header_frame.pack(fill='x', padx=10, pady=5)
        
        tk.Label(header_frame, text="アレンジ設定:", font=('Arial', 10, 'bold')).pack(anchor='w')
        try:
            fixed_value = (self.fixed_length_var.get() or "").strip()
        except Exception:
            fixed_value = ""
        length_adjust_label = f"固定{fixed_value}文字" if fixed_value.isdigit() else self.length_adjust_var.get()
        tk.Label(header_frame, text=f"プリセット: {preset_label} | 強度: {strength} | 文字数調整: {length_adjust_label}").pack(anchor='w')
        
        # 比較表示エリア
        comparison_frame = tk.Frame(dialog)
        comparison_frame.pack(fill='both', expand=True, padx=10, pady=5)
        
        # 左側：アレンジ前
        left_frame = tk.Frame(comparison_frame)
        left_frame.pack(side='left', fill='both', expand=True, padx=(0, 5))
        
        original_visible_length = self._visible_length_without_movie_tail(original_text)
        tk.Label(left_frame, text=f"アレンジ前: ({original_visible_length}文字)", font=('Arial', 10, 'bold')).pack(anchor='w')
        original_text_widget = tk.scrolledtext.ScrolledText(
            left_frame, 
            wrap=tk.WORD, 
            width=40, 
            height=15,
            font=('Consolas', 9)
        )
        original_text_widget.pack(fill='both', expand=True)
        original_text_widget.insert('1.0', original_text)
        original_text_widget.config(state='disabled')
        
        # 右側：アレンジ後
        right_frame = tk.Frame(comparison_frame)
        right_frame.pack(side='right', fill='both', expand=True, padx=(5, 0))
        
        arranged_visible_length = self._visible_length_without_movie_tail(arranged_text)
        tk.Label(right_frame, text=f"アレンジ後: ({arranged_visible_length}文字)", font=('Arial', 10, 'bold')).pack(anchor='w')
        arranged_text_widget = tk.scrolledtext.ScrolledText(
            right_frame, 
            wrap=tk.WORD, 
            width=40, 
            height=15,
            font=('Consolas', 9)
        )
        arranged_text_widget.pack(fill='both', expand=True)
        arranged_text_widget.insert('1.0', arranged_text)
        arranged_text_widget.config(state='disabled')
        
        # ボタンエリア
        button_frame = tk.Frame(dialog)
        button_frame.pack(fill='x', padx=10, pady=10)
        
        # アレンジ後をコピーするボタン
        copy_button = tk.Button(
            button_frame, 
            text="アレンジ後をクリップボードにコピー", 
            command=lambda: self.copy_text_to_clipboard(arranged_text, dialog)
        )
        copy_button.pack(side='left', padx=(0, 10))
        
        # 閉じるボタン
        close_button = tk.Button(
            button_frame, 
            text="閉じる", 
            command=dialog.destroy
        )
        close_button.pack(side='right')
        
        # # 完了通知
        # before_len = self._visible_length_without_movie_tail(original_text)
        # after_len = self._visible_length_without_movie_tail(arranged_text)
        # messagebox.showinfo("アレンジ完了", f"プロンプトのアレンジが完了しました。\nプリセット: {preset_label}\n強度: {strength}\n文字数調整: {self.length_adjust_var.get()}\n文字数: {before_len} → {after_len}")

    def copy_text_to_clipboard(self, text, dialog):
        """テキストをクリップボードにコピー"""
        self.master.clipboard_clear()
        self.master.clipboard_append(text)
        messagebox.showinfo("コピー完了", "アレンジ後のプロンプトをクリップボードにコピーしました。")

    def show_detailed_error_dialog(self, title, error_message, preset_label, strength):
        """詳細なエラー情報を表示するダイアログ"""
        dialog = tk.Toplevel(self.master)
        dialog.title(title)
        
        # メインウィンドウの位置を取得してダイアログを配置
        master_x = self.master.winfo_x()
        master_y = self.master.winfo_y()
        dialog.geometry(f"600x500+{master_x + 50}+{master_y + 50}")
        
        # ダイアログをモーダルにする
        dialog.transient(self.master)
        dialog.grab_set()
        
        # メインフレーム
        main_frame = tk.Frame(dialog)
        main_frame.pack(fill='both', expand=True, padx=10, pady=10)
        
        # タイトル
        title_label = tk.Label(main_frame, text=title, font=('Arial', 12, 'bold'))
        title_label.pack(anchor='w', pady=(0, 10))
        
        # エラーメッセージ（スクロール可能）
        error_frame = tk.Frame(main_frame)
        error_frame.pack(fill='both', expand=True, pady=(0, 10))
        
        error_label = tk.Label(error_frame, text="エラー詳細:", font=('Arial', 10, 'bold'))
        error_label.pack(anchor='w')
        
        error_text = tk.scrolledtext.ScrolledText(
            error_frame,
            wrap=tk.WORD,
            width=70,
            height=15,
            font=('Consolas', 9)
        )
        error_text.pack(fill='both', expand=True)
        error_text.insert('1.0', error_message)
        error_text.config(state='disabled')
        
        # 設定情報
        info_frame = tk.Frame(main_frame)
        info_frame.pack(fill='x', pady=(0, 10))
        
        tk.Label(info_frame, text="現在の設定:", font=('Arial', 10, 'bold')).pack(anchor='w')
        tk.Label(info_frame, text=f"• プリセット: {preset_label}").pack(anchor='w')
        tk.Label(info_frame, text=f"• 強度: {strength}").pack(anchor='w')
        tk.Label(info_frame, text=f"• モデル: {self.get_selected_model()}").pack(anchor='w')
        tk.Label(info_frame, text=f"• タイムアウト: {LLM_TIMEOUT}秒").pack(anchor='w')
        
        # ボタンエリア
        button_frame = tk.Frame(main_frame)
        button_frame.pack(fill='x')
        
        # エラー詳細をコピーするボタン
        copy_button = tk.Button(
            button_frame,
            text="エラー詳細をコピー",
            command=lambda: self.copy_error_to_clipboard(error_message, dialog)
        )
        copy_button.pack(side='left', padx=(0, 10))
        
        # 閉じるボタン
        close_button = tk.Button(
            button_frame,
            text="閉じる",
            command=dialog.destroy
        )
        close_button.pack(side='right')

    def copy_error_to_clipboard(self, error_message, dialog):
        """エラーメッセージをクリップボードにコピー"""
        self.master.clipboard_clear()
        self.master.clipboard_append(error_message)
        messagebox.showinfo("コピー完了", "エラー詳細をクリップボードにコピーしました。")

    def show_length_adjust_comparison_dialog(self, original_text, adjusted_text, length_adjust):
        """文字数調整前後のプロンプトを比較表示するダイアログ"""
        dialog = tk.Toplevel(self.master)
        dialog.title("文字数調整完了 - プロンプト比較")
        
        # メインウィンドウの位置を取得してダイアログを配置
        master_x = self.master.winfo_x()
        master_y = self.master.winfo_y()
        dialog.geometry(f"800x600+{master_x + 50}+{master_y + 50}")
        
        # ダイアログをモーダルにする
        dialog.transient(self.master)
        dialog.grab_set()
        
        # ヘッダー情報
        header_frame = tk.Frame(dialog)
        header_frame.pack(fill='x', padx=10, pady=5)
        
        tk.Label(header_frame, text="文字数調整設定:", font=('Arial', 10, 'bold')).pack(anchor='w')
        before_visible = self._visible_length_without_movie_tail(original_text)
        after_visible = self._visible_length_without_movie_tail(adjusted_text)
        tk.Label(header_frame, text=f"調整設定: {length_adjust} | 文字数: {before_visible} → {after_visible}").pack(anchor='w')
        
        # 比較表示エリア
        comparison_frame = tk.Frame(dialog)
        comparison_frame.pack(fill='both', expand=True, padx=10, pady=5)
        
        # 左側：調整前
        left_frame = tk.Frame(comparison_frame)
        left_frame.pack(side='left', fill='both', expand=True, padx=(0, 5))
        
        tk.Label(left_frame, text=f"調整前: ({before_visible}文字)", font=('Arial', 10, 'bold')).pack(anchor='w')
        original_text_widget = tk.scrolledtext.ScrolledText(
            left_frame, 
            wrap=tk.WORD, 
            width=40, 
            height=15,
            font=('Consolas', 9)
        )
        original_text_widget.pack(fill='both', expand=True)
        original_text_widget.insert('1.0', original_text)
        original_text_widget.config(state='disabled')
        
        # 右側：調整後
        right_frame = tk.Frame(comparison_frame)
        right_frame.pack(side='right', fill='both', expand=True, padx=(5, 0))
        
        tk.Label(right_frame, text=f"調整後: ({after_visible}文字)", font=('Arial', 10, 'bold')).pack(anchor='w')
        adjusted_text_widget = tk.scrolledtext.ScrolledText(
            right_frame, 
            wrap=tk.WORD, 
            width=40, 
            height=15,
            font=('Consolas', 9)
        )
        adjusted_text_widget.pack(fill='both', expand=True)
        adjusted_text_widget.insert('1.0', adjusted_text)
        adjusted_text_widget.config(state='disabled')
        
        # ボタンエリア
        button_frame = tk.Frame(dialog)
        button_frame.pack(fill='x', padx=10, pady=10)
        
        # 調整後をコピーするボタン
        copy_button = tk.Button(
            button_frame, 
            text="調整後をクリップボードにコピー", 
            command=lambda: self.copy_text_to_clipboard(adjusted_text, dialog)
        )
        copy_button.pack(side='left', padx=(0, 10))
        
        # 閉じるボタン
        close_button = tk.Button(
            button_frame, 
            text="閉じる", 
            command=dialog.destroy
        )
        close_button.pack(side='right')
        
        # # 完了通知
        # before_len = self._visible_length_without_movie_tail(original_text)
        # after_len = self._visible_length_without_movie_tail(adjusted_text)
        # messagebox.showinfo("文字数調整完了", f"プロンプトの文字数調整が完了しました。\n調整設定: {length_adjust}\n文字数: {before_len} → {after_len}")

def load_exclusion_words():
    try:
        with open(EXCLUSION_CSV, 'r', encoding='utf-8', newline='') as file:
            reader = csv.reader(file, quotechar='"', quoting=csv.QUOTE_ALL)
            return [""] + [row[0] for row in reader if row]
    except FileNotFoundError:
        return [""]

def load_arrange_presets(yaml_path: str):
    try:
        print(f"プリセットファイルを読み込み中: {yaml_path}")
        with open(yaml_path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f) or {}
        presets = data.get('presets', [])
        print(f"YAMLから読み込んだプリセット数: {len(presets)}")
        normalized = []
        for p in presets:
            normalized.append({
                'id': p.get('id') or p.get('key') or p.get('name'),
                'label': p.get('label') or p.get('name') or p.get('id'),
                'guidance': p.get('guidance') or ''
            })
        result = [p for p in normalized if p['id']]
        print(f"正規化後のプリセット数: {len(result)}")
        for preset in result:
            print(f"  - {preset['label']} (id: {preset['id']})")
        return result
    except FileNotFoundError:
        print(f"プリセットファイルが見つかりません: {yaml_path}")
        return []
    except Exception as e:
        print(f"プリセット読み込みエラー: {e}")
        return []

def sanitize_to_english(text: str) -> str:
    """基本的に英語出力を維持するための軽いサニタイズ。
    - 代表的な日本語キーワードを英語に置換（最後の砦）
    """
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



# YAML設定ファイルパス
yaml_settings_path = _resolve_path('desktop_gui_settings.yaml')
settings = load_yaml_settings(yaml_settings_path)
BASE_FOLDER = settings["app_image_prompt_creator"]["BASE_FOLDER"]
DEFAULT_TXT_PATH = settings["app_image_prompt_creator"]["DEFAULT_TXT_PATH"]
DEFAULT_DB_PATH = settings["app_image_prompt_creator"]["DEFAULT_DB_PATH"]
POSITION_FILE = settings["app_image_prompt_creator"]["POSITION_FILE"]
EXCLUSION_CSV = settings["app_image_prompt_creator"]["EXCLUSION_CSV"]
LLM_ENABLED       = settings["app_image_prompt_creator"].get("LLM_ENABLED", False)
LLM_MODEL         = settings["app_image_prompt_creator"].get("LLM_MODEL", "gpt-5-mini")
LLM_TEMPERATURE   = settings["app_image_prompt_creator"].get("LLM_TEMPERATURE", 0.7)
LLM_MAX_COMPLETION_TOKENS = settings["app_image_prompt_creator"].get("LLM_MAX_COMPLETION_TOKENS", 4500)
LLM_TIMEOUT       = settings["app_image_prompt_creator"].get("LLM_TIMEOUT", 30)
OPENAI_API_KEY_ENV= settings["app_image_prompt_creator"].get("OPENAI_API_KEY_ENV", "OPENAI_API_KEY")
ARRANGE_PRESETS_YAML = str(_resolve_path(settings["app_image_prompt_creator"].get("ARRANGE_PRESETS_YAML", "app_image_prompt_creator/arrange_presets.yaml")))
LLM_INCLUDE_TEMPERATURE = settings["app_image_prompt_creator"].get("LLM_INCLUDE_TEMPERATURE", False)

print(f"[LLM] 設定ファイルの既定モデル: {LLM_MODEL}")

def _should_use_responses_api(model_name: str) -> bool:
    """gpt-5系モデルかどうかを判定し、Responses APIへの切り替え要否を返却する。"""
    if not model_name:
        return False
    target = model_name.strip().lower()
    return any(target.startswith(prefix) for prefix in RESPONSES_MODEL_PREFIXES)

def _build_responses_input(system_prompt: str, user_prompt: str):
    """Responses API用のmessage表現を生成する。
    2025-11時点の仕様ではユーザー／システムともに `input_text` を使用する。
    """
    def build_block(role: str, text: str):
        content_type = "input_text"
        return {
            "role": role,
            "content": [
                {
                    "type": content_type,
                    "text": text or ""
                }
            ]
        }
    blocks = []
    if system_prompt is not None:
        blocks.append(build_block("system", system_prompt))
    blocks.append(build_block("user", user_prompt or ""))
    return blocks

def _temperature_hint_for_responses(model_name: str, temperature: float) -> str:
    """gpt-5系向けに、旧temperature設定を文章で補助指示化する。"""
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

def _compose_openai_payload(system_prompt: str, user_prompt: str, temperature: float, max_tokens: int, include_temperature: bool, model_name: str):
    """
    モデル種別に応じてChat Completions/Responses APIの差異を吸収したpayloadとエンドポイントを返す。
    """
    model = model_name or LLM_MODEL
    use_responses = _should_use_responses_api(model)
    payload = {"model": model}
    if use_responses:
        payload["input"] = _build_responses_input(system_prompt, user_prompt)
        if max_tokens is not None:
            payload["max_output_tokens"] = max_tokens
        endpoint = RESPONSES_API_URL
        response_kind = "responses"
    else:
        payload["messages"] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        if max_tokens is not None:
            payload["max_completion_tokens"] = max_tokens
        endpoint = CHAT_COMPLETIONS_URL
        response_kind = "chat"
    send_temperature = include_temperature and (temperature is not None) and not use_responses
    if send_temperature:
        payload["temperature"] = temperature
    return endpoint, payload, response_kind

def _summarize_http_error_response(resp: requests.Response) -> str:
    """OpenAI HTTPエラー内容を抜粋し、調査向けに要約する。"""
    if resp is None:
        return ""
    request_id = resp.headers.get("x-request-id") or resp.headers.get("x-requestid")
    summary = ""
    try:
        data = resp.json()
    except ValueError:
        data = None
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

def _parse_openai_response(response_kind: str, data: dict):
    """レスポンス構造の差分を吸収し、本文と終了理由を抽出する。"""
    if response_kind == "responses":
        output = data.get("output", [])
        texts = []
        finish_reason = ""
        for item in output or []:
            finish_reason = finish_reason or item.get("stop_reason", "")
            if item.get("type") != "message":
                continue
            for content in item.get("content", []):
                # 2025-11時点のResponses APIでは `type: "output_text"` で返ってくるケースがある
                # 既存の `type: "text"` と両対応させる
                ctype = content.get("type")
                if ctype in ("text", "output_text"):
                    # 現行仕様ではフィールド名は常に "text"
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

def send_llm_request(api_key: str, system_prompt: str, user_prompt: str, temperature: float, max_tokens: int, timeout: int, model_name: str, include_temperature: bool = True):
    """
    OpenAI API（Chat/Responses）への共通リクエスト送信関数。
    gpt-5以降の仕様差異を内部で吸収し、本文と終了理由を返す。
    """
    endpoint, payload, response_kind = _compose_openai_payload(system_prompt, user_prompt, temperature, max_tokens, include_temperature, model_name)
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    kind_label = "responses" if response_kind == "responses" else "chat"
    print(f"    APIリクエスト送信中... (モデル: {model_name or LLM_MODEL}, endpoint: {endpoint.rsplit('/', 1)[-1]}, kind: {kind_label})")
    if response_kind == "responses":
        block_summaries = []
        for block in payload.get("input", []):
            role = block.get("role", "?")
            content_types = [
                item.get("type", "?")
                for item in (block.get("content") or [])
            ]
            joined_types = "/".join([t for t in content_types if t]) or "?"
            block_summaries.append(f"{role}:{joined_types}")
        print(f"    payload概要: blocks={block_summaries}, max_output_tokens={payload.get('max_output_tokens')}")
    else:
        print(f"    payload概要: messages={len(payload.get('messages', []))}, max_completion_tokens={payload.get('max_completion_tokens')}")
    resp = requests.post(endpoint, headers=headers, json=payload, timeout=timeout)
    print(f"    レスポンスステータス: {resp.status_code}")
    resp.raise_for_status()
    data = resp.json()
    text, finish_reason = _parse_openai_response(response_kind, data)
    return text, finish_reason, data

DEFAULT_EXCLUSION_WORDS = load_exclusion_words()

if __name__ == '__main__':
    try:
        root = tk.Tk()
        app = TextGeneratorApp(root)
        
        # restore_position(root)
        root.protocol("WM_DELETE_WINDOW", on_close)  # 終了時処理の設定
        
        root.mainloop()
    except:
        print(get_exception_trace())
