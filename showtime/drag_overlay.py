# drag_overlay.py
#
# Copyright 2023 FineFindus
# Copyright 2023-2024 Sophie Herold
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
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
# SPDX-License-Identifier: GPL-3.0-or-later

# Taken from Loupe, rewritten in PyGObject
# https://gitlab.gnome.org/GNOME/loupe/-/blob/d66dd0f16bf45b3cd46e3a084409513eaa1c9af5/src/widgets/drag_overlay.rs

"""A widget that shows an overlay when dragging a video over the window."""
from typing import Any, Optional

from gi.repository import Adw, GObject, Gtk


class ShowtimeDragOverlay(Adw.Bin):
    """A widget that shows an overlay when dragging a video over the window."""

    __gtype_name__ = "ShowtimeDragOverlay"

    _drop_target: Optional[Gtk.DropTarget] = None

    overlay: Gtk.Overlay
    revealer: Gtk.Revealer

    @GObject.Property(type=Gtk.Widget)
    def child(self) -> Optional[Gtk.Widget]:
        """Usual content."""
        return self.overlay.get_child()

    @child.setter
    def child(self, child: Gtk.Widget) -> None:
        self.overlay.set_child(child)

    @GObject.Property(type=Gtk.Widget)
    def overlayed(self) -> Optional[Gtk.Widget]:
        """Widget overlayed when dragging over child."""
        return self.revealer.get_child()

    @overlayed.setter
    def overlayed(self, overlayed: Gtk.Widget) -> None:
        self.revealer.set_child(overlayed)

    @GObject.Property(type=Gtk.DropTarget)
    def drop_target(self) -> Gtk.DropTarget:
        """The drop target."""
        return self._drop_target

    @drop_target.setter
    def drop_target(self, drop_target: Gtk.DropTarget) -> None:
        self._drop_target = drop_target

        if not drop_target:
            return

        drop_target.connect(
            "notify::current-drop",
            lambda *_: self.revealer.set_reveal_child(
                bool(drop_target.get_current_drop())
            ),
        )

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.overlay = Gtk.Overlay()
        self.revealer = Gtk.Revealer()

        self.set_css_name("showtime-drag-overlay")

        self.overlay.set_parent(self)
        self.overlay.add_overlay(self.revealer)

        self.revealer.set_can_target(False)
        self.revealer.set_transition_type(Gtk.RevealerTransitionType.CROSSFADE)
        self.revealer.set_reveal_child(False)
