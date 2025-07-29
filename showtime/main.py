# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2024-2025 kramo

import json
import logging
import sys
from collections.abc import Callable, Sequence
from hashlib import sha256
from logging.handlers import RotatingFileHandler
from typing import Any

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gst", "1.0")
gi.require_version("GstPlay", "1.0")
gi.require_version("GstAudio", "1.0")
gi.require_version("GstPbutils", "1.0")

from gi.repository import Adw, Gio, GLib, GObject, Gst, Gtk

import showtime
from showtime import APP_ID, VERSION, log_file, logger, state_settings, system

from .mpris import MPRIS
from .widgets.window import PROFILE, Window

# if system == "Darwin":
#     from AppKit import NSApp
#     from PyObjCTools import AppHelper
#
#     from showtime.application_delegate import ApplicationDelegate

MAX_HIST_ITEMS = 1000
MAX_BUFFER_TRIES = 50


class Application(Adw.Application):
    """The main application singleton class."""

    inhibit_cookies: dict
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

        self.inhibit_cookies = {}

        Gst.init()

        logger.debug("Starting %s v%s (%s)", APP_ID, VERSION, PROFILE)
        logger.debug("Python version: %s", sys.version)
        logger.debug("GStreamer version: %s", ".".join(str(v) for v in Gst.version()))

        # if system == "Darwin":
        #
        #     def setup_app_delegate() -> None:
        #         NSApp.setDelegate_(ApplicationDelegate.alloc().init())
        #         AppHelper.runEventLoop()
        #
        #     GLib.Thread.new(None, setup_app_delegate)

        new_window = GLib.OptionEntry()
        new_window.long_name = "new-window"
        new_window.short_name = ord("n")
        new_window.flags = int(GLib.OptionFlags.NONE)
        new_window.arg = int(GLib.OptionArg.NONE)  # pyright: ignore[reportAttributeAccessIssue]
        new_window.arg_data = None
        new_window.description = "Open the app with a new window"

        self.add_main_option_entries((new_window,))
        self.set_option_context_parameter_string("[VIDEO FILES]")

        if system == "Darwin" and (settings := Gtk.Settings.get_default()):
            settings.props.gtk_decoration_layout = "close,minimize,maximize:"

        self.connect("window-removed", self._on_window_removed)
        self.connect("shutdown", self._on_shutdown)

    @property
    def win(self) -> Window | None:  # pyright: ignore[reportAttributeAccessIssue]
        """The currently active window."""
        return (
            win if isinstance(win := self.props.active_window, Window) else None  # pyright: ignore[reportAttributeAccessIssue]
        )

    def inhibit_win(self, win: Window) -> None:  # pyright: ignore[reportAttributeAccessIssue]
        """Try to add an inhibitor associated with `win`.

        This will automatically be removed when `win` is closed.
        """
        self.inhibit_cookies[win] = self.inhibit(
            win, Gtk.ApplicationInhibitFlags.IDLE, _("Playing a video")
        )

    def uninhibit_win(self, win: Window) -> None:  # pyright: ignore[reportAttributeAccessIssue]
        """Remove the inhibitor associated with `win` if one exists."""
        if not (cookie := self.inhibit_cookies.pop(win, 0)):
            return

        self.uninhibit(cookie)

    def save_play_position(self, win: Window) -> None:
        """Save the play position of the currently playing video to restore later."""
        if not (uri := win.play.props.uri):
            return

        digest = sha256(uri.encode("utf-8")).hexdigest()

        showtime.state_path.mkdir(parents=True, exist_ok=True)
        hist_path = showtime.state_path / "playback_history.json"

        try:
            hist_file = hist_path.open("r")
        except FileNotFoundError:
            hist = {}
        else:
            try:
                hist = json.load(hist_file)
            except EOFError:
                hist = {}

            hist_file.close()

        hist[digest] = win.play.props.position

        for _extra in range(max(len(hist) - MAX_HIST_ITEMS, 0)):
            del hist[next(iter(hist))]

        with hist_path.open("w") as hist_file:
            json.dump(hist, hist_file)

    def do_startup(self) -> None:
        """Set up actions."""
        Adw.Application.do_startup(self)

        Adw.StyleManager.get_default().props.color_scheme = Adw.ColorScheme.PREFER_DARK

        self._create_action("new-window", lambda *_: self.activate(), ("<primary>n",))
        self._create_action("quit", lambda *_: self.quit(), ("<primary>q",))

    def do_activate(self, gfile: Gio.File | None = None) -> None:
        """Create a new window, set up MPRIS."""
        win = Window(
            application=self,  # pyright: ignore[reportAttributeAccessIssue]
            maximized=state_settings.get_boolean("is-maximized"),  # pyright: ignore[reportAttributeAccessIssue]
        )
        state_settings.bind("is-maximized", win, "maximized", Gio.SettingsBindFlags.SET)

        win.connect(
            "media-info-updated",
            lambda win: self.emit("media-info-updated")
            if win == self.props.active_window
            else None,
        )

        win.connect(
            "volume-changed",
            lambda win: self.emit("volume-changed")
            if win == self.props.active_window
            else None,
        )

        win.connect(
            "rate-changed",
            lambda win: self.emit("rate-changed")
            if win == self.props.active_window
            else None,
        )

        win.connect(
            "seeked",
            lambda win: self.emit("seeked")
            if win == self.props.active_window
            else None,
        )

        win.connect(
            "notify::paused",
            lambda win, *_: self.emit("state-changed")
            if win == self.props.active_window
            else None,
        )

        if gfile:
            win.play_video(gfile)

            tries = 0

            # Present the window only after it has loaded or after a 1s timeout
            def present_timeout() -> bool:
                nonlocal tries

                tries += 1
                if (not win.buffering) or (tries >= MAX_BUFFER_TRIES):
                    win.present()
                    return False

                return True

            GLib.timeout_add(20, present_timeout)
        else:
            win.present()

        if not self.mpris_active:
            self.mpris_active = True
            MPRIS(self)

    def do_open(self, gfiles: Sequence[Gio.File], _n_files: int, _hint: str) -> None:  # pyright: ignore[reportIncompatibleMethodOverride]
        """Open the given files."""
        for gfile in gfiles:
            self.do_activate(gfile)

    def do_handle_local_options(self, options: GLib.VariantDict) -> int:
        """Handle local command line arguments."""
        self.register()  # This is so props.is_remote works
        if self.props.is_remote:
            if options.contains("new-window"):
                return -1

            logger.warning(
                "Showtime is already running. "
                "To open a new window, run the app with --new-window."
            )
            return 0

        return -1

    def _create_action(
        self,
        name: str,
        callback: Callable,
        shortcuts: Sequence[str] | None = None,
    ) -> None:
        action = Gio.SimpleAction.new(name, None)
        action.connect("activate", callback)
        self.add_action(action)

        if shortcuts:
            if system == "Darwin":
                shortcuts = tuple(s.replace("<primary>", "<meta>") for s in shortcuts)

            self.set_accels_for_action(f"app.{name}", shortcuts)

    def _on_window_removed(self, _obj: Any, win: Window) -> None:  # pyright: ignore[reportAttributeAccessIssue]
        self.save_play_position(win)
        self.uninhibit_win(win)
        win.play.stop()

    def _on_shutdown(self, *_args: Any) -> None:
        for win in self.get_windows():
            if isinstance(win, Window):  # pyright: ignore[reportAttributeAccessIssue]
                self._on_window_removed(None, win)


def main() -> int:
    """Run the application."""
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(levelname)s: %(name)s:%(lineno)d %(message)s",
        handlers=(
            (
                logging.StreamHandler(),
                RotatingFileHandler(log_file, maxBytes=1_000_000),
            )
        ),
    )

    showtime.app = Application()
    return showtime.app.run(sys.argv)
