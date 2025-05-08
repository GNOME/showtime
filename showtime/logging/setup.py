# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2023 Geoffrey Coulaud
# SPDX-FileCopyrightText: Copyright 2024-2025 kramo

import logging
import logging.config as logging_dot_config
import os
import platform
import subprocess
import sys

from gi.repository import Gst

import showtime
from showtime import APP_ID, PROFILE, VERSION


def setup_logging() -> None:
    """Intitate the app's logging."""
    is_dev = PROFILE == "development"
    profile_app_log_level = "DEBUG" if is_dev else "INFO"
    profile_lib_log_level = "INFO" if is_dev else "WARNING"
    app_log_level = os.environ.get("LOGLEVEL", profile_app_log_level).upper()
    lib_log_level = os.environ.get("LIBLOGLEVEL", profile_lib_log_level).upper()

    log_filename = showtime.cache_path / "logs" / "showtime.log"

    config = {
        "version": 1,
        "formatters": {
            "file_formatter": {
                "format": "%(asctime)s - %(levelname)s: %(message)s",
                "datefmt": "%M:%S",
            },
            "console_formatter": {
                "format": "%(name)s %(levelname)s - %(message)s",
                "class": "showtime.logging.color_log_formatter.ColorLogFormatter",
            },
        },
        "handlers": {
            "file_handler": {
                "class": "showtime.logging.session_file_handler.SessionFileHandler",
                "formatter": "file_formatter",
                "level": "DEBUG",
                "filename": log_filename,
                "backup_count": 2,
            },
            "app_console_handler": {
                "class": "logging.StreamHandler",
                "formatter": "console_formatter",
                "level": app_log_level,
            },
            "lib_console_handler": {
                "class": "logging.StreamHandler",
                "formatter": "console_formatter",
                "level": lib_log_level,
            },
        },
        "root": {
            "level": "NOTSET",
            "handlers": ["app_console_handler", "file_handler"],
        },
    }
    logging_dot_config.dictConfig(config)


def log_system_info() -> None:
    """Log system debug information."""
    logging.debug("Starting %s v%s (%s)", APP_ID, VERSION, PROFILE)
    logging.debug("Python version: %s", sys.version)
    logging.debug("GStreamer version: %s", ".".join(str(v) for v in Gst.version()))
    if os.getenv("FLATPAK_ID") == APP_ID:
        process = subprocess.run(
            ("flatpak-spawn", "--host", "flatpak", "--version"),
            capture_output=True,
            encoding="utf-8",
            check=False,
        )
        logging.debug("Flatpak version: %s", process.stdout.rstrip())
    logging.debug("Platform: %s", platform.platform())
    if os.name == "posix":
        for key, value in platform.uname()._asdict().items():
            logging.debug("\t%s: %s", key.title(), value)
    logging.debug("─" * 37)
