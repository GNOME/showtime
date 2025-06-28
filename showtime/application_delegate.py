# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2024-2025 kramo

from typing import Any

from AppKit import (
    NSApp,  # pyright: ignore[reportAttributeAccessIssue]
    NSApplication,  # pyright: ignore[reportAttributeAccessIssue]
    NSMenu,  # pyright: ignore[reportAttributeAccessIssue]
    NSMenuItem,  # pyright: ignore[reportAttributeAccessIssue]
)
from Foundation import NSObject  # pyright: ignore[reportAttributeAccessIssue]
from gi.repository import Gio

import showtime
from showtime import utils


class ApplicationDelegate(NSObject):
    """macOS integration."""

    def applicationDidFinishLaunching_(self, *_args: Any) -> None:  # noqa: N802
        """Set up menu bar actions."""
        main_menu = NSApp.mainMenu()

        new_window_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            _("New Window"), "new:", "n"
        )

        open_menu_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            _("Open…"), "open:", "o"
        )

        file_menu = NSMenu.alloc().init()
        file_menu.addItem_(new_window_item)
        file_menu.addItem_(open_menu_item)

        file_menu_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            _("File"), None, ""
        )
        file_menu_item.setSubmenu_(file_menu)
        main_menu.addItem_(file_menu_item)

        windows_menu = NSMenu.alloc().init()

        windows_menu_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            _("Window"), None, ""
        )
        windows_menu_item.setSubmenu_(windows_menu)
        main_menu.addItem_(windows_menu_item)

        NSApp.setWindowsMenu_(windows_menu)

        keyboard_shortcuts_menu_item = (
            NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                _("Keyboard Shortcuts"), "shortcuts:", "?"
            )
        )

        help_menu = NSMenu.alloc().init()
        help_menu.addItem_(keyboard_shortcuts_menu_item)

        help_menu_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            _("Help"), None, ""
        )
        help_menu_item.setSubmenu_(help_menu)
        main_menu.addItem_(help_menu_item)

        NSApp.setHelpMenu_(help_menu)

    def new_(self, *_args: Any) -> None:
        """Create a new window."""
        if not showtime.app:
            return

        showtime.app.do_activate()

    def open_(self, *_args: Any) -> None:
        """Show the file chooser for opening a video."""
        if not (showtime.app and showtime.app.win):
            return

        if action := utils.lookup_action(showtime.app.win, "open-video"):
            action.activate()

    def shortcuts_(self, *_args: Any) -> None:
        """Open the shortcuts dialog."""
        if (
            showtime.app
            and showtime.app.win
            and (overlay := showtime.app.win.get_help_overlay())
        ):
            overlay.present()

    def application_openFile_(  # noqa: N802
        self,
        _theApplication: NSApplication,  # noqa: N803
        filename: str,
    ) -> bool:
        """Open a file."""
        if not (showtime.app and showtime.app.win):
            return False

        showtime.app.win.play_video(Gio.File.new_for_path(filename))
        return True
