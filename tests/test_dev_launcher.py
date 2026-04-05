from __future__ import annotations

from pathlib import Path

from scripts import dev_launcher


def test_ensure_settings_file_creates_from_example(tmp_path: Path) -> None:
    repo_root = tmp_path
    (repo_root / "desktop_gui_settings.yaml.example").write_text("sample: true\n", encoding="utf-8")

    created = dev_launcher.ensure_settings_file(repo_root)

    assert created is True
    assert (repo_root / "desktop_gui_settings.yaml").read_text(encoding="utf-8") == "sample: true\n"


def test_ensure_settings_file_does_not_overwrite_existing(tmp_path: Path) -> None:
    repo_root = tmp_path
    (repo_root / "desktop_gui_settings.yaml.example").write_text("sample: true\n", encoding="utf-8")
    (repo_root / "desktop_gui_settings.yaml").write_text("custom: 1\n", encoding="utf-8")

    created = dev_launcher.ensure_settings_file(repo_root)

    assert created is False
    assert (repo_root / "desktop_gui_settings.yaml").read_text(encoding="utf-8") == "custom: 1\n"


def test_build_launch_command_points_to_qt_entry(tmp_path: Path) -> None:
    command = dev_launcher.build_launch_command(tmp_path)

    assert len(command) == 2
    assert command[1] == str(tmp_path / "app_image_prompt_creator_qt.py")
