# utils.py

# Copyright 2024 kramo

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
import logging
from pathlib import Path
from typing import Any, Optional

import chardet
import srt
from gi.repository import Gdk, Gio, GLib, Graphene, Gtk


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
            "Could not get node snapshot, width: %s, height: %s", width, height
        )
        return None

    rect = Graphene.Rect()
    rect.origin = Graphene.Point.zero()
    size = Graphene.Size()
    size.width = width
    size.height = height
    rect.size = size

    renderer = native.get_renderer()
    return renderer.render_texture(node, rect)


def update_subtitles(
    label: Gtk.Label, gfile: Gio.File, stream: Gtk.MediaStream
) -> None:
    if not stream:
        return

    if not (path := gfile.get_path()):
        return

    path = Path(path)

    subtitles = list(
        srt.sort_and_reindex(
            srt.parse(
                path.read_text(encoding=chardet.detect(path.read_bytes())["encoding"])
            )
        )
    )

    original_subs = subtitles.copy()

    timestamp = stream.get_timestamp() / 1000

    for sub in subtitles:
        ms = sub.start.total_seconds() * 1000

        if ms > timestamp:
            timeout = ms - timestamp

            if stream.get_playing():
                subtitleUpdater(label, subtitles, original_subs, stream, timeout)
            else:

                def play_cb(*_args: Any) -> None:
                    subtitleUpdater(label, subtitles, original_subs, stream, timeout)
                    stream.disconnect_by_func(play_cb)

                stream.connect("notify::playing", play_cb)

            return

        subtitles.pop(0)


class subtitleUpdater:
    def __init__(
        self,
        label: Gtk.Label,
        subtitles: list[srt.Subtitle],
        original_subs: list[srt.Subtitle],
        stream: Gtk.MediaStream,
        timeout: float,
    ) -> None:
        self.label = label
        self.subtitles = subtitles
        self.original_subs = original_subs
        self.stream = stream

        self.cycle_i = 0

        GLib.timeout_add(timeout, self.__update_subtitles, self.cycle_i)

        self.stream.connect("notify::playing", self.__on_play_changed)
        self.stream.connect("notify::seeking", self.__on_seek_changed)
        self.stream.connect("notify::ended", self.__on_ended_changed)

        if updater := label.get_root().subtitle_updater:
            updater.stop()

        label.get_root().subtitle_updater = self

    def __on_play_changed(self, *_args: Any) -> None:
        if not self.stream.get_playing():
            return

        timestamp = self.stream.get_timestamp() / 1000
        ms = self.subtitles[0].start.total_seconds() * 1000
        timeout = ms - timestamp

        self.cycle_i += 1

        GLib.timeout_add(timeout, self.__update_subtitles, self.cycle_i)

    def __position_changed(self) -> None:
        self.cycle_i += 1

        timestamp = self.stream.get_timestamp() / 1000

        self.subtitles = self.original_subs.copy()

        prev = None

        for sub in self.subtitles:
            ms = sub.start.total_seconds() * 1000

            if ms > timestamp:
                timeout = ms - timestamp

                GLib.timeout_add(timeout, self.__update_subtitles, self.cycle_i)

                if not prev:
                    return

                self.label.set_label(srt.make_legal_content(prev.content))
                self.label.set_visible(True)
                return

            prev = self.subtitles.pop(0)

    def stop(self) -> None:
        """Stop updating the subtitles."""
        self.stream.disconnect_by_func(self.__on_play_changed)
        self.stream.disconnect_by_func(self.__on_seek_changed)
        self.stream.disconnect_by_func(self.__on_ended_changed)
        self.cycle_i += 1

    def __on_seek_changed(self, *_args: Any) -> None:
        if self.stream.is_seeking():
            self.label.set_visible(False)
            return

        # Add a timeout because doing it right away seems to lead to inconsistent outcomes
        GLib.timeout_add(10, self.__position_changed)

    def __on_ended_changed(self, *_args: Any) -> None:
        if self.stream.get_ended():
            self.label.set_visible(False)
            return

        self.__position_changed()

    def __hide_subtitle(self, cycle_i: int, content: str) -> None:
        if cycle_i != self.cycle_i:
            return

        if not self.stream.get_playing():
            return

        if self.stream.is_seeking():
            return

        if content != self.label.get_label():
            return

        self.label.set_visible(False)

    def __update_subtitles(self, cycle_i: int) -> None:
        if cycle_i != self.cycle_i:
            return

        if not self.stream.get_playing():
            return

        if self.stream.is_seeking():
            return

        sub = self.subtitles.pop(0)

        self.label.set_visible(True)
        self.label.set_label(srt.make_legal_content(sub.content))

        ms = (
            self.subtitles[0].start.total_seconds() * 1000
            - sub.start.total_seconds() * 1000
        )

        hide_ms = sub.end.total_seconds() * 1000 - sub.start.total_seconds() * 1000

        GLib.timeout_add(ms, self.__update_subtitles, cycle_i)
        GLib.timeout_add(hide_ms, self.__hide_subtitle, cycle_i, sub.content)
