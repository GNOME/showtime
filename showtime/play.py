# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2024-2026 kramo

from typing import Any, NamedTuple

from gi.repository import (
    Gdk,
    GObject,
    Gst,
    GstPlay,  # pyright: ignore[reportAttributeAccessIssue]
    Gtk,
)

from showtime import logger, system, utils


class MissingPlugin(NamedTuple):
    """A missing plugin reported by GStreamer."""

    description: str
    detail: str


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

    def set_subtitle_font_desc(*_args) -> None:
        pipeline.props.subtitle_font_desc = utils.get_subtitle_font_desc()

    if settings := Gtk.Settings.get_default():
        settings.connect("notify::gtk-xft-dpi", set_subtitle_font_desc)

    set_subtitle_font_desc()

    return paintable, play, pipeline, paintable_sink


def _should_missing_plugin_be_ignored(missing_plugin: MissingPlugin) -> bool:
    """Check if a missing plugin should be ignored.

    qtdemux generates {audio,video,text,meta}/x-gst-fourcc-<fourcc>
    caps as a fallback for any fourcc code it doesn't recognise in a
    QuickTime/MP4 file. If a decoder existed, qtdemux would already
    know the fourcc and emit proper caps for it. These are therefore
    not actionable from the missing-plugin UI, so they're ignored.
    """
    return "x-gst-fourcc" in missing_plugin.detail


def _parse_missing_plugins(msg: GstPlay.PlayMessage) -> tuple[MissingPlugin, ...]:
    result: tuple[bool, list[str], list[str]] = (
        GstPlay.play_message_parse_error_missing_plugin(msg)
        if GstPlay.PlayMessage.parse_type(msg) == GstPlay.PlayMessage.ERROR
        else GstPlay.play_message_parse_warning_missing_plugin(msg)
    )
    found, descriptions, details = result
    if not found:
        return ()

    missing_plugins: list[MissingPlugin] = [
        MissingPlugin(description, detail)
        for description, detail in zip(descriptions, details, strict=True)
    ]

    return tuple(
        missing_plugin
        for missing_plugin in missing_plugins
        if not _should_missing_plugin_be_ignored(missing_plugin)
    )


class Messenger(GObject.Object):
    """A messenger between GStreamer and the app."""

    __gtype_name__ = "Messenger"

    _pending_missing_plugins: tuple[MissingPlugin, ...] = ()

    state_changed = GObject.Signal(name="state-changed", arg_types=(object,))
    duration_changed = GObject.Signal(name="duration-changed", arg_types=(object,))
    position_updated = GObject.Signal(name="position-updated", arg_types=(object,))
    seek_done = GObject.Signal(name="seek-done")
    media_info_updated = GObject.Signal(name="media-info-updated", arg_types=(object,))
    volume_changed = GObject.Signal(name="volume-changed")
    end_of_stream = GObject.Signal(name="end-of-stream")
    warning = GObject.Signal(name="warning", arg_types=(object,))
    error = GObject.Signal(name="error", arg_types=(object,))
    missing_plugins = GObject.Signal(name="missing-plugins", arg_types=(object, bool))

    def __init__(
        self,
        play: GstPlay.Play,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)

        if bus := play.get_message_bus():
            bus.add_signal_watch()
            bus.connect("message", self._on_play_bus_message)

    def _on_play_bus_message(self, _bus: Gst.Bus, msg: GstPlay.PlayMessage) -> None:
        match GstPlay.PlayMessage.parse_type(msg):
            case GstPlay.PlayMessage.STATE_CHANGED:
                state = GstPlay.PlayMessage.parse_state_changed(msg)
                self._resolve_pending_missing_plugins(state)
                self.emit("state-changed", state)

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
                if plugins := _parse_missing_plugins(msg):
                    self._pending_missing_plugins = plugins
                self.emit("warning", GstPlay.PlayMessage.parse_warning(msg))

            case GstPlay.PlayMessage.ERROR:
                error, _details = GstPlay.PlayMessage.parse_error(msg)
                if plugins := _parse_missing_plugins(msg):
                    logger.error(error.message)
                    self.emit("missing-plugins", plugins, False)
                else:
                    self.emit("error", error)

    def _resolve_pending_missing_plugins(self, state: GstPlay.PlayState) -> None:
        match state:
            case GstPlay.PlayState.STOPPED:
                self._pending_missing_plugins = ()
            case GstPlay.PlayState.PAUSED | GstPlay.PlayState.PLAYING:
                if self._pending_missing_plugins:
                    self.emit("missing-plugins", self._pending_missing_plugins, True)
                    self._pending_missing_plugins = ()
