# color_log_formatter.py
#
# Copyright 2023 Geoffrey Coulaud
# Copyright 2023-2024 kramo
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Configures application-wide logging."""
from logging import Formatter, LogRecord, config
from os import environ

from showtime import shared


class ColorLogFormatter(Formatter):
    """Formatter that outputs logs in a colored format."""

    RESET = "\033[0m"
    DIM = "\033[2m"
    BOLD = "\033[1m"
    RED = "\033[31m"
    YELLOW = "\033[33m"

    def format(self, record: LogRecord) -> str:
        super_format = super().format(record)
        match record.levelname:
            case "CRITICAL":
                return self.BOLD + self.RED + super_format + self.RESET
            case "ERROR":
                return self.RED + super_format + self.RESET
            case "WARNING":
                return self.YELLOW + super_format + self.RESET
            case "DEBUG":
                return self.DIM + super_format + self.RESET
            case _other:
                return super_format


def configure_logging() -> None:
    """Configures application-wide logging."""
    log_level = environ.get(
        "LOGLEVEL", "DEBUG" if shared.PROFILE == "development" else "INFO"
    ).upper()

    config.dictConfig(
        {
            "version": 1,
            "formatters": {
                "console_formatter": {
                    "format": "%(levelname)s - %(message)s",
                    "class": "showtime.configure_logging.ColorLogFormatter",
                },
            },
            "handlers": {
                "console_handler": {
                    "class": "logging.StreamHandler",
                    "formatter": "console_formatter",
                    "level": log_level,
                },
            },
            "root": {
                "level": "NOTSET",
                "handlers": ["console_handler"],
            },
        }
    )
