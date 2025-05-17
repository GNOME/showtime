# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2024-2025 kramo
# SPDX-FileCopyrightText: Copyright 2025 Jamie Gravendeel

from typing import Any

from gi.repository import Adw, GObject, Gtk

from showtime import PREFIX

HIGH_VOLUME = 0.7
MEDIUM_VOLUME = 0.3


@Gtk.Template.from_resource(f"{PREFIX}/gtk/sound-options.ui")
class SoundOptions(Adw.Bin):
    """A bin containing the volume menu button and its popover."""

    __gtype_name__ = "SoundOptions"

    menu_button: Gtk.MenuButton = Gtk.Template.Child()
    popover: Gtk.Popover = Gtk.Template.Child()
    adjustment: Gtk.Adjustment = Gtk.Template.Child()

    mute = GObject.Property(type=bool, default=True)
    volume = GObject.Property(type=float)

    schedule_volume_change = GObject.Signal(arg_types=(float,))

    @Gtk.Template.Callback()
    def _schedule_volume_change(self, adjustment: Gtk.Adjustment, _: Any) -> None:
        self.emit("schedule-volume-change", adjustment.props.value)

    @Gtk.Template.Callback()
    def _get_volume_icon(self, _obj: Any, mute: bool, volume: float) -> str:
        return (
            "audio-volume-muted-symbolic"
            if mute
            else "audio-volume-high-symbolic"
            if volume > HIGH_VOLUME
            else "audio-volume-medium-symbolic"
            if volume > MEDIUM_VOLUME
            else "audio-volume-low-symbolic"
        )
