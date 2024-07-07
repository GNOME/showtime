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
import lzma
import pickle
import sys
from hashlib import sha256
from typing import Any, Optional, Sequence

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gst", "1.0")
gi.require_version("GstPlay", "1.0")
gi.require_version("GstPbutils", "1.0")

# pylint: disable=wrong-import-position
# pylint: disable=wrong-import-order

from gi.repository import Adw, Gio, GLib, GObject, Gst, Gtk

from showtime import shared
from showtime.drag_overlay import ShowtimeDragOverlay
from showtime.logging.setup import log_system_info, setup_logging
from showtime.mpris import MPRIS
from showtime.window import ShowtimeWindow


class ShowtimeApplication(Adw.Application):
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

        setup_logging()
        log_system_info()

        Gst.init()

        new_window = GLib.OptionEntry()
        new_window.long_name = "new-window"
        new_window.short_name = ord("n")
        new_window.flags = int(GLib.OptionFlags.NONE)
        new_window.arg = int(GLib.OptionArg.NONE)  # type: ignore
        new_window.arg_data = None
        new_window.description = "Open the app with a new window"

        self.add_main_option_entries((new_window,))
        self.set_option_context_parameter_string("[VIDEO FILES]")

        self.create_action(
            "new-window",
            lambda *_: self.activate(),
            ("<primary>n",),
        )
        self.create_action(
            "open-video",
            lambda *_: (self.win.choose_video() if self.win else ...),
            ("<primary>o",),
        )
        self.create_action(
            "show-in-files",
            lambda *_: (
                Gtk.FileLauncher.new(
                    Gio.File.new_for_uri(self.win.play.get_uri())
                ).open_containing_folder()
                if self.win
                else None
            ),
        )
        self.create_action(
            "screenshot",
            lambda *_: self.win.save_screenshot() if self.win else ...,
            ("<primary><alt>s",),
        )
        (
            a.set_enabled(False)
            if isinstance(a := self.lookup_action("screenshot"), Gio.SimpleAction)
            else ...
        )
        (
            a.set_enabled(False)
            if isinstance(a := self.lookup_action("show-in-files"), Gio.SimpleAction)
            else ...
        )
        self.create_action(
            "toggle-fullscreen",
            lambda *_: self.win.toggle_fullscreen() if self.win else ...,
            ("F11", "f"),
        )
        self.create_action(
            "toggle-playback",
            lambda *_: self.win.toggle_playback() if self.win else ...,
            ("p", "k", "space"),
        )
        self.create_action(
            "increase-volume",
            lambda *_: (
                (play := self.win.play).set_volume(min(play.get_volume() + 0.05, 1))
                if self.win
                else None
            ),
            ("Up",),
        )
        self.create_action(
            "decrease-volume",
            lambda *_: (
                (play := self.win.play).set_volume(max(play.get_volume() - 0.05, 0))
                if self.win
                else None
            ),
            ("Down",),
        )
        self.create_action(
            "toggle-mute",
            lambda *_: self.win.toggle_mute() if self.win else ...,
            ("m",),
        )

        self.create_action(
            "backwards",
            lambda *_: (
                (play := self.win.play).seek(max(0, play.get_position() - 1e10))
                if self.win
                else None
            ),
            ("Left",),
        )
        self.create_action(
            "forwards",
            lambda *_: (
                (play := self.win.play).seek(play.get_position() + 1e10)
                if self.win
                else None
            ),
            ("Right",),
        )
        self.create_action(
            "close-window",
            lambda *_: self.win.close() if self.win else ...,
            ("<primary>w", "q"),
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
            lambda *_: self.win.choose_subtitles() if self.win else ...,
        )

        subs_action = Gio.SimpleAction.new_stateful(
            "select-subtitles", GLib.VariantType.new("q"), GLib.Variant.new_uint16(0)
        )
        subs_action.connect(
            "activate",
            lambda *args: self.win.select_subtitles(*args) if self.win else ...,
        )
        self.add_action(subs_action)

        lang_action = Gio.SimpleAction.new_stateful(
            "select-language", GLib.VariantType.new("q"), GLib.Variant.new_uint16(0)
        )
        lang_action.connect(
            "activate",
            lambda *args: self.win.select_language(*args) if self.win else ...,
        )
        self.add_action(lang_action)

        toggle_loop_action = Gio.SimpleAction.new_stateful(
            "toggle-loop", None, GLib.Variant.new_boolean(False)
        )
        toggle_loop_action.connect("activate", self.__on_toggle_loop)
        toggle_loop_action.connect("change-state", self.__on_toggle_loop)
        self.add_action(toggle_loop_action)

        self.connect("window-removed", self.__on_window_removed)
        self.connect("shutdown", self.__on_shutdown)

    @property
    def win(self) -> Optional[ShowtimeWindow]:
        """The currently active window."""
        return (
            win if isinstance(win := self.get_active_window(), ShowtimeWindow) else None
        )

    def __on_toggle_loop(self, action: Gio.SimpleAction, _state: GLib.Variant):
        value = not action.props.state.get_boolean()
        action.set_state(GLib.Variant.new_boolean(value))

        self.win.set_looping(value) if self.win else ...

    def __on_window_removed(self, _obj: Any, win: ShowtimeWindow) -> None:
        self.save_play_position(win)
        self.uninhibit_win(win)
        del win.play

    def __on_shutdown(self, *_args: Any) -> None:
        for win in self.get_windows():
            if isinstance(win, ShowtimeWindow):
                self.__on_window_removed(None, win)

    def inhibit_win(self, win: ShowtimeWindow) -> None:
        """
        Tries to add an inhibitor associated with `win`.

        This will automatically be removed when `win` is closed.
        """
        self.inhibit_cookies[win] = self.inhibit(
            win, Gtk.ApplicationInhibitFlags.IDLE, _("Playing a video")
        )

    def uninhibit_win(self, win: ShowtimeWindow) -> None:
        """Removes the inhibitor associated with `win` if one exists."""
        if not (cookie := self.inhibit_cookies.pop(win, 0)):
            return

        self.uninhibit(cookie)

    def save_play_position(self, win: ShowtimeWindow) -> None:
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
        """
        Called when the application is activated.

        Creates a new window and sets up MPRIS.
        """
        Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.PREFER_DARK)

        win = ShowtimeWindow(
            application=self, maximized=shared.state_schema.get_boolean("is-maximized")
        )
        shared.state_schema.bind(
            "is-maximized", win, "maximized", Gio.SettingsBindFlags.SET
        )

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

            tries = 0

            # Present the window only after it has loaded or after a 1s timeout
            def present_timeout() -> bool:
                nonlocal tries

                tries += 1
                if (not win.buffering) or (tries >= 50):
                    win.present()
                    return False

                return True

            GLib.timeout_add(20, present_timeout)
        else:
            win.present()

        if self.mpris_active:
            return

        self.mpris_active = True
        MPRIS(self)

    def do_open(  # type: ignore
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
                "Showtime is already running. "
                "To open a new window, run the app with --new-window."
            )
            return 0

        return -1

    def on_about_action(self, *_args: Any) -> None:
        """Callback for the app.about action."""

        # Get the debug info from the log files
        debug_str = ""
        for index, path in enumerate(shared.log_files):
            # Add a horizontal line between runs
            if index > 0:
                debug_str += "─" * 37 + "\n"
            # Add the run's logs
            log_file = (
                lzma.open(path, "rt", encoding="utf-8")
                if path.name.endswith(".xz")
                else open(path, "r", encoding="utf-8")
            )
            debug_str += log_file.read()
            log_file.close()

        about = Adw.AboutDialog.new_from_appdata(
            shared.PREFIX + "/" + shared.APP_ID + ".metainfo.xml", shared.VERSION
        )
        about.set_developers(("kramo https://kramo.page",))
        about.set_designers(
            (
                "Tobias Bernard https://tobiasbernard.com/",
                "Allan Day https://blogs.gnome.org/aday/",
                "kramo https://kramo.page",
            )
        )
        about.set_copyright("© 2024 kramo")
        # Translators: Replace this with your name for it to show up in the about dialog
        about.set_translator_credits(_("translator_credits"))
        about.set_debug_info(debug_str)
        about.set_debug_info_filename("showtime.log")
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
    app = ShowtimeApplication()
    return app.run(sys.argv)
