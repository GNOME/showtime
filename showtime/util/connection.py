# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 The Sushi authors

# Adapted from https://gitlab.gnome.org/GNOME/sushi/-/tree/main/src/util/connection.js

from collections.abc import Callable
from typing import Any

from gi.repository import GObject


class Connection:
    """A wrapper around a GObject signal connection that simplifies disconnect/cleanup."""

    def __init__(self, signal: str, fn: Callable[..., Any], object=None) -> None:
        """Define the signal and callback the connection should manage."""
        self._id = 0
        self._object = None
        self._signal = signal
        self._function = fn
        if object:
            self.connect(object)

    def connect(self, object: GObject.Object) -> None:
        """Create a connection to `object`, replacing any existing one."""
        if self._id != 0:
            self.disconnect()
        self._id = object.connect(self._signal, self._function)
        self._object = object

    def disconnect(self) -> None:
        if self._id != 0:
            if (object := self._object) is not None:
                object.disconnect(self._id)
            self._id = 0
        self._object = None
