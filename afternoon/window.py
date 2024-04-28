# window.py
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
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The main application window."""
import datetime
import logging
import pickle
from hashlib import sha256
from math import floor
from os import sep
from pathlib import Path
from typing import Any, Optional

from gi.repository import Adw, Clapper, ClapperGtk, Gio, GLib, Gtk

from afternoon import shared
from afternoon.utils import screenshot


@Gtk.Template(resource_path=f"{shared.PREFIX}/gtk/window.ui")
class AfternoonWindow(Adw.ApplicationWindow):
    """The main application window."""

    __gtype_name__ = "AfternoonWindow"

    breakpoint: Adw.Breakpoint = Gtk.Template.Child()
    toast_overlay: Adw.ToastOverlay = Gtk.Template.Child()
    stack: Gtk.Stack = Gtk.Template.Child()

    placeholder_page: Adw.ToolbarView = Gtk.Template.Child()
    placeholder_stack: Gtk.Stack = Gtk.Template.Child()
    open_status_page: Adw.StatusPage = Gtk.Template.Child()
    error_status_page: Adw.StatusPage = Gtk.Template.Child()
    button_open: Gtk.Button = Gtk.Template.Child()

    video_page: Gtk.WindowHandle = Gtk.Template.Child()
    video: ClapperGtk.Video = Gtk.Template.Child()
    button_fullscreen: Gtk.Button = Gtk.Template.Child()

    toolbar_box: Gtk.Box = Gtk.Template.Child()
    toolbar_center_box: Gtk.CenterBox = Gtk.Template.Child()
    play_controls_box: Gtk.Box = Gtk.Template.Child()
    backwards_button: Gtk.Button = Gtk.Template.Child()
    forwards_button: Gtk.Button = Gtk.Template.Child()
    restore_revealer: Gtk.Revealer = Gtk.Template.Child()

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)

        if shared.PROFILE == "development":
            self.add_css_class("devel")

        self.player = self.video.get_player()
        self.player.add_feature(
            Clapper.Mpris.new(
                "org.mpris.MediaPlayer2.Afternoon", "Afternoon", shared.APP_ID
            )
        )
        if settings := Gtk.Settings.get_default():
            self.player.set_subtitle_font_desc(settings.props.gtk_font_name)

        self.player.connect("error", self.__on_player_error)
        self.player.connect("missing-plugin", self.__on_missing_plugin)
        self.player.connect("notify::state", self.__on_state_changed)

        self.queue = self.player.get_queue()

        self.breakpoint.connect(
            "apply", lambda *_: self.toolbar_box.remove_css_class("sharp-corners")
        )
        self.breakpoint.connect(
            "unapply", lambda *_: self.toolbar_box.add_css_class("sharp-corners")
        )

        self.toolbar_center_box.set_center_widget(
            Adw.Clamp(
                child=ClapperGtk.TitleLabel(margin_start=12, margin_end=3),
                tightening_threshold=150,
                maximum_size=2147483647,  # Max gint size
            )
        )
        extra_menu_button = ClapperGtk.ExtraMenuButton(can_open_subtitles=True)
        extra_menu_button.get_first_child().set_icon_name("settings-symbolic")
        self.toolbar_center_box.set_end_widget(extra_menu_button)
        self.play_controls_box.insert_child_after(
            ClapperGtk.TogglePlayButton(), self.backwards_button
        )
        self.toolbar_box.append(ClapperGtk.SeekBar())
        extra_menu_button.connect(
            "open-subtitles", lambda _obj, item: self.choose_subtitles(item)
        )

        self.backwards_button.connect(
            "clicked",
            lambda *_: self.player.seek(max(0, self.player.get_position() - 10)),
        )
        self.forwards_button.connect(
            "clicked",
            lambda *_: self.player.seek(self.player.get_position() + 10),
        )

        self.stack.connect("notify::visible-child", self.__on_stack_child_changed)
        self.__on_stack_child_changed()

        (esc := Gtk.ShortcutController()).add_shortcut(
            Gtk.Shortcut.new(
                Gtk.ShortcutTrigger.parse_string("Escape"),
                Gtk.CallbackAction.new(lambda *_: self.unfullscreen()),
            )
        )
        self.add_controller(esc)

        self.connect("notify::fullscreened", self.__on_fullscreen)

    def __on_fullscreen(self, *_args: Any) -> None:
        self.button_fullscreen.set_icon_name(
            "view-restore-symbolic"
            if self.is_fullscreen()
            else "view-fullscreen-symbolic"
        )

    def __on_stack_child_changed(self, *_args: Any) -> None:
        self.get_application().lookup_action("screenshot").set_enabled(
            self.stack.get_visible_child() == self.video_page
        )

    @Gtk.Template.Callback()
    def toggle_fullscreen(self, *_args: Any) -> None:
        """Fullscreens `self` if not already in fullscreen, otherwise unfullscreens."""
        if self.is_fullscreen():
            self.unfullscreen()
            return

        self.fullscreen()

    @Gtk.Template.Callback()
    def choose_video(self, *_args: Any) -> None:
        """Opens a file dialog to pick a video to play."""
        dialog = Gtk.FileDialog()

        file_filter = Gtk.FileFilter()
        file_filter.add_mime_type("video/*")
        file_filter.set_name(_("Video"))

        filters = Gio.ListStore()
        filters.append(file_filter)
        dialog.set_filters(filters)
        dialog.set_default_filter(file_filter)

        dialog.open(self, callback=self.__choose_video_cb)

    def __choose_video_cb(self, dialog: Gtk.FileDialog, res: Gio.AsyncResult) -> None:
        try:
            if not (gfile := dialog.open_finish(res)):
                return

        except GLib.Error:
            return

        self.get_application().save_play_position(self)
        self.play_video(gfile)

    def choose_subtitles(self, item: Clapper.MediaItem) -> None:
        """Opens a file dialog to pick a subtitle."""
        dialog = Gtk.FileDialog()

        file_filter = Gtk.FileFilter()
        file_filter.add_mime_type("application/x-subrip")
        file_filter.add_mime_type("text/x-ssa")
        file_filter.set_name(_("Subtitles"))

        filters = Gio.ListStore()
        filters.append(file_filter)
        dialog.set_filters(filters)
        dialog.set_default_filter(file_filter)

        dialog.open(self, callback=self.__choose_subtitles_cb, user_data=item)

    def __choose_subtitles_cb(
        self, dialog: Gtk.FileDialog, res: Gio.AsyncResult, item: Clapper.MediaItem
    ) -> None:
        try:
            if not (gfile := dialog.open_finish(res)):
                return

        except GLib.Error:
            return

        item.set_suburi(gfile.get_uri())

    def __on_state_changed(self, player: Clapper.Player, *_args: Any) -> None:
        if (state := player.get_state()) == Clapper.PlayerState.PLAYING:
            self.restore_revealer.set_reveal_child(False)
            return

        if state != Clapper.PlayerState.PAUSED:
            return

        if not (item := self.queue.get_current_item()):
            return

        # The precision of the two values can differ so floor them

        # While a video is loading
        if (pos := floor(player.get_position())) == 0:
            return

        # Seek to the beginning when a video has ended
        if pos != floor(item.get_duration()):
            return

        player.seek(0)

    def __on_player_error(
        self, _obj: Any, error: GLib.Error, debug_info: Optional[str] = None
    ) -> None:
        self.error_status_page.set_description(error.message.rstrip("."))
        self.placeholder_stack.set_visible_child(self.error_status_page)
        self.stack.set_visible_child(self.placeholder_page)

        if not debug_info:
            return

        logging.error("Playback error: %s", debug_info)

    def __on_missing_plugin(self, _obj: Any, name: str, _installer_detail: str) -> None:
        self.error_status_page.set_description(
            f"A “{name}” plugin is required to play this video"
        )
        self.placeholder_stack.set_visible_child(self.error_status_page)
        self.stack.set_visible_child(self.placeholder_page)

    def __get_previous_play_position(self) -> Optional[float]:
        if not (item := self.queue.get_current_item()):
            return None

        try:
            hist_file = (shared.cache_path / "playback_history").open("rb")
        except FileNotFoundError:
            return None

        try:
            hist = pickle.load(hist_file)
        except EOFError:
            return None

        hist_file.close()

        return hist.get(sha256(item.get_uri().encode("utf-8")).hexdigest())

    def __resize_window(self, stream: Clapper.VideoStream) -> None:
        try:
            if (ratio := stream.get_width() / stream.get_height()) == 0:
                return
        except ZeroDivisionError:
            return

        # Make the window 3/5ths of the display height
        height = (
            self.props.display.get_monitor_at_surface(self.get_surface())
            .get_geometry()
            .height
            * 0.6
        )
        width = height * ratio

        self.set_default_size(width, height)

    def __stream_cb(self, player: Clapper.Player, *_args: Any) -> None:
        if player.get_state() != Clapper.PlayerState.PAUSED:
            return

        if video_stream := self.player.get_video_streams().get_current_stream():
            self.__resize_window(video_stream)

        player.disconnect_by_func(self.__stream_cb)

        if not (pos := self.__get_previous_play_position()):
            self.player.play()
            return

        # Don't restore the previous play position if it is in the first minute
        if pos < 60:
            self.player.play()
            return

        self.player.seek(pos)
        self.restore_revealer.set_reveal_child(True)

    def play_video(self, gfile: Gio.File) -> None:
        """Starts playing the given `GFile`."""
        self.stack.set_visible_child(self.video_page)
        self.restore_revealer.set_reveal_child(False)

        # Can't seek while buffering
        self.player.connect("notify::state", self.__stream_cb)

        self.queue.add_item(Clapper.MediaItem.new_from_file(gfile))
        if self.queue.get_n_items() > 1:
            self.queue.select_next_item()
            self.queue.remove_index(0)

        self.player.pause()

    @Gtk.Template.Callback()
    def _restore(self, *_args: Any) -> None:
        self.player.play()

    @Gtk.Template.Callback()
    def _play_again(self, *_args: Any) -> None:
        self.player.seek(0)
        self.player.play()

    def save_screenshot(self) -> None:
        """
        Saves a screenshot of the current frame of the video being played in PNG format.

        It tries saving it to `xdg-pictures/Screenshot` and falls back to `~`.
        """

        if not (item := self.queue.get_current_item()):
            return

        if not (
            paintable := self.video.get_first_child().get_first_child().get_paintable()
        ):
            return

        if not (stream := self.player.get_video_streams().get_current_stream()):
            return

        if not (
            texture := screenshot(
                paintable,
                stream.get_width(),
                stream.get_height(),
                self,
            )
        ):
            return

        if pictures := GLib.get_user_special_dir(GLib.USER_DIRECTORY_PICTURES):
            path = GLib.build_pathv(sep, (pictures, "Screenshots"))
        else:
            path = GLib.get_home_dir()

        if not (title := item.get_title()):
            title = _("Unknown Title")

        time = (
            (
                datetime.datetime.min
                + datetime.timedelta(seconds=self.player.get_position())
            )
            .time()
            .strftime("%H:%M:%S")
        )

        path = GLib.build_pathv(
            sep,
            (path, f"{Path(title).stem} {time}.png"),
        )

        texture.save_to_png(path)

        toast = Adw.Toast.new(_("Screenshot captured"))
        toast.set_priority(Adw.ToastPriority.HIGH)
        toast.set_button_label(_("Show in Files"))
        toast.connect(
            "button-clicked",
            lambda *_: Gtk.FileLauncher.new(
                Gio.File.new_for_path(path)
            ).open_containing_folder(),
        )

        self.toast_overlay.add_toast(toast)
