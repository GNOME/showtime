# mpris.py
#
# Copyright 2019 The GNOME Music developers
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

# A lot of the code is taken from GNOME Music
# https://gitlab.gnome.org/GNOME/gnome-music/-/blob/6a32efb74ff4107d1e4a288184e21c43f5dd877f/gnomemusic/mpris.py

import logging
import re
from typing import Any, Optional

from gi.repository import Gio, GLib, GstPlay

from showtime import shared
from showtime.utils import get_title
from showtime.window import ShowtimeWindow


class DBusInterface:
    def __init__(self, name: str, path: str, _application: Any) -> None:
        """Etablish a D-Bus session connection

        :param str name: interface name
        :param str path: object path
        :param GtkApplication application: The Application object
        """
        self._path = path
        self._signals = None
        Gio.bus_get(Gio.BusType.SESSION, None, self._bus_get_sync, name)

    def _bus_get_sync(self, _source: Any, res: Gio.AsyncResult, name: str) -> None:
        try:
            self._con = Gio.bus_get_finish(res)
        except GLib.Error as e:
            logging.warning("Unable to connect to to session bus: %s", e.message)
            return

        Gio.bus_own_name_on_connection(
            self._con, name, Gio.BusNameOwnerFlags.NONE, None, None
        )

        method_outargs = {}
        method_inargs = {}
        signals = {}
        for interface in Gio.DBusNodeInfo.new_for_xml(self.__doc__).interfaces:
            for method in interface.methods:
                method_outargs[method.name] = (
                    "(" + "".join([arg.signature for arg in method.out_args]) + ")"
                )
                method_inargs[method.name] = tuple(
                    arg.signature for arg in method.in_args
                )

            for signal in interface.signals:
                args = {arg.name: arg.signature for arg in signal.args}
                signals[signal.name] = {"interface": interface.name, "args": args}

            self._con.register_object(
                object_path=self._path,
                interface_info=interface,
                method_call_closure=self._on_method_call,
                get_property_closure=None,
                set_property_closure=None,
            )

        self._method_inargs = method_inargs
        self._method_outargs = method_outargs
        self._signals = signals

    def _on_method_call(
        self,
        connection: Gio.DBusConnection,
        sender: str,
        object_path: str,
        interface_name: str,
        method_name: str,
        parameters: GLib.Variant,
        invocation: Gio.DBusMethodInvocation,
    ) -> None:
        """GObject.Closure to handle incoming method calls.

        :param Gio.DBusConnection connection: D-Bus connection
        :param str sender: bus name that invoked the method
        :param srt object_path: object path the method was invoked on
        :param str interface_name: name of the D-Bus interface
        :param str method_name: name of the method that was invoked
        :param GLib.Variant parameters: parameters of the method invocation
        :param Gio.DBusMethodInvocation invocation: invocation
        """
        args = list(parameters.unpack())
        for i, sig in enumerate(self._method_inargs[method_name]):
            if sig == "h":
                msg = invocation.get_message()
                fd_list = msg.get_unix_fd_list()
                args[i] = fd_list.get(args[i])

        method_snake_name = DBusInterface.camelcase_to_snake_case(method_name)
        try:
            result = getattr(self, method_snake_name)(*args)
        except ValueError as e:
            invocation.return_dbus_error(interface_name, str(e))
            return

        # out_args is at least (signature1). We therefore always wrap the
        # result as a tuple.
        # Reference:
        # https://bugzilla.gnome.org/show_bug.cgi?id=765603
        result = (result,)

        out_args = self._method_outargs[method_name]
        if out_args != "()":
            variant = GLib.Variant(out_args, result)
            invocation.return_value(variant)
        else:
            invocation.return_value(None)

    def _dbus_emit_signal(self, signal_name: str, values: dict) -> None:
        if self._signals is None:
            return

        signal = self._signals[signal_name]
        parameters = []
        for arg_name, arg_signature in signal["args"].items():
            value = values[arg_name]
            parameters.append(GLib.Variant(arg_signature, value))

        variant = GLib.Variant.new_tuple(*parameters)
        self._con.emit_signal(
            None, self._path, signal["interface"], signal_name, variant
        )

    @staticmethod
    def camelcase_to_snake_case(name: str) -> str:
        s1 = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", name)
        return "_" + re.sub("([a-z0-9])([A-Z])", r"\1_\2", s1).lower()


class MPRIS(DBusInterface):
    """
    <!DOCTYPE node PUBLIC
    '-//freedesktop//DTD D-BUS Object Introspection 1.0//EN'
    'http://www.freedesktop.org/standards/dbus/1.0/introspect.dtd'>
    <node>
        <interface name='org.freedesktop.DBus.Introspectable'>
            <method name='Introspect'>
                <arg name='data' direction='out' type='s'/>
            </method>
        </interface>
        <interface name='org.freedesktop.DBus.Properties'>
            <method name='Get'>
                <arg name='interface' direction='in' type='s'/>
                <arg name='property' direction='in' type='s'/>
                <arg name='value' direction='out' type='v'/>
            </method>
            <method name='Set'>
                <arg name='interface_name' direction='in' type='s'/>
                <arg name='property_name' direction='in' type='s'/>
                <arg name='value' direction='in' type='v'/>
            </method>
            <method name='GetAll'>
                <arg name='interface' direction='in' type='s'/>
                <arg name='properties' direction='out' type='a{sv}'/>
            </method>
            <signal name='PropertiesChanged'>
                <arg name='interface_name' type='s' />
                <arg name='changed_properties' type='a{sv}' />
                <arg name='invalidated_properties' type='as' />
            </signal>
        </interface>
        <interface name='org.mpris.MediaPlayer2'>
            <method name='Raise'>
            </method>
            <method name='Quit'>
            </method>
            <property name='CanQuit' type='b' access='read' />
            <property name='Fullscreen' type='b' access='readwrite' />
            <property name='CanRaise' type='b' access='read' />
            <property name='HasTrackList' type='b' access='read'/>
            <property name='Identity' type='s' access='read'/>
            <property name='DesktopEntry' type='s' access='read'/>
            <property name='SupportedUriSchemes' type='as' access='read'/>
            <property name='SupportedMimeTypes' type='as' access='read'/>
        </interface>
        <interface name='org.mpris.MediaPlayer2.Player'>
            <method name='Next'/>
            <method name='Previous'/>
            <method name='Pause'/>
            <method name='PlayPause'/>
            <method name='Stop'/>
            <method name='Play'/>
            <method name='Seek'>
                <arg direction='in' name='Offset' type='x'/>
            </method>
            <method name='SetPosition'>
                <arg direction='in' name='TrackId' type='o'/>
                <arg direction='in' name='Position' type='x'/>
            </method>
            <method name='OpenUri'>
                <arg direction='in' name='Uri' type='s'/>
            </method>
            <signal name='Seeked'>
                <arg name='Position' type='x'/>
            </signal>
            <property name='PlaybackStatus' type='s' access='read'/>
            <property name='LoopStatus' type='s' access='readwrite'/>
            <property name='Rate' type='d' access='readwrite'/>
            <property name='Shuffle' type='b' access='readwrite'/>
            <property name='Metadata' type='a{sv}' access='read'>
            </property>
            <property name='Position' type='x' access='read'/>
            <property name='MinimumRate' type='d' access='read'/>
            <property name='MaximumRate' type='d' access='read'/>
            <property name='CanGoNext' type='b' access='read'/>
            <property name='CanGoPrevious' type='b' access='read'/>
            <property name='CanPlay' type='b' access='read'/>
            <property name='CanPause' type='b' access='read'/>
            <property name='CanSeek' type='b' access='read'/>
            <property name='CanControl' type='b' access='read'/>
        </interface>
    </node>
    """

    MEDIA_PLAYER2_IFACE = "org.mpris.MediaPlayer2"
    MEDIA_PLAYER2_PLAYER_IFACE = "org.mpris.MediaPlayer2.Player"

    @property
    def win(self) -> Optional[ShowtimeWindow]:
        return self._app.get_active_window()

    @property
    def play(self) -> Optional[GstPlay.Play]:
        if not self.win:
            return None

        return getattr(self.win, "play", None)

    def __init__(self, app) -> None:
        name = f"org.mpris.MediaPlayer2.{shared.APP_ID}"
        path = "/org/mpris/MediaPlayer2"
        super().__init__(name, path, app)

        self._app = app

        self._app.connect("state-changed", self._on_player_state_changed)
        self._app.connect("media-info-updated", self._on_media_info_updated)
        self._app.connect("notify::active-window", self._on_active_window_changed)

    def _get_playback_status(self) -> str:
        if (not self.win) or self.win.stopped:
            return "Stopped"

        if self.win.paused:
            return "Paused"

        return "Playing"

    def _get_metadata(self) -> dict:
        if (not self.play) or (not (media_info := self.play.get_media_info())):
            return {
                "mpris:trackid": GLib.Variant(
                    "o", f"{shared.PREFIX}/TrackList/CurrentTrack"
                )
            }

        length = int(self.play.get_duration() / 1000)

        metadata = {
            "xesam:url": GLib.Variant("s", media_info.get_uri()),
            "mpris:length": GLib.Variant("x", length),
            "xesam:title": GLib.Variant(
                "s", get_title(media_info) or _("Unknown Title")
            ),
        }

        return metadata

    def _on_player_state_changed(self, *_args: Any) -> None:
        playback_status = self._get_playback_status()

        self._properties_changed(
            MPRIS.MEDIA_PLAYER2_PLAYER_IFACE,
            {
                "PlaybackStatus": GLib.Variant("s", playback_status),
            },
            [],
        )

    def _on_media_info_updated(self, *_args: Any) -> None:
        self._properties_changed(
            MPRIS.MEDIA_PLAYER2_PLAYER_IFACE,
            {
                "CanPlay": GLib.Variant("b", True),
                "CanPause": GLib.Variant("b", True),
                "Metadata": GLib.Variant("a{sv}", self._get_metadata()),
            },
            [],
        )

    def _on_active_window_changed(self, *_args: Any) -> None:
        position_msecond = int(self.play.get_position() / 1000) if self.play else 0
        playback_status = self._get_playback_status()
        can_play = (self.play.get_uri() is not None) if self.play else False
        self._properties_changed(
            MPRIS.MEDIA_PLAYER2_PLAYER_IFACE,
            {
                "PlaybackStatus": GLib.Variant("s", playback_status),
                "Metadata": GLib.Variant("a{sv}", self._get_metadata()),
                "Position": GLib.Variant("x", position_msecond),
                "CanPlay": GLib.Variant("b", can_play),
                "CanPause": GLib.Variant("b", can_play),
            },
            [],
        )

    def _raise(self) -> None:
        """Brings user interface to the front (MPRIS Method)."""
        ...

    def _quit(self) -> None:
        """Causes the media player to stop running (MPRIS Method)."""
        self._app.quit()

    def _next(self) -> None:
        """Skips to the next track in the tracklist (MPRIS Method)."""
        ...

    def _previous(self) -> None:
        """Skips to the previous track in the tracklist.

        (MPRIS Method)
        """
        ...

    def _pause(self) -> None:
        """Pauses playback (MPRIS Method)."""
        if not self.win:
            return

        self.win.pause()

    def _play_pause(self) -> None:
        """Play or Pauses playback (MPRIS Method)."""
        if not self.win:
            return

        self.win.toggle_playback()

    def _stop(self) -> None:
        """Stop playback (MPRIS Method)."""
        if (not self.win) or (not self.play):
            return

        self.win.pause()
        self.play.seek(0)

    def _play(self) -> None:
        """Start or resume playback (MPRIS Method).

        If there is no track to play, this has no effect.
        """
        if not self.win:
            return

        self.win.unpause()

    def _seek(self, _offset_msecond: int) -> None:
        """Seek forward in the current track (MPRIS Method).

        Seek is relative to the current player position.
        If the value passed in would mean seeking beyond the end of the track,
        acts like a call to Next.

        :param int offset_msecond: number of microseconds
        """
        ...

    def _set_position(self, _track_id: str, _position_msecond: int) -> None:
        """Set the current track position in microseconds (MPRIS Method)

        :param str track_id: The currently playing track's identifier
        :param int position_msecond: new position in microseconds
        """
        ...

    def _open_uri(self, _uri: str) -> None:
        """Opens the Uri given as an argument (MPRIS Method).

        Not implemented.

        :param str uri: Uri of the track to load.
        """
        ...

    def _get(self, interface_name: str, property_name: str) -> dict:
        # Some clients (for example GSConnect) try to access the volume
        # property. This results in a crash at startup.
        # Return nothing to prevent it.
        try:
            return self._get_all(interface_name)[property_name]
        except KeyError:
            msg = "MPRIS does not handle {} property from {} interface".format(
                property_name, interface_name
            )
            logging.warning(msg)
            raise ValueError(msg)

    def _get_all(self, interface_name: str) -> dict:
        if interface_name == MPRIS.MEDIA_PLAYER2_IFACE:
            application_id = self._app.props.application_id
            return {
                "CanQuit": GLib.Variant("b", True),
                "Fullscreen": GLib.Variant("b", False),
                "CanSetFullscreen": GLib.Variant("b", False),
                "CanRaise": GLib.Variant("b", False),
                "HasTrackList": GLib.Variant("b", False),
                "Identity": GLib.Variant("s", "Showtime"),
                "DesktopEntry": GLib.Variant("s", shared.APP_ID),
                "SupportedUriSchemes": GLib.Variant("as", ["file"]),
                "SupportedMimeTypes": GLib.Variant(
                    "as",
                    [],
                ),
            }
        elif interface_name == MPRIS.MEDIA_PLAYER2_PLAYER_IFACE:
            position_msecond = int(self.play.get_position() / 1000) if self.play else 0
            playback_status = self._get_playback_status()
            can_play = (self.play.get_uri() is not None) if self.play else False
            return {
                "PlaybackStatus": GLib.Variant("s", playback_status),
                "LoopStatus": GLib.Variant("s", "None"),
                "Rate": GLib.Variant("d", 1.0),
                "Shuffle": GLib.Variant("b", False),
                "Metadata": GLib.Variant("a{sv}", self._get_metadata()),
                "Position": GLib.Variant("x", position_msecond),
                "MinimumRate": GLib.Variant("d", 1.0),
                "MaximumRate": GLib.Variant("d", 1.0),
                "CanGoNext": GLib.Variant("b", False),
                "CanGoPrevious": GLib.Variant("b", False),
                "CanPlay": GLib.Variant("b", can_play),
                "CanPause": GLib.Variant("b", can_play),
                "CanSeek": GLib.Variant("b", False),
                "CanControl": GLib.Variant("b", True),
            }
        elif interface_name == "org.freedesktop.DBus.Properties":
            return {}
        elif interface_name == "org.freedesktop.DBus.Introspectable":
            return {}
        else:
            logging.warning("MPRIS does not implement %s interface", interface_name)

    def _set(self, interface_name: str, property_name: str, _new_value: Any) -> None:
        if interface_name == MPRIS.MEDIA_PLAYER2_IFACE:
            if property_name == "Fullscreen":
                pass
        elif interface_name == MPRIS.MEDIA_PLAYER2_PLAYER_IFACE:
            if property_name in ["Rate", "Volume"]:
                pass
            elif property_name == "LoopStatus":
                pass
            elif property_name == "Shuffle":
                pass
        else:
            logging.warning("MPRIS does not implement %s interface", interface_name)

    def _properties_changed(
        self,
        interface_name: str,
        changed_properties: dict,
        invalidated_properties: list,
    ) -> None:
        parameters = {
            "interface_name": interface_name,
            "changed_properties": changed_properties,
            "invalidated_properties": invalidated_properties,
        }
        self._dbus_emit_signal("PropertiesChanged", parameters)

    def _introspect(self) -> str:
        return self.__doc__
