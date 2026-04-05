"""開発環境向けの起動補助スクリプト。

- macOS を含む各OSで、リポジトリ直下を作業ディレクトリに固定して起動する。
- 設定ファイル未配置時はテンプレートから自動生成して初回起動の失敗を防ぐ。
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Sequence


def get_repo_root() -> Path:
    """このスクリプト位置を基準にリポジトリルートを返す。"""

    return Path(__file__).resolve().parents[1]


def ensure_settings_file(repo_root: Path) -> bool:
    """設定ファイルが無い場合のみ example から生成する。

    Returns:
        bool: 新規生成した場合は True。
    """

    target = repo_root / "desktop_gui_settings.yaml"
    template = repo_root / "desktop_gui_settings.yaml.example"

    if target.exists():
        return False
    if not template.exists():
        raise FileNotFoundError(
            "desktop_gui_settings.yaml.example が見つからないため初期設定を生成できません。"
        )

    # Why: 初回セットアップで最も起きやすい「設定ファイル未配置」を自動解消するため。
    shutil.copyfile(template, target)
    return True


def build_launch_command(repo_root: Path) -> Sequence[str]:
    """アプリ起動コマンドを構築する。"""

    return [sys.executable, str(repo_root / "app_image_prompt_creator_qt.py")]


def parse_args() -> argparse.Namespace:
    """CLI引数を解釈する。"""

    parser = argparse.ArgumentParser(description="アプリ起動補助スクリプト")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="実行せず、最終的に使う起動コマンドだけ表示します。",
    )
    return parser.parse_args()


def main() -> int:
    """開発向けの安全な起動フローを実行する。"""

    args = parse_args()
    repo_root = get_repo_root()
    created = ensure_settings_file(repo_root)

    if created:
        print("[INFO] desktop_gui_settings.yaml をテンプレートから生成しました。")

    command = build_launch_command(repo_root)
    print(f"[INFO] launch command: {' '.join(command)}")

    if args.dry_run:
        return 0

    completed = subprocess.run(command, cwd=repo_root, check=False)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
