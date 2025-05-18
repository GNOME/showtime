# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2023-2024 Sophie Herold
# SPDX-FileCopyrightText: Copyright 2023 FineFindus
# SPDX-FileCopyrightText: Copyright 2024-2025 kramo

# Taken from Loupe, rewritten in PyGObject
# https://gitlab.gnome.org/GNOME/loupe/-/blob/d66dd0f16bf45b3cd46e3a084409513eaa1c9af5/src/widgets/drag_overlay.rs

from typing import Any

from gi.repository import Adw, GObject, Gtk


class DragOverlay(Adw.Bin):
    """A widget that shows an overlay when dragging a video over the window."""

    __gtype_name__ = "DragOverlay"

    _drop_target: Gtk.DropTarget | None = None

    overlay: Gtk.Overlay
    revealer: Gtk.Revealer

    @GObject.Property(type=Gtk.Widget)
    def child(self) -> Gtk.Widget | None:
        """Usual content."""
        return self.overlay.props.child

    @child.setter
    def child(self, child: Gtk.Widget) -> None:
        self.overlay.props.child = child

    @GObject.Property(type=Gtk.Widget)
    def overlayed(self) -> Gtk.Widget | None:
        """Widget overlayed when dragging over child."""
        return self.revealer.props.child

    @overlayed.setter
    def overlayed(self, overlayed: Gtk.Widget) -> None:
        self.revealer.props.child = overlayed

    @GObject.Property(type=Gtk.DropTarget)
    def drop_target(self) -> Gtk.DropTarget | None:
        """Get the drop target."""
        return self._drop_target

    @drop_target.setter
    def drop_target(self, drop_target: Gtk.DropTarget) -> None:
        self._drop_target = drop_target

        if not drop_target:
            return

        drop_target.connect(
            "notify::current-drop",
            lambda *_: self.revealer.set_reveal_child(
                bool(drop_target.props.current_drop)
            ),
        )

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.overlay = Gtk.Overlay()
        self.revealer = Gtk.Revealer()

        self.set_css_name("showtime-drag-overlay")

        self.overlay.set_parent(self)
        self.overlay.add_overlay(self.revealer)

        self.revealer.props.can_target = False
        self.revealer.props.transition_type = Gtk.RevealerTransitionType.CROSSFADE
        self.revealer.props.reveal_child = False
