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
import sys
from typing import Any, Optional, Sequence

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

# pylint: disable=wrong-import-position
# pylint: disable=wrong-import-order

from gi.repository import Adw, Gio, GLib

from afternoon import shared
from afternoon.window import AfternoonWindow


class AfternoonApplication(Adw.Application):
    """The main application singleton class."""

    def __init__(self):
        super().__init__(
            application_id=shared.APP_ID,
            flags=Gio.ApplicationFlags.HANDLES_OPEN,
        )

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
            "quit",
            lambda *_: self.quit(),
            ["<primary>q"],
        )
        self.create_action(
            "open-video",
            lambda *_: self.get_active_window().choose_video(),
            ["<primary>o"],
        )
        self.create_action(
            "open-subtitles",
            lambda *_: self.get_active_window().choose_subtitles(),
        )
        self.create_action(
            "screenshot",
            lambda *_: self.get_active_window().save_screenshot(),
        )
        self.create_action(
            "close-window",
            lambda *_: self.get_active_window().close(),
            ["<primary>w"],
        )
        self.create_action(
            "fullscreen",
            lambda *_: self.get_active_window().toggle_fullscreen(),
            ["F11"],
        )
        self.create_action(
            "about",
            self.on_about_action,
        )

        show_subtitles_action = Gio.SimpleAction.new_stateful(
            "show-subtitles", None, GLib.Variant.new_boolean(True)
        )
        show_subtitles_action.connect("activate", self.__show_subtitles)
        show_subtitles_action.connect("change-state", self.__show_subtitles)
        self.add_action(show_subtitles_action)

    def __show_subtitles(self, action: Gio.SimpleAction, _state: GLib.Variant) -> None:
        value = not action.props.state.get_boolean()
        action.set_state(GLib.Variant.new_boolean(value))

        # TODO: Use a signal handler for this
        for window in self.get_windows():
            window.subtitles_label.set_opacity(1 if value else 0)

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

        if not gfile:
            return

        win.play_video(gfile)

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
