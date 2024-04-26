# utils.py

# Copyright 2024 kramo

# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

# SPDX-License-Identifier: GPL-3.0-or-later

"""Utilities used across the app."""
import logging
from typing import Optional

from gi.repository import Gdk, Graphene, Gtk


def screenshot(paintable: Gdk.Paintable, native: Gtk.Native) -> Optional[Gdk.Texture]:
    """Takes a screenshot of the current image of a `GdkPaintable`."""

    # Copied from Workbench
    # https://github.com/workbenchdev/Workbench/blob/1ebbe1e3915aabfd172c166c88ca23ad08861d15/src/Previewer/previewer.vala#L36

    paintable = paintable.get_current_image()

    width = paintable.get_intrinsic_width()
    height = paintable.get_intrinsic_height()
    snapshot = Gtk.Snapshot()
    paintable.snapshot(snapshot, width, height)

    if not (node := snapshot.to_node()):
        logging.warning(
            "Could not get node snapshot, width: %s, height: %s", width, height
        )
        return None

    rect = Graphene.Rect()
    rect.origin = Graphene.Point.zero()
    size = Graphene.Size()
    size.width = width
    size.height = height
    rect.size = size

    renderer = native.get_renderer()
    return renderer.render_texture(node, rect)
