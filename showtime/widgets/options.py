# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2024-2025 kramo
# SPDX-FileCopyrightText: Copyright 2025 Jamie Gravendeel

from gettext import ngettext
from typing import Any

from gi.repository import (
    Adw,
    Gdk,
    Gio,
    GLib,
    GObject,
    GstPlay,  # pyright: ignore[reportAttributeAccessIssue]
    Gtk,
)

from showtime import PREFIX, state_settings
from showtime.utils import lookup_action


@Gtk.Template.from_resource(f"{PREFIX}/gtk/options.ui")
class Options(Adw.Bin):
    """A bin containing the options menu button and its popover."""

    __gtype_name__ = "Options"

    menu_button: Gtk.MenuButton = Gtk.Template.Child()
    popover: Gtk.PopoverMenu = Gtk.Template.Child()

    language_menu: Gio.Menu = Gtk.Template.Child()
    subtitles_menu: Gio.Menu = Gtk.Template.Child()

    rotate_left = GObject.Signal()
    rotate_right = GObject.Signal()

    rate = GObject.Property(type=str)

    menus_building = 0

    def on_secondary_click_pressed(
        self,
        window: Adw.ApplicationWindow,
        gesture: Gtk.Gesture,
        x: int,
        y: int,
    ) -> None:
        """Parent and unparent the popover appropriately."""
        gesture.set_state(Gtk.EventSequenceState.CLAIMED)

        self.menu_button.props.popover = None
        self.popover.set_parent(window)
        self.popover.props.has_arrow = False
        self.popover.props.halign = Gtk.Align.START

        rectangle = Gdk.Rectangle()
        rectangle.x, rectangle.y, rectangle.width, rectangle.height = x, y, 0, 0
        self.popover.props.pointing_to = rectangle

        self.popover.popup()

        def closed(*_args: Any) -> None:
            self.popover.unparent()
            self.popover.props.has_arrow = True
            self.popover.props.halign = Gtk.Align.FILL

            self.popover.props.pointing_to = None  # pyright: ignore[reportAttributeAccessIssue]
            self.menu_button.props.popover = self.popover

            self.popover.disconnect_by_func(closed)

        self.popover.connect("closed", closed)

    def build_menus(self, media_info: GstPlay.PlayMediaInfo) -> None:
        """Fill up the menu with subtitles and languages."""
        self.menus_building -= 1

        # Don't try to rebuild the menu multiple times
        # when the media info has many changes
        if self.menus_building > 1:
            return

        self.language_menu.remove_all()
        self.subtitles_menu.remove_all()

        langs = 0
        for index, stream in enumerate(media_info.get_audio_streams()):
            has_title, title = stream.get_tags().get_string("title")
            language = (
                stream.get_language()
                or ngettext(
                    # Translators: The variable is the number of channels
                    # in an audio track
                    "Undetermined, {} Channel",
                    "Undetermined, {} Channels",
                    channels,
                ).format(channels)
                if (channels := stream.get_channels()) > 0
                else _("Undetermined")
            )

            if (title is not None) and (title == language):
                title = None

            self.language_menu.append(
                f"{language}{(' - ' + title) if (has_title and title) else ''}",
                f"win.select-language(uint16 {index})",
            )
            langs += 1

        if not langs:
            self.language_menu.append(_("No Audio"), "nonexistent.action")
            # HACK: This is to make the item insensitive
            # I don't know if there is a better way to do this

        self.subtitles_menu.append(
            _("None"), f"win.select-subtitles(uint16 {GLib.MAXUINT16})"
        )

        subs = 0
        for index, stream in enumerate(media_info.get_subtitle_streams()):
            has_title, title = stream.get_tags().get_string("title")
            language = stream.get_language() or _("Undetermined Language")

            self.subtitles_menu.append(
                f"{language}{(' - ' + title) if (has_title and title) else ''}",
                f"win.select-subtitles(uint16 {index})",
            )
            subs += 1

        if not subs and (action := lookup_action(self.props.root, "select-subtitles")):
            action.activate(GLib.Variant.new_uint16(GLib.MAXUINT16))

        self.subtitles_menu.append(_("Add Subtitle File…"), "win.choose-subtitles")

    def _on_toggle_loop(self, action: Gio.SimpleAction, _state: GLib.Variant) -> None:
        value = not action.props.state.get_boolean()
        action.set_state(GLib.Variant.new_boolean(value))
        state_settings.set_boolean("looping", value)

    @Gtk.Template.Callback()
    def _rotate_left(self, *_args: Any) -> None:
        self.emit("rotate-left")

    @Gtk.Template.Callback()
    def _rotate_right(self, *_args: Any) -> None:
        self.emit("rotate-right")
