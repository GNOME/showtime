# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2024-2025 kramo

from typing import Any

from gi.repository import (
    Gdk,
    Gst,
    GstPlay,  # type: ignore
    Gtk,
)

from showtime import system, utils


def gst_play_setup(
    picture: Gtk.Picture,
) -> tuple[Gdk.Paintable, GstPlay.Play, Gst.Element, Gst.Element]:
    """Set up `GstPlay`."""
    sink = paintable_sink = Gst.ElementFactory.make("gtk4paintablesink")
    if not paintable_sink:
        raise RuntimeError("Cannot make gtk4paintablesink")

    paintable = paintable_sink.props.paintable  # type: ignore
    picture.props.paintable = paintable

    # OpenGL doesn't work on macOS properly
    if paintable.props.gl_context and system != "Darwin":
        gl_sink = Gst.ElementFactory.make("glsinkbin")
        gl_sink.props.sink = paintable_sink  # type: ignore
        sink = gl_sink

    play = GstPlay.Play(
        video_renderer=GstPlay.PlayVideoOverlayVideoRenderer.new_with_sink(None, sink)
    )

    pipeline = play.props.pipeline

    def set_subtitle_font_desc(*_args: Any) -> None:
        pipeline.props.subtitle_font_desc = utils.get_subtitle_font_desc()

    if settings := Gtk.Settings.get_default():
        settings.connect("notify::gtk-xft-dpi", set_subtitle_font_desc)

    set_subtitle_font_desc()

    return paintable, play, pipeline, paintable_sink
