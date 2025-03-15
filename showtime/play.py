# play.py

# Copyright 2025 kramo

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

from typing import Any

from gi.repository import (
    Gdk,
    Gst,
    GstPlay,  # type: ignore
    Gtk,
)

from showtime import shared, utils


def gst_play_setup(
    picture: Gtk.Picture,
) -> tuple[Gdk.Paintable, GstPlay.Play, Gst.Element]:
    """Set up `GstPlay`."""
    sink = Gst.ElementFactory.make("gtk4paintablesink")
    paintable = sink.props.paintable  # type: ignore

    picture.set_paintable(paintable)

    # OpenGL doesn't work on macOS properly
    if paintable.props.gl_context and shared.system != "Darwin":
        gl_sink = Gst.ElementFactory.make("glsinkbin")
        gl_sink.props.sink = sink  # type: ignore
        sink = gl_sink

    play = GstPlay.Play(
        video_renderer=GstPlay.PlayVideoOverlayVideoRenderer.new_with_sink(None, sink)
    )

    pipeline = play.get_pipeline()

    def set_subtitle_font_desc(*_args: Any) -> None:
        pipeline.props.subtitle_font_desc = utils.get_subtitle_font_desc()

    if settings := Gtk.Settings.get_default():
        settings.connect("notify::gtk-xft-dpi", set_subtitle_font_desc)

    set_subtitle_font_desc()

    return paintable, play, pipeline
