# -*- coding: utf-8 -*-
# アプリ名: 9. 画像プロンプトランダム生成ツール

import sys
import traceback
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
from pathlib import Path
from export_prompts_to_csv import MJImage

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
FREE_TEXTS = [
    "",
    "A high resolution photograph. Very high resolution. 8K photo",
    "a Japanese ink painting. Zen painting",
    "a Medieval European painting."
    ]
S_OPTIONS = ["", "0", "10", "20", "30", "40", "50", "100", "150", "200", "250", "300", "400", "500", "600", "700", "800", "900", "1000"]
AR_OPTIONS = ["", "16:9", "9:16", "4:3", "3:4"]  # 'ar'オプションの項目
CHAOS_OPTIONS = ["", "0", "10", "20", "30", "40", "50", "60", "70", "80", "90", "100"]  # 'chaos'オプションの項目
Q_OPTIONS = ["", "1", "2"]
WEIRD_OPTIONS = ["", "0", "10", "20", "30", "40", "50", "100", "150", "200", "250", "500", "750", "1000", "1250", "1500", "1750", "2000", "2250", "2500", "2750", "3000"]  # 'weird'オプションの項目

# 定数としてホスト名を取得
HOSTNAME = socket.gethostname()

# YAMLファイルを読み込むための関数
def load_yaml_settings(file_path):
    """
    指定されたパスのYAMLファイルを読み込んで、設定を辞書として返す。
    """
    with open(file_path, 'r', encoding="utf-8") as file:
        # yamlモジュールを使用して設定ファイルを読み込む
        settings = yaml.safe_load(file)
    return settings

def save_position(root):
    """
    ウィンドウの位置とサイズをCSVファイルに保存する。
    """
    print("ウィンドウ位置を保存中...")
    position_data = [HOSTNAME, root.geometry()]
    print(f"保存データ: {position_data}")
    with open(POSITION_FILE, 'w', newline='', encoding="utf_8_sig") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(position_data)
    print("保存完了")

def restore_position(root):
    """
    CSVファイルからウィンドウの位置とサイズを復元する。
    """
    print("ウィンドウ位置を復元中...")
    try:
        with open(POSITION_FILE, newline='', encoding="utf_8_sig") as csvfile:
            reader = csv.reader(csvfile)
            for row in reader:
                if row[0] == HOSTNAME:
                    print(f"復元データ: {row[1]}")
                    root.geometry(row[1])
                    break
    except FileNotFoundError:
        print("位置情報ファイルが見つかりません。")

# アプリケーションの終了時の処理をカスタマイズする
def on_close():
    save_position(root)  # ウィンドウの位置を保存
    root.destroy()  # ウィンドウを破壊する

def get_exception_trace():
    '''例外のトレースバックを取得'''
    t, v, tb = sys.exc_info()
    trace = traceback.format_exception(t, v, tb)
    return trace

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

        # 末尾テキスト入力UI(固定文1)
        self.tail_free_text_frame1 = tk.Frame(self.main_frame)
        self.tail_free_text_frame1.pack(fill='x')
        self.add_tail_free_text_var1 = tk.BooleanVar()
        self.checkbox_tail_free_text1 = tk.Checkbutton(self.tail_free_text_frame1, variable=self.add_tail_free_text_var1, font=TAIL_FREE_FONT_SIZE)
        self.checkbox_tail_free_text1.pack(side='right')
        self.combo_tail_free_text1 = ttk.Combobox(self.tail_free_text_frame1, values=FREE_TEXTS, width=25, font=TAIL_FREE_FONT_SIZE)
        self.combo_tail_free_text1.pack(side='right')
        self.combo_tail_free_text1.bind("<<ComboboxSelected>>", self.auto_update)
        self.label_tail_free_text1 = tk.Label(self.tail_free_text_frame1, text=LABEL_TAIL_FREE1)
        self.label_tail_free_text1.pack(side='left')

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

        # 変数初期化
        self.file_lines = []
        self.main_prompt = ""
        self.option_prompt = ""
        self.tail_free_texts = ""

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

    def open_csv_import_window(self):
        CSVImportWindow(self.master, self.update_attribute_details)

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

# YAML設定ファイルパス
yaml_settings_path = 'desktop_gui_settings.yaml'
settings = load_yaml_settings(yaml_settings_path)
BASE_FOLDER = settings["app_image_prompt_creator"]["BASE_FOLDER"]
DEFAULT_TXT_PATH = settings["app_image_prompt_creator"]["DEFAULT_TXT_PATH"]
DEFAULT_DB_PATH = settings["app_image_prompt_creator"]["DEFAULT_DB_PATH"]
POSITION_FILE = settings["app_image_prompt_creator"]["POSITION_FILE"]

if __name__ == '__main__':
    try:
        root = tk.Tk()
        app = TextGeneratorApp(root)
        
        restore_position(root)
        root.protocol("WM_DELETE_WINDOW", on_close)  # 終了時処理の設定
        
        root.mainloop()
    except:
        print(get_exception_trace())
