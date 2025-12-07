"""ログ周りの共通ヘルパー。"""

from __future__ import annotations

import json
import logging
import os
import platform
import sys
import traceback
from datetime import datetime
from pathlib import Path

from PySide6 import QtCore, QtWidgets

from . import config


class _HostnameContextFilter(logging.Filter):
    """ターミナル出力でホスト名を常に表示し、障害発生環境を即時判別できるようにする。"""

    def filter(self, record: logging.LogRecord) -> bool:  # type: ignore[override]
        record.hostname = config.HOSTNAME
        return True


def setup_logging() -> None:
    """ルートロガーの書式とフィルターを設定する。"""

    logging.basicConfig(level=logging.INFO, format=config.LOG_FORMAT, datefmt=config.LOG_DATETIME_FORMAT)
    try:
        import faulthandler

        faulthandler.enable()
    except Exception:
        logging.getLogger(__name__).warning("Failed to enable faulthandler; native crashes may lack stack traces.")
    logging.getLogger().addFilter(_HostnameContextFilter())


def _coerce_json_safe(value):
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (Path, datetime)):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _coerce_json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_coerce_json_safe(v) for v in value]
    return str(value)


def log_structured(level: int, event: str, context: dict | None = None) -> None:
    """環境依存の調査を容易にするため、ホスト名と経路情報を含む構造化ログを出力する。"""

    payload = {"event": event, "hostname": config.HOSTNAME}
    if context:
        safe_context = {str(k): _coerce_json_safe(v) for k, v in context.items()}
        payload.update(safe_context)
    logging.log(level, json.dumps(payload, ensure_ascii=False))


def install_global_exception_logger() -> None:
    """未捕捉例外やQtメッセージを構造化ログに流し、ターミナル調査を容易にする。"""

    if getattr(install_global_exception_logger, "_installed", False):
        return

    def _handle_exception(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        trace = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
        log_structured(
            logging.CRITICAL,
            "unhandled_exception",
            {
                "exception_type": exc_type.__name__,
                "message": str(exc_value),
                "traceback": trace,
            },
        )

    sys.excepthook = _handle_exception

    def _qt_message_handler(mode, context, message):
        level_map = {
            QtCore.QtDebugMsg: logging.DEBUG,
            QtCore.QtInfoMsg: logging.INFO,
            QtCore.QtWarningMsg: logging.WARNING,
            QtCore.QtCriticalMsg: logging.ERROR,
            QtCore.QtFatalMsg: logging.CRITICAL,
        }
        payload = {
            "category": getattr(context, "category", ""),
            "file": getattr(context, "file", ""),
            "line": getattr(context, "line", 0),
            "function": getattr(context, "function", ""),
            "message": message,
        }
        log_structured(level_map.get(mode, logging.INFO), "qt_message", payload)
        if mode == QtCore.QtFatalMsg:
            raise SystemExit(1)

    try:
        QtCore.qInstallMessageHandler(_qt_message_handler)
    except Exception:
        logging.getLogger(__name__).debug("Qt message handler installation skipped.", exc_info=True)

    install_global_exception_logger._installed = True


def log_startup_environment() -> None:
    """アプリ起動直後の実行環境を計測し、障害再現を容易にする。"""

    payload = {
        "python_version": platform.python_version(),
        "executable": sys.executable,
        "cwd": os.getcwd(),
        "script_dir": str(config.SCRIPT_DIR),
        "default_db_path": config.DEFAULT_DB_PATH,
        "settings_path": str(config.SCRIPT_DIR / "desktop_gui_settings.yaml"),
        "qt_version": QtCore.qVersion(),
        "hostname": config.HOSTNAME,
    }
    log_structured(logging.INFO, "startup_environment", payload)


def get_exception_trace() -> str:
    t, v, tb = sys.exc_info()
    trace = traceback.format_exception(t, v, tb)
    return "".join(trace)
