# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2024-2025 kramo

from typing import Any

from gi.repository import (
    Gdk,
    GObject,
    Gst,
    GstPbutils,
    GstPlay,  # pyright: ignore[reportAttributeAccessIssue]
    Gtk,
)

from showtime import system, utils


def gst_play_setup(
    picture: Gtk.Picture,
) -> tuple[Gdk.Paintable, GstPlay.Play, Gst.Element, Gst.Element]:
    """Set up `GstPlay`."""
    sink = paintable_sink = Gst.ElementFactory.make("gtk4paintablesink")
    if not paintable_sink:
        msg = "Cannot make gtk4paintablesink"
        raise RuntimeError(msg)

    paintable = paintable_sink.props.paintable  # pyright: ignore[reportAttributeAccessIssue]
    picture.props.paintable = paintable

    # OpenGL doesn't work on macOS properly
    if paintable.props.gl_context and system != "Darwin":
        gl_sink = Gst.ElementFactory.make("glsinkbin")
        gl_sink.props.sink = paintable_sink  # pyright: ignore[reportAttributeAccessIssue, reportOptionalMemberAccess]
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


class Messenger(GObject.Object):
    """A messenger between GStreamer and the app."""

    __gtype_name__ = "Messenger"

    state_changed = GObject.Signal(name="state-changed", arg_types=(object,))
    duration_changed = GObject.Signal(name="duration-changed", arg_types=(object,))
    position_updated = GObject.Signal(name="position-updated", arg_types=(object,))
    seek_done = GObject.Signal(name="seek-done")
    media_info_updated = GObject.Signal(name="media-info-updated", arg_types=(object,))
    volume_changed = GObject.Signal(name="volume-changed")
    end_of_stream = GObject.Signal(name="end-of-stream")
    warning = GObject.Signal(name="warning", arg_types=(object,))
    error = GObject.Signal(name="error", arg_types=(object,))
    missing_plugin = GObject.Signal(name="missing-plugin", arg_types=(object,))

    def __init__(
        self,
        play: GstPlay.Play,
        pipeline: Gst.Element,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)

        if bus := play.get_message_bus():
            bus.add_signal_watch()
            bus.connect("message", self._on_play_bus_message)

        if bus := pipeline.get_bus():
            bus.add_signal_watch()
            bus.connect("message", self._on_pipeline_bus_message)

    def _on_play_bus_message(self, _bus: Gst.Bus, msg: GstPlay.PlayMessage) -> None:
        match GstPlay.PlayMessage.parse_type(msg):
            case GstPlay.PlayMessage.STATE_CHANGED:
                self.emit(
                    "state-changed",
                    GstPlay.PlayMessage.parse_state_changed(msg),
                )

            case GstPlay.PlayMessage.DURATION_CHANGED:
                self.emit(
                    "duration-changed",
                    GstPlay.PlayMessage.parse_duration_changed(msg),
                )

            case GstPlay.PlayMessage.POSITION_UPDATED:
                self.emit(
                    "position-updated",
                    GstPlay.PlayMessage.parse_position_updated(msg),
                )

            case GstPlay.PlayMessage.SEEK_DONE:
                self.emit("seek-done")

            case GstPlay.PlayMessage.MEDIA_INFO_UPDATED:
                self.emit(
                    "media-info-updated",
                    GstPlay.PlayMessage.parse_media_info_updated(msg),
                )

            case GstPlay.PlayMessage.VOLUME_CHANGED:
                self.emit("volume-changed")

            case GstPlay.PlayMessage.END_OF_STREAM:
                self.emit("end-of-stream")

            case GstPlay.PlayMessage.WARNING:
                self.emit("warning", GstPlay.PlayMessage.parse_warning(msg))

            case GstPlay.PlayMessage.ERROR:
                error, _details = GstPlay.PlayMessage.parse_error(msg)
                self.emit("error", error)

    def _on_pipeline_bus_message(self, _bus: Gst.Bus, msg: Gst.Message) -> None:
        if GstPbutils.is_missing_plugin_message(msg):
            self.emit("missing-plugin", msg)
