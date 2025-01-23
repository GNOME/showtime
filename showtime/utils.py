# utils.py

# Copyright 2024-2025 kramo

# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

# SPDX-License-Identifier: GPL-3.0-or-later

"""Utilities used across the app."""

import datetime
import logging
from pathlib import Path
from typing import Optional
from urllib.parse import unquote, urlparse

from gi.repository import (
    Gdk,
    Graphene,
    GstPlay,  # type: ignore
    Gtk,
    Gio,
)


def screenshot(paintable: Gdk.Paintable, native: Gtk.Native) -> Optional[Gdk.Texture]:
    """Takes a screenshot of the current image of a `GdkPaintable`."""

    # Copied from Workbench
    # https://github.com/workbenchdev/Workbench/blob/1ebbe1e3915aabfd172c166c88ca23ad08861d15/src/Previewer/previewer.vala#L36

    paintable = paintable.get_current_image()
    width = paintable.get_intrinsic_width()
    height = paintable.get_intrinsic_height()

    snapshot = Gtk.Snapshot()
    paintable.snapshot(snapshot, width, height)

    if not (node := snapshot.to_node()):
        logging.warning(
            "Could not get node snapshot, width: %s, height: %s.", width, height
        )
        return None

    rect = Graphene.Rect()
    rect.origin = Graphene.Point.zero()
    size = Graphene.Size()
    size.width = width
    size.height = height
    rect.size = size

    return (
        renderer.render_texture(node, rect)
        if (renderer := native.get_renderer())
        else None
    )


def nanoseconds_to_timestamp(nanoseconds: int, format: Optional[bool] = True) -> str:
    """
    Converts `nanoseconds` to a human readable time stamp
    in the format 1∶23 or 1∶23∶45 depending on the length.

    If `format` is set to False, always returns a string in the format 01∶23∶45.
    """

    str = (
        (
            datetime.datetime.min
            + datetime.timedelta(microseconds=int(nanoseconds / 1000))
        )
        .time()
        .strftime("%H:%M:%S")
    )

    return (
        (
            stripped
            if len(stripped := str.lstrip("0:") or "0") > 2
            else f"0:{stripped.zfill(2)}"
        )
        if format
        else str
    )


def get_title(media_info: Optional[GstPlay.PlayMediaInfo]) -> Optional[str]:
    """Gets the title of the video from a `GstPlayMediaInfo`."""
    return (
        (
            title
            if (title := media_info.get_title())
            and title
            not in (
                "Video",
                "Audio",
            )
            else Path(unquote(urlparse(media_info.get_uri()).path)).stem
        )
        if media_info
        else None
    )


def lookup_action(
    app: Optional[Gio.Application], name: str
) -> Optional[Gio.SimpleAction]:
    if app and isinstance(action := app.lookup_action(name), Gio.SimpleAction):
        return action
