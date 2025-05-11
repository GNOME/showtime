# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2024-2025 kramo

"""The main application singleton class."""

import logging
import lzma
import pickle
import sys
from collections.abc import Callable, Sequence
from hashlib import sha256
from typing import Any

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gst", "1.0")
gi.require_version("GstPlay", "1.0")
gi.require_version("GstAudio", "1.0")
gi.require_version("GstPbutils", "1.0")

# pylint: disable=wrong-import-position
# pylint: disable=wrong-import-order

from gi.repository import Adw, Gio, GLib, GObject, Gst, Gtk

import showtime
from showtime import APP_ID, PREFIX, VERSION, state_settings, system
from showtime.logging.setup import log_system_info, setup_logging
from showtime.mpris import MPRIS
from showtime.utils import lookup_action
from showtime.window import Window

if system == "Darwin":
    from AppKit import NSApp  # type: ignore
    from PyObjCTools import AppHelper

    from showtime.application_delegate import ApplicationDelegate

MAX_HIST_ITEMS = 1000


class Application(Adw.Application):
    """The main application singleton class."""

    inhibit_cookies: dict = {}
    mpris_active: bool = False

    media_info_updated = GObject.Signal(name="media-info-updated")
    state_changed = GObject.Signal(name="state-changed")
    volume_changed = GObject.Signal(name="volume-changed")
    rate_changed = GObject.Signal(name="rate-changed")
    seeked = GObject.Signal(name="seeked")

    def __init__(self) -> None:
        super().__init__(
            application_id=APP_ID,
            flags=Gio.ApplicationFlags.HANDLES_OPEN,
        )

        Gst.init()

        try:
            setup_logging()
        except ValueError:
            pass

        log_system_info()

        if system == "Darwin":

            def setup_app_delegate() -> None:
                NSApp.setDelegate_(ApplicationDelegate.alloc().init())  # type: ignore
                AppHelper.runEventLoop()  # type: ignore

            GLib.Thread.new(None, setup_app_delegate)

        new_window = GLib.OptionEntry()
        new_window.long_name = "new-window"
        new_window.short_name = ord("n")
        new_window.flags = int(GLib.OptionFlags.NONE)
        new_window.arg = int(GLib.OptionArg.NONE)  # type: ignore
        new_window.arg_data = None
        new_window.description = "Open the app with a new window"

        self.add_main_option_entries((new_window,))
        self.set_option_context_parameter_string("[VIDEO FILES]")

        if system == "Darwin" and (settings := Gtk.Settings.get_default()):
            settings.props.gtk_decoration_layout = "close,minimize:"

        self.connect("window-removed", self._on_window_removed)
        self.connect("shutdown", self._on_shutdown)

    @property
    def win(self) -> Window | None:  # type: ignore
        """The currently active window."""
        return (
            win if isinstance(win := self.props.active_window, Window) else None  # type: ignore
        )

    def inhibit_win(self, win: Window) -> None:  # type: ignore
        """Try to add an inhibitor associated with `win`.

        This will automatically be removed when `win` is closed.
        """
        self.inhibit_cookies[win] = self.inhibit(
            win, Gtk.ApplicationInhibitFlags.IDLE, _("Playing a video")
        )

    def uninhibit_win(self, win: Window) -> None:  # type: ignore
        """Remove the inhibitor associated with `win` if one exists."""
        if not (cookie := self.inhibit_cookies.pop(win, 0)):
            return

        self.uninhibit(cookie)

    def save_play_position(self, win: Window) -> None:  # type: ignore
        """Save the play position of the currently playing file in the window to restore later."""
        if not (uri := win.play.props.uri):
            return

        digest = sha256(uri.encode("utf-8")).hexdigest()

        showtime.cache_path.mkdir(parents=True, exist_ok=True)
        hist_path = showtime.cache_path / "playback_history"

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

        hist[digest] = win.play.props.position

        for _extra in range(max(len(hist) - MAX_HIST_ITEMS, 0)):
            del hist[next(iter(hist))]

        with hist_path.open("wb") as hist_file:
            pickle.dump(hist, hist_file)

    def do_startup(self) -> None:
        """Set up actions."""
        Adw.Application.do_startup(self)

        Adw.StyleManager.get_default().props.color_scheme = Adw.ColorScheme.PREFER_DARK

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
                    Gio.File.new_for_uri(self.win.play.props.uri)
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

        if action := lookup_action(self, "screenshot"):
            action.props.enabled = False

        if action := lookup_action(self, "show-in-files"):
            action.props.enabled = False

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
                (play := self.win.play).set_volume(min(play.props.volume + 0.05, 1))
                if self.win
                else None
            ),
            ("Up",),
        )
        self.create_action(
            "decrease-volume",
            lambda *_: (
                (play := self.win.play).set_volume(max(play.props.volume - 0.05, 0))
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
                (play := self.win.play).seek(max(0, play.props.position - 1e10))
                if self.win
                else None
            ),
            ("Left",),
        )
        self.create_action(
            "forwards",
            lambda *_: (
                (play := self.win.play).seek(play.props.position + 1e10)
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
            "select-subtitles",
            GLib.VariantType.new("q"),
            GLib.Variant.new_uint16(0),
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
            "toggle-loop",
            None,
            GLib.Variant.new_boolean(state_settings.get_boolean("looping")),
        )
        toggle_loop_action.connect("activate", self._on_toggle_loop)
        toggle_loop_action.connect("change-state", self._on_toggle_loop)
        self.add_action(toggle_loop_action)

    def do_activate(  # pylint: disable=arguments-differ
        self, gfile: Gio.File | None = None
    ) -> None:
        """Create a new window, set up MPRIS."""
        win = Window(
            application=self,  # type: ignore
            maximized=state_settings.get_boolean("is-maximized"),  # type: ignore
        )
        state_settings.bind("is-maximized", win, "maximized", Gio.SettingsBindFlags.SET)

        def emit_media_info_updated(win: Window) -> None:  #  type: ignore
            if win == self.props.active_window:
                self.emit("media-info-updated")

        win.connect("media-info-updated", emit_media_info_updated)

        def emit_volume_changed(win: Window) -> None:
            if win == self.props.active_window:
                self.emit("volume-changed")

        win.connect("volume-changed", emit_volume_changed)

        def emit_rate_changed(win: Window) -> None:
            if win == self.props.active_window:
                self.emit("rate-changed")

        win.connect("rate-changed", emit_rate_changed)

        def emit_seeked(win: Window) -> None:
            if win == self.props.active_window:
                self.emit("seeked")

        win.connect("seeked", emit_seeked)

        def emit_state_changed(win: Window, *_args: Any) -> None:  # type: ignore
            if win == self.props.active_window:
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

        if not self.mpris_active:
            self.mpris_active = True
            MPRIS(self)

    def do_open(self, gfiles: Sequence[Gio.File], _n_files: int, _hint: str) -> None:  # type: ignore
        """Open the given files."""
        for gfile in gfiles:
            self.do_activate(gfile)

    def do_handle_local_options(  # pylint: disable=arguments-differ
        self, options: GLib.VariantDict
    ) -> int:
        """Handle local command line arguments."""
        self.register()  # This is so props.is_remote works
        if self.props.is_remote:
            if options.contains("new-window"):
                return -1

            logging.warning(
                "Showtime is already running. "
                "To open a new window, run the app with --new-window."
            )
            return 0

        return -1

    def on_about_action(self, *_args: Any) -> None:
        """Show the about dialog."""
        # Get the debug info from the log files
        debug_str = ""
        for index, path in enumerate(showtime.log_files):
            # Add a horizontal line between runs
            if index > 0:
                debug_str += "─" * 37 + "\n"
            # Add the run's logs
            log_file = (
                lzma.open(path, "rt", encoding="utf-8")
                if path.name.endswith(".xz")
                else path.open("r", encoding="utf-8")
            )
            debug_str += data if isinstance(data := log_file.read(), str) else ""
            log_file.close()

        about = Adw.AboutDialog.new_from_appdata(
            PREFIX + "/" + APP_ID + ".metainfo.xml", VERSION
        )
        about.props.developers = ["kramo https://kramo.page"]
        about.props.designers = [
            "Tobias Bernard https://tobiasbernard.com/",
            "Allan Day https://blogs.gnome.org/aday/",
            "kramo https://kramo.page",
        ]
        about.props.copyright = "© 2024 kramo"
        # Translators: Replace this with your name for it to show up in the about dialog
        about.props.translator_credits = _("translator_credits")
        about.props.debug_info = debug_str
        about.props.debug_info_filename = "showtime.log"
        about.present(self.props.active_window)

    def create_action(
        self,
        name: str,
        callback: Callable,
        shortcuts: Sequence[str] | None = None,
    ) -> None:
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
            if system == "Darwin":
                shortcuts = tuple(s.replace("<primary>", "<meta>") for s in shortcuts)
            self.set_accels_for_action(f"app.{name}", shortcuts)

    def _on_toggle_loop(self, action: Gio.SimpleAction, _state: GLib.Variant) -> None:
        value = not action.props.state.get_boolean()
        action.set_state(GLib.Variant.new_boolean(value))

        self.win.set_looping(value) if self.win else ...

    def _on_window_removed(self, _obj: Any, win: Window) -> None:  # type: ignore
        self.save_play_position(win)
        self.uninhibit_win(win)
        del win.play

    def _on_shutdown(self, *_args: Any) -> None:
        for win in self.get_windows():
            if isinstance(win, Window):  # type: ignore
                self._on_window_removed(None, win)


def main() -> int:
    """Run the application."""
    showtime.app = Application()
    return showtime.app.run(sys.argv)
