"""CIやローカルチェックで必須ファイルの存在を検証するスクリプト。"""
from __future__ import annotations

from pathlib import Path
import sys
from typing import List

# 追加の必須ファイルが増えた場合はここに列挙する。
REQUIRED_FILES: List[Path] = [
    Path("export_prompts_to_csv.py"),
    Path("desktop_gui_settings.yaml.example"),
]


def main() -> int:
    """必須ファイルが揃っているかを確認し、欠損時は終了コード1で通知する。"""

    missing = [path for path in REQUIRED_FILES if not path.exists()]
    if missing:
        print("[NG] 以下の必須ファイルが見つかりません:")
        for path in missing:
            print(f" - {path}")
        print(
            "export_prompts_to_csv.py が無い場合はリポジトリの最新を取得するか、"
            "README に記載のリンク・pip手順から入手してください。"
        )
        return 1

    print("[OK] 必須ファイルはすべて揃っています。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
