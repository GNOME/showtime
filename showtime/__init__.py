# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2023-2025 kramo

"""The Showtime video player."""

import gettext
import logging
import platform
import signal
from logging.handlers import RotatingFileHandler
from pathlib import Path

import _showtime
from gi.repository import Gio, GLib

APP_ID = _showtime.APP_ID
BIN_NAME = _showtime.BIN_NAME
LOCALE_DIR= _showtime.LOCALE_DIR
PREFIX = _showtime.PREFIX
PROFILE = _showtime.PROFILE
VERSION = _showtime.VERSION

system = platform.system()

app = None
logger = logging.getLogger("showtime")

schema = Gio.Settings.new(APP_ID)
state_settings = Gio.Settings.new(APP_ID + ".State")

(state_path := Path(GLib.get_user_state_dir(), "showtime")).mkdir(exist_ok=True)
log_file = state_path / "showtime.log"

end_timestamp_type = state_settings.get_enum("end-timestamp-type")


def main(argv: tuple[bytes, ...]) -> int:
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    if system == "Linux":
        gettext.install(BIN_NAME, LOCALE_DIR)
    else:
        gettext.install(BIN_NAME)

    from showtime.application import Application

    global app

    """Run the application."""
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(levelname)s: %(name)s:%(lineno)d %(message)s",
        handlers=(
            (
                logging.StreamHandler(),
                RotatingFileHandler(log_file, maxBytes=1_000_000),
            )
        ),
    )

    return Application().run(argv)
