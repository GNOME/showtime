# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2024-2025 kramo

"""A set of methods that manage the app’s life cycle and its interaction with common system services."""

from typing import Any

from AppKit import NSApp, NSApplication, NSMenu, NSMenuItem  # type: ignore
from Foundation import NSObject  # type: ignore
from gi.repository import Gio

from showtime import app


class ApplicationDelegate(NSObject):
    """A set of methods that manage the app’s life cycle and its interaction with common system services."""

    def applicationDidFinishLaunching_(self, *_args: Any) -> None:  # noqa: N802
        """Set up menu bar actions."""
        main_menu = NSApp.mainMenu()

        new_window_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "New Window", "new:", "n"
        )

        open_menu_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Open…", "open:", "o"
        )

        file_menu = NSMenu.alloc().init()
        file_menu.addItem_(new_window_item)
        file_menu.addItem_(open_menu_item)

        file_menu_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "File", None, ""
        )
        file_menu_item.setSubmenu_(file_menu)
        main_menu.addItem_(file_menu_item)

        windows_menu = NSMenu.alloc().init()

        windows_menu_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Window", None, ""
        )
        windows_menu_item.setSubmenu_(windows_menu)
        main_menu.addItem_(windows_menu_item)

        NSApp.setWindowsMenu_(windows_menu)

        keyboard_shortcuts_menu_item = (
            NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                "Keyboard Shortcuts", "shortcuts:", "?"
            )
        )

        help_menu = NSMenu.alloc().init()
        help_menu.addItem_(keyboard_shortcuts_menu_item)

        help_menu_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Help", None, ""
        )
        help_menu_item.setSubmenu_(help_menu)
        main_menu.addItem_(help_menu_item)

        NSApp.setHelpMenu_(help_menu)

    def new_(self, *_args: Any) -> None:
        """Create a new window."""
        if not app:
            return

        app.do_activate()

    def open_(self, *_args: Any) -> None:
        """Show the file chooser for opening a video."""
        if (not (app)) or (not app.win):
            return

        app.win.choose_video()

    def shortcuts_(self, *_args: Any) -> None:
        """Open the shortcuts dialog."""
        if (
            (not (app))
            or (not app.win)
            or (not (overlay := app.win.get_help_overlay()))
        ):
            return

        overlay.present()

    def application_openFile_(  # noqa: N802
        self,
        _theApplication: NSApplication,  # noqa: N803
        filename: str,
    ) -> bool:
        """Open a file."""
        if (not app) or (not app.win):
            return False

        app.win.play_video(Gio.File.new_for_path(filename))
        return True
