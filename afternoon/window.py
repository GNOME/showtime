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

import datetime
import logging
from os import sep
from pathlib import Path
from typing import Any

from gi.repository import Adw, Gdk, Gio, GLib, GObject, Graphene, Gtk

from afternoon import shared


@Gtk.Template(resource_path=f"{shared.PREFIX}/gtk/window.ui")
class AfternoonWindow(Adw.ApplicationWindow):
    __gtype_name__ = "AfternoonWindow"

    toast_overlay: Adw.ToastOverlay = Gtk.Template.Child()
    stack: Gtk.Stack = Gtk.Template.Child()

    placeholder_page: Adw.ToolbarView = Gtk.Template.Child()
    placeholder_stack: Adw.ToolbarView = Gtk.Template.Child()
    open_status_page: Adw.StatusPage = Gtk.Template.Child()
    error_status_page: Adw.StatusPage = Gtk.Template.Child()
    button_open: Gtk.Button = Gtk.Template.Child()

    video_page: Gtk.WindowHandle = Gtk.Template.Child()
    video: Gtk.Video = Gtk.Template.Child()
    header_revealer: Gtk.Revealer = Gtk.Template.Child()
    button_fullscreen = Gtk.Template.Child()

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)

        # HACK: Should reimplement Gtk.Video instead of hacking around in it
        self.media_controls = (
            self.video.get_first_child()
            .get_first_child()
            .get_next_sibling()
            .get_next_sibling()
            .get_first_child()
        )

        self.media_controls.get_parent().bind_property(
            "reveal-child",
            self.header_revealer,
            "reveal-child",
            GObject.BindingFlags.DEFAULT,
        )

        # Dock/undock the toolbar based on window size
        self.connect("notify::default-width", self.__on_width_changed)
        self.__on_width_changed()

        primary_click = Gtk.GestureClick(button=Gdk.BUTTON_PRIMARY)
        primary_click.connect(
            "released",
            lambda *_: (stream := self.video.get_media_stream()).set_playing(
                not stream.get_playing()
            ),
        )
        self.video.get_first_child().get_first_child().add_controller(primary_click)

        self.connect("notify::fullscreened", self.__on_fullscreen)
        self.stack.connect("notify::visible-child", self.__on_stack_child_changed)
        self.__on_stack_child_changed()

        (esc := Gtk.ShortcutController()).add_shortcut(
            Gtk.Shortcut.new(
                Gtk.ShortcutTrigger.parse_string("Escape"),
                Gtk.CallbackAction.new(lambda *_: self.unfullscreen()),
            )
        )
        self.video_page.add_controller(esc)

    def __on_width_changed(self, *_args: Any):
        # TODO: Only use floating controls in fullscreen if
        # screen size is greater than 600px
        if self.get_default_size().width > 600 or self.is_fullscreen():
            self.media_controls.set_margin_bottom(12)
            self.media_controls.set_margin_start(36)
            self.media_controls.set_margin_end(36)
            self.media_controls.add_css_class("toolbar")
        else:
            self.media_controls.set_margin_bottom(0)
            self.media_controls.set_margin_start(0)
            self.media_controls.set_margin_end(0)
            self.media_controls.remove_css_class("toolbar")

    def __on_fullscreen(self, *_args: Any):
        self.button_fullscreen.set_icon_name(
            "view-restore-symbolic"
            if self.is_fullscreen()
            else "view-fullscreen-symbolic"
        )
        self.__on_width_changed()

    def __on_stack_child_changed(self, *_args: Any) -> None:
        self.get_application().lookup_action("screenshot").set_enabled(
            self.stack.get_visible_child() == self.video_page
        )

    def __choose_video_cb(self, dialog: Gtk.FileDialog, res: Gio.AsyncResult) -> None:
        try:
            gfile = dialog.open_finish(res)
        except GLib.Error:
            return

        self.play_video(gfile)

    @Gtk.Template.Callback()
    def toggle_fullscreen(self, *_args: Any) -> None:
        if self.is_fullscreen():
            self.unfullscreen()
            return

        self.fullscreen()

    @Gtk.Template.Callback()
    def choose_video(self, *_args: Any) -> None:
        dialog = Gtk.FileDialog()

        filter = Gtk.FileFilter()
        filter.add_mime_type("video/*")
        filter.set_name(_("Video"))

        filters = Gio.ListStore()
        filters.append(filter)
        dialog.set_filters(filters)
        dialog.set_default_filter(filter)

        dialog.open(self, callback=self.__choose_video_cb)

    def __on_media_error(self, *_args: Any) -> None:
        self.error_status_page.set_description(
            self.video.get_media_stream().get_error().message
        )
        self.placeholder_stack.set_visible_child(self.error_status_page)
        self.stack.set_visible_child(self.placeholder_page)

    def play_video(self, gfile: Gio.File) -> None:
        self.video.set_file(gfile)
        self.video.get_media_stream().connect("notify::error", self.__on_media_error)
        self.stack.set_visible_child(self.video_page)

    def screenshot(self) -> None:
        # Copied from Workbench
        # https://github.com/workbenchdev/Workbench/blob/1ebbe1e3915aabfd172c166c88ca23ad08861d15/src/Previewer/previewer.vala#L36

        if not (stream := self.video.get_media_stream()):
            return

        paintable = stream.get_current_image()

        width = paintable.get_intrinsic_width()
        height = paintable.get_intrinsic_height()
        snapshot = Gtk.Snapshot()
        paintable.snapshot(snapshot, width, height)

        if not (node := snapshot.to_node()):
            logging.warning(
                f"Could not get node snapshot, width: {width}, height: {height}"
            )
            return

        rect = Graphene.Rect()
        rect.origin = Graphene.Point.zero()

        size = Graphene.Size()
        size.width = width
        size.height = height
        rect.size = size

        renderer = self.get_native().get_renderer()
        texture = renderer.render_texture(node, rect)

        if pictures := GLib.get_user_special_dir(GLib.USER_DIRECTORY_PICTURES):
            path = GLib.build_pathv(sep, (pictures, "Screenshots"))
        else:
            path = GLib.get_home_dir()

        if not (gfile := self.video.get_file()):
            return

        display_name = gfile.query_info(
            Gio.FILE_ATTRIBUTE_STANDARD_DISPLAY_NAME, Gio.FileQueryInfoFlags.NONE
        ).get_display_name()

        time = (
            (
                datetime.datetime.min
                + datetime.timedelta(microseconds=stream.get_timestamp())
            )
            .time()
            .strftime("%H:%M:%S")
        )

        path = GLib.build_pathv(
            sep,
            (path, f"{Path(display_name).stem} {time}.png"),
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
