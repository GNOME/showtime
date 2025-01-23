# messenger.py
#
# Copyright 2025 kramo
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
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
#
# SPDX-License-Identifier: GPL-3.0-or-later

from typing import Any
from gi.repository import (
    GObject,
    Gst,
    GstPbutils,
    GstPlay,  # type: ignore
    GLib,
)


class ShowtimeMessenger(GObject.Object):
    __gtype_name__ = "ShowtimeMessenger"

    @GObject.Signal(name="state-changed", arg_types=(object,))
    def state_changed(self, state: GstPlay.PlayState) -> None: ...

    @GObject.Signal(name="duration-changed", arg_types=(object,))
    def duration_changed(self, dur: int) -> None: ...

    @GObject.Signal(name="position-updated", arg_types=(object,))
    def position_updated(self, pos: int) -> None: ...

    @GObject.Signal(name="seek-done")
    def seek_done(self) -> None: ...

    @GObject.Signal(name="media-info-updated", arg_types=(object,))
    def media_info_updated(self, media_info: GstPlay.PlayMediaInfo) -> None: ...

    @GObject.Signal(name="volume-changed")
    def volume_changed(self) -> None: ...

    @GObject.Signal(name="end-of-stream")
    def end_of_stream(self) -> None: ...

    @GObject.Signal(name="warning", arg_types=(object,))
    def warning(self, warning: GLib.Error) -> None: ...

    @GObject.Signal(name="error", arg_types=(object,))
    def error(self, error: GLib.Error) -> None: ...

    @GObject.Signal(name="missing-plugin", arg_types=(object,))
    def missing_plugin(self, msg: Gst.Message) -> None: ...

    def __init__(
        self,
        play: GstPlay.Play,
        pipeline: Gst.Element,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)

        if bus := play.get_message_bus():
            bus.add_signal_watch()
            bus.connect("message", self.__on_play_bus_message)

        if bus := pipeline.get_bus():
            bus.add_signal_watch()
            bus.connect("message", self.__on_pipeline_bus_message)

    def __on_play_bus_message(self, _bus: Gst.Bus, msg: GstPlay.PlayMessage) -> None:
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

    def __on_pipeline_bus_message(self, _bus: Gst.Bus, msg: Gst.Message) -> None:
        if GstPbutils.is_missing_plugin_message(msg):
            self.emit("missing-plugin", msg)
