# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2023 Geoffrey Coulaud
# SPDX-FileCopyrightText: Copyright 2024-2025 kramo

from logging import Formatter, LogRecord


class ColorLogFormatter(Formatter):
    """Formatter that outputs logs in a colored format."""

    RESET = "\033[0m"
    DIM = "\033[2m"
    BOLD = "\033[1m"
    RED = "\033[31m"
    YELLOW = "\033[33m"

    def format(self, record: LogRecord) -> str:
        """Format log messages."""
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
