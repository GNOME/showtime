# shared.pyi
#
# Copyright 2024 kramo
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

from typing import Optional
from pathlib import Path

from gi.repository import Gio

from showtime.main import ShowtimeApplication

APP_ID: str
VERSION: str
PREFIX: str
PROFILE: str

system: str

app: Optional[ShowtimeApplication]

schema: Gio.Settings
state_schema: Gio.Settings

cache_path: Path
log_files: list[Path]

end_timestamp_type: int

DEFAULT_OCCUPY_SCREEN: float
SMALL_SCREEN_AREA: int
SMALL_OCCUPY_SCREEN: float

MAX_UINT16: int
