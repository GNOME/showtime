# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2024-2025 kramo

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from gi.repository import (
    Gdk,
    Gio,
    Graphene,
    GstPlay,  # pyright: ignore[reportAttributeAccessIssue]
    Gtk,
)

from showtime import logger

SECONDS_ONLY = 2


def screenshot(paintable: Gdk.Paintable, native: Gtk.Native) -> Gdk.Texture | None:
    """Take a screenshot of the current image of a `GdkPaintable`."""
    # Copied from Workbench
    # https://github.com/workbenchdev/Workbench/blob/1ebbe1e3915aabfd172c166c88ca23ad08861d15/src/Previewer/previewer.vala#L36

    paintable = paintable.get_current_image()
    width = paintable.get_intrinsic_width()
    height = paintable.get_intrinsic_height()

    snapshot = Gtk.Snapshot()
    paintable.snapshot(snapshot, width, height)

    if not (node := snapshot.to_node()):
        logger.warning(
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


def nanoseconds_to_timestamp(ns: int, *, hours: bool = False) -> str:
    """Convert `ns` to a human readable time stamp.

    In the format 1:23 or 1:23:45 depending on length.

    If `hours` is set to True, always return a string in the format 01:23:45.
    """
    formatted = (
        (datetime.min.replace(tzinfo=UTC) + timedelta(microseconds=int(ns / 1000)))
        .time()
        .strftime("%H:%M:%S")
    )

    return (
        formatted
        if hours
        else formatted.lstrip("0:") or "0"
        if len(stripped := formatted.lstrip("0:") or "0") > SECONDS_ONLY
        else f"0:{stripped:0>2}"
    )


def get_title(media_info: GstPlay.PlayMediaInfo | None) -> str | None:
    """Get the title of the video from a `GstPlayMediaInfo`."""
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


def lookup_action(action_map: Any, name: str) -> Gio.SimpleAction | None:
    """Look up an action in `action_map` with type checking."""
    if isinstance(action_map, Gio.ActionMap) and isinstance(
        action := action_map.lookup_action(name), Gio.SimpleAction
    ):
        return action

    return None


def get_subtitle_font_desc() -> str | None:
    """Get a font description scaled to the user's preferences.

    Ideal for rendering subtitles.
    """
    if not (settings := Gtk.Settings.get_default()):
        return None

    font_name = settings.props.gtk_font_name

    try:
        size_str = font_name.rsplit(" ", 1)[1]
        size = float(size_str)
    except (ValueError, IndexError):
        return font_name
    else:
        # TODO: Can I always assume that 72 is the default unscaled DPI? Probably not…
        new_size = size * ((settings.props.gtk_xft_dpi / 1024) / 72)
        return font_name[: len(font_name) - len(size_str)] + str(round(new_size))
