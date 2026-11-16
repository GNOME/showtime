# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 The Sushi authors

# Adapted from https://gitlab.gnome.org/GNOME/sushi/-/tree/main/src/util/source.js

from collections.abc import Callable

from gi.repository import GLib


class SourceId:
    """A wrapper around a GLib source ID that simplifies removing/replacing the source."""

    def __init__(self) -> None:
        self._id = 0

    @property
    def added(self) -> bool:
        return self._id != 0

    def add_timeout(
        self,
        priority: int,
        interval: int,
        fn: Callable[[], None],
        repeated: bool = False,
    ) -> None:
        """Replace the current source with one created using `GLib.timeout_add`.

        Unless `repeated` is set, the source is removed after one invocation.
        """

        def wrapper() -> bool:
            fn()
            if not repeated:
                self._id = 0
                return GLib.SOURCE_REMOVE
            return GLib.SOURCE_CONTINUE

        self._replace(GLib.timeout_add(interval, wrapper, priority=priority))

    def ensure_timeout(
        self,
        priority: int,
        interval: int,
        fn: Callable[[], None],
        repeated: bool = False,
    ) -> None:
        """Add a timeout if one is not already set. See `add_timeout`."""
        if self._id == 0:
            self.add_timeout(priority, interval, fn, repeated)

    def _replace(self, source_id: int) -> None:
        self.remove()
        self._id = source_id

    def remove(self) -> None:
        if self._id != 0:
            GLib.source_remove(self._id)
            self._id = 0
