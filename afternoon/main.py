# main.py
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

"""The main application singleton class."""
import logging
import pickle
import sys
from hashlib import sha256
from typing import Any, Optional, Sequence

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gst", "1.0")
gi.require_version("GstPlay", "1.0")

# pylint: disable=wrong-import-position
# pylint: disable=wrong-import-order

from gi.repository import Adw, Gio, GLib, GObject, Gst, Gtk

from afternoon import shared
from afternoon.mpris import MPRIS
from afternoon.window import AfternoonWindow


class AfternoonApplication(Adw.Application):
    """The main application singleton class."""

    inhibit_cookies: dict = {}
    mpris_active: bool = False

    @GObject.Signal(name="media-info-updated")
    def __media_info_updated(self) -> None:
        """Emitted when the currently active video's media info is updated."""

    @GObject.Signal(name="state-changed")
    def __state_changed(self) -> None:
        """Emitted when the currently active video's state changes."""

    def __init__(self):
        super().__init__(
            application_id=shared.APP_ID,
            flags=Gio.ApplicationFlags.HANDLES_OPEN,
        )
        Gst.init()

        new_window = GLib.OptionEntry()
        new_window.long_name = "new-window"
        new_window.short_name = ord("n")
        new_window.flags = int(GLib.OptionFlags.NONE)
        new_window.arg = int(GLib.OptionArg.NONE)
        new_window.arg_data = None
        new_window.description = "Open the app with a new window"
        new_window.arg_description = None

        self.add_main_option_entries((new_window,))
        self.set_option_context_parameter_string("[VIDEO FILES]")

        self.create_action(
            "new-window",
            lambda *_: self.activate(),
            ("<primary>n",),
        )
        self.create_action(
            "open-video",
            lambda *_: self.get_active_window().choose_video(),
            ("<primary>o",),
        )
        self.create_action(
            "show-in-files",
            lambda *_: Gtk.FileLauncher.new(
                Gio.File.new_for_uri(self.get_active_window().play.get_uri())
            ).open_containing_folder(),
        )
        self.create_action(
            "screenshot",
            lambda *_: self.get_active_window().save_screenshot(),
            ("<primary><alt>s",),
        )
        self.lookup_action("screenshot").set_enabled(False)
        self.lookup_action("show-in-files").set_enabled(False)
        self.create_action(
            "fullscreen",
            lambda *_: self.get_active_window().toggle_fullscreen(),
            ("F11", "f"),
        )
        self.create_action(
            "toggle-playback",
            lambda *_: self.get_active_window().toggle_playback(),
            ("p", "k", "space"),
        )
        self.create_action(
            "increase-volume",
            lambda *_: (play := self.get_active_window().play).set_volume(
                min(play.get_volume() + 0.05, 1)
            ),
            ("Up",),
        )
        self.create_action(
            "decrease-volume",
            lambda *_: (play := self.get_active_window().play).set_volume(
                max(play.get_volume() - 0.05, 0)
            ),
            ("Down",),
        )
        self.create_action(
            "toggle-mute",
            lambda *_: self.get_active_window().toggle_mute(),
            ("m",),
        )
        self.create_action(
            "backwards",
            lambda *_: (play := self.get_active_window().play).seek(
                max(0, play.get_position() - pow(10, 10))
            ),
            ("Left",),
        )
        self.create_action(
            "forwards",
            lambda *_: (play := self.get_active_window().play).seek(
                play.get_position() + pow(10, 10)
            ),
            ("Right",),
        )
        self.create_action(
            "close-window",
            lambda *_: self.get_active_window().close(),
            ("<primary>w",),
        )
        self.create_action(
            "quit",
            lambda *_: self.quit(),
            ("<primary>q",),
        )
        self.create_action(
            "about",
            self.on_about_action,
        )
        self.create_action(
            "choose-subtitles",
            lambda *_: self.get_active_window().choose_subtitles(),
        )

        subs_action = Gio.SimpleAction.new_stateful(
            "select-subtitles", GLib.VariantType.new("q"), GLib.Variant.new_uint16(0)
        )
        subs_action.connect(
            "activate", lambda *args: self.get_active_window().select_subtitles(*args)
        )
        self.add_action(subs_action)

        lang_action = Gio.SimpleAction.new_stateful(
            "select-language", GLib.VariantType.new("q"), GLib.Variant.new_uint16(0)
        )
        lang_action.connect(
            "activate", lambda *args: self.get_active_window().select_language(*args)
        )
        self.add_action(lang_action)

        self.connect("window-removed", self.__on_window_removed)

    def __on_window_removed(self, _obj: Any, win: AfternoonWindow) -> None:
        self.save_play_position(win)
        self.uninhibit_win(win)

    def inhibit_win(self, win: AfternoonWindow) -> None:
        """
        Tries to add an inhibitor associated with `win`.

        This will automatically be removed when `win` is closed.
        """
        self.inhibit_cookies[win] = self.inhibit(
            win, Gtk.ApplicationInhibitFlags.IDLE, _("Playing a video")
        )

    def uninhibit_win(self, win: AfternoonWindow) -> None:
        """Removes the inhibitor associated with `win` if one exists."""
        if not (cookie := self.inhibit_cookies.pop(win, 0)):
            return

        self.uninhibit(cookie)

    def save_play_position(self, win: AfternoonWindow) -> None:
        """Saves the play position of the currently playing file in the window to restore later."""
        if not (uri := win.play.get_uri()):
            return

        digest = sha256(uri.encode("utf-8")).hexdigest()

        shared.cache_path.mkdir(parents=True, exist_ok=True)
        hist_path = shared.cache_path / "playback_history"

        try:
            hist_file = hist_path.open("rb")
        except FileNotFoundError:
            hist = {}
        else:
            try:
                hist = pickle.load(hist_file)
            except EOFError:
                hist = {}

            hist_file.close()

        hist[digest] = win.play.get_position()

        MAX_HIST_ITEMS = 1000

        for _extra in range(max(len(hist) - MAX_HIST_ITEMS, 0)):
            del hist[next(iter(hist))]

        with hist_path.open("wb") as hist_file:
            pickle.dump(hist, hist_file)

    def do_activate(  # pylint: disable=arguments-differ
        self, gfile: Optional[Gio.File] = None
    ) -> None:
        """Called when the application is activated.

        We raise the application's main window, creating it if
        necessary.
        """
        Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.PREFER_DARK)

        win = AfternoonWindow(application=self)
        win.present()

        def emit_media_info_updated(win) -> None:
            if win == self.get_active_window():
                self.emit("media-info-updated")

        win.connect("media-info-updated", emit_media_info_updated)

        def emit_state_changed(win, _args: Any) -> None:
            if win == self.get_active_window():
                self.emit("state-changed")

        win.connect("notify::paused", emit_state_changed)

        if gfile:
            win.play_video(gfile)

        if self.mpris_active:
            return

        self.mpris_active = True
        MPRIS(self)

    def do_open(  # pylint: disable=arguments-differ
        self, gfiles: Sequence[Gio.File], _n_files: int, _hint: str
    ) -> None:
        """Opens the given files."""
        for gfile in gfiles:
            self.do_activate(gfile)

    def do_handle_local_options(  # pylint: disable=arguments-differ
        self, options: GLib.VariantDict
    ) -> int:
        """Handles local command line arguments."""
        self.register()  # This is so get_is_remote works
        if self.get_is_remote():
            if options.contains("new-window"):
                return -1

            logging.warning(
                "Afternoon is already running. "
                "To open a new window, run the app with --new-window."
            )
            return 0

        return -1

    def on_about_action(self, *_args: Any):
        """Callback for the app.about action."""
        about = Adw.AboutDialog(
            application_name="Afternoon",
            application_icon=shared.APP_ID,
            developer_name="kramo",
            version=shared.VERSION,
            developers=["kramo"],
            copyright="© 2024 kramo",
        )
        about.present(self.get_active_window())

    def create_action(self, name, callback, shortcuts=None):
        """Add an application action.

        Args:
            name: the name of the action
            callback: the function to be called when the action is
              activated
            shortcuts: an optional list of accelerators
        """
        action = Gio.SimpleAction.new(name, None)
        action.connect("activate", callback)
        self.add_action(action)
        if shortcuts:
            self.set_accels_for_action(f"app.{name}", shortcuts)


def main():
    """The application's entry point."""
    app = AfternoonApplication()
    return app.run(sys.argv)
