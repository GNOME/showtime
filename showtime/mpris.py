# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2019 The GNOME Music developers
# SPDX-FileCopyrightText: Copyright 2024-2025 kramo

# A lot of the code is taken from GNOME Music
# https://gitlab.gnome.org/GNOME/gnome-music/-/blob/6a32efb74ff4107d1e4a288184e21c43f5dd877f/gnomemusic/mpris.py

import re
from functools import partial
from typing import Any

from gi.repository import (
    Gio,
    GLib,
    GstAudio,  # pyright: ignore[reportAttributeAccessIssue]
    GstPlay,  # pyright: ignore[reportAttributeAccessIssue]
    Gtk,
)

from showtime import APP_ID, PREFIX, logger
from showtime.utils import get_title
from showtime.widgets.window import Window

RATE_SLOW = 0.75
RATE_NORMAL = 1.125
RATE_FASTER = 1.375
RATE_FASTEST = 1.75

INTERFACE = """
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


class DBusInterface:
    """A D-Bus interface."""

    def __init__(self, name: str, path: str, _application: Any) -> None:
        """Etablish a D-Bus session connection.

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
            logger.warning("Unable to connect to the session bus: %s", e.message)
            return

        Gio.bus_own_name_on_connection(
            self._con, name, Gio.BusNameOwnerFlags.NONE, None, None
        )

        method_outargs = {}
        method_inargs = {}
        signals = {}
        for interface in Gio.DBusNodeInfo.new_for_xml(INTERFACE).interfaces:
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
        _connection: Gio.DBusConnection,
        _sender: str,
        _object_path: str,
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
                args[i] = fd_list.get(args[i])  # pyright: ignore[reportOptionalMemberAccess]

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
        """Convert `name` from camelCase to snake_case."""
        s1 = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", name)
        return "_" + re.sub("([a-z0-9])([A-Z])", r"\1_\2", s1).lower()


class MPRIS(DBusInterface):
    """An MRPIS implementation."""

    MEDIA_PLAYER2_IFACE = "org.mpris.MediaPlayer2"
    MEDIA_PLAYER2_PLAYER_IFACE = "org.mpris.MediaPlayer2.Player"

    @property
    def win(self) -> Window | None:  # pyright: ignore[reportAttributeAccessIssue]
        """Get the active application window."""
        return win if isinstance(win := self._app.get_active_window(), Window) else None

    @property
    def play(self) -> GstPlay.Play | None:
        """Play the video."""
        if not self.win:
            return None

        return getattr(self.win, "play", None)

    def __init__(self, app: Gtk.Application) -> None:
        name = f"org.mpris.MediaPlayer2.{APP_ID}"
        path = "/org/mpris/MediaPlayer2"
        super().__init__(name, path, app)

        self._app = app

        self._app.connect("state-changed", self._on_player_state_changed)
        self._app.connect("media-info-updated", self._on_media_info_updated)
        self._app.connect("notify::active-window", self._on_active_window_changed)
        self._app.connect("volume-changed", self._on_volume_changed)
        self._app.connect("rate-changed", self._on_rate_changed)
        self._app.connect("seeked", self._on_seeked)

    def _get_playback_status(self) -> str:
        if (not self.win) or self.win.stopped:
            return "Stopped"

        if self.win.paused:
            return "Paused"

        return "Playing"

    def _get_metadata(self) -> dict:
        if (not self.play) or (not (media_info := self.play.get_media_info())):
            return {
                "mpris:trackid": GLib.Variant("o", f"{PREFIX}/TrackList/CurrentTrack")
            }

        return {
            "xesam:url": GLib.Variant("s", media_info.get_uri()),
            "mpris:length": GLib.Variant("x", int(self.play.get_duration() / 1e3)),
            "xesam:title": GLib.Variant(
                "s", get_title(media_info) or _("Unknown Title")
            ),
        }

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
        playback_status = self._get_playback_status()
        can_play = (self.play.get_uri() is not None) if self.play else False
        self._properties_changed(
            MPRIS.MEDIA_PLAYER2_PLAYER_IFACE,
            {
                "PlaybackStatus": GLib.Variant("s", playback_status),
                "Metadata": GLib.Variant("a{sv}", self._get_metadata()),
                "CanPlay": GLib.Variant("b", can_play),
                "CanPause": GLib.Variant("b", can_play),
            },
            [],
        )

    def _on_volume_changed(self, *_args: Any) -> None:
        if not self.win:
            return

        volume = self.win.pipeline.get_volume(GstAudio.StreamVolumeFormat.CUBIC)  # pyright: ignore[reportAttributeAccessIssue]

        self._properties_changed(
            MPRIS.MEDIA_PLAYER2_PLAYER_IFACE,
            {
                "Volume": GLib.Variant("d", volume),
            },
            [],
        )

    def _on_rate_changed(self, *_args: Any) -> None:
        if not self.play:
            return

        self._properties_changed(
            MPRIS.MEDIA_PLAYER2_PLAYER_IFACE,
            {
                "Rate": GLib.Variant("d", self.play.props.rate),
            },
            [],
        )

    def _on_seeked(self, *_args: Any) -> None:
        position_usecond = int(self.play.get_position() / 1e3) if self.play else 0

        self._dbus_emit_signal(
            "Seeked",
            {
                "Position": position_usecond,
            },
        )

    def _raise(self) -> None:
        """Brings user interface to the front (MPRIS Method)."""
        if not self.win:
            return

        self.win.present()

    def _quit(self) -> None:
        """Causes the media player to stop running (MPRIS Method)."""
        self._app.quit()

    def _next(self) -> None:
        """Skips to the next track in the tracklist (MPRIS Method)."""

    def _previous(self) -> None:
        """Skips to the previous track in the tracklist.

        (MPRIS Method)
        """

    def _pause(self) -> None:
        """Pauses playback (MPRIS Method)."""
        if not self.win:
            return

        self.win.pause()

    def _play_pause(self) -> None:
        """Play or Pauses playback (MPRIS Method)."""
        if not self.win:
            return

        self.win.unpause() if self.win.paused else self.win.pause()

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

    def _seek(self, offset_usecond: int) -> None:
        """Seek forward in the current track (MPRIS Method).

        Seek is relative to the current player position.
        If the value passed in would mean seeking beyond the end of the track,
        acts like a call to Next.

        :param int offset_usecond: number of microseconds
        """
        if not self.play:
            return

        self.play.seek(max(0, self.play.get_position() + (offset_usecond * 1e3)))

    def _set_position(self, _track_id: str, position_usecond: int) -> None:
        """Set the current track position in microseconds (MPRIS Method).

        :param str track_id: The currently playing track's identifier
        :param int position_usecond: new position in microseconds
        """
        if not self.play:
            return

        self.play.seek(position_usecond * 1e3)

    def _open_uri(self, _uri: str) -> None:
        """Open the Uri given as an argument (MPRIS Method).

        Not implemented.

        :param str uri: Uri of the track to load.
        """

    def _get(self, iface: str, prop: str) -> GLib.Variant | None:
        # Some clients (for example GSConnect) try to access the volume
        # property. This results in a crash at startup.
        # Return nothing to prevent it.
        try:
            return all_props[prop] if (all_props := self._get_all(iface)) else None
        except KeyError as error:
            msg = f"MPRIS does not handle {prop} property from {iface} interface"
            logger.warning(msg)
            raise ValueError(msg) from error

    def _get_all(self, interface_name: str) -> dict | None:
        if interface_name == MPRIS.MEDIA_PLAYER2_IFACE:
            return {
                "CanQuit": GLib.Variant("b", True),
                "Fullscreen": GLib.Variant("b", False),
                "CanSetFullscreen": GLib.Variant("b", False),
                "CanRaise": GLib.Variant("b", False),
                "HasTrackList": GLib.Variant("b", False),
                "Identity": GLib.Variant("s", "Video Player"),
                "DesktopEntry": GLib.Variant("s", APP_ID),
                "SupportedUriSchemes": GLib.Variant("as", ["file"]),
                "SupportedMimeTypes": GLib.Variant("as", []),
            }

        if interface_name == MPRIS.MEDIA_PLAYER2_PLAYER_IFACE:
            position_usecond = int(self.play.get_position() / 1e3) if self.play else 0
            volume = self.play.get_volume() if self.play else 0.0
            can_play = (self.play.get_uri() is not None) if self.play else False
            return {
                "PlaybackStatus": GLib.Variant("s", self._get_playback_status()),
                "LoopStatus": GLib.Variant("s", "None"),
                "Rate": GLib.Variant("d", self.play.props.rate if self.play else 0.0),
                "Shuffle": GLib.Variant("b", False),
                "Metadata": GLib.Variant("a{sv}", self._get_metadata()),
                "Volume": GLib.Variant("d", volume),
                "Position": GLib.Variant("x", position_usecond),
                "MinimumRate": GLib.Variant("d", 0.5),
                "MaximumRate": GLib.Variant("d", 2.0),
                "CanGoNext": GLib.Variant("b", False),
                "CanGoPrevious": GLib.Variant("b", False),
                "CanPlay": GLib.Variant("b", can_play),
                "CanPause": GLib.Variant("b", can_play),
                "CanSeek": GLib.Variant("b", True),
                "CanControl": GLib.Variant("b", True),
            }

        if interface_name in (
            "org.freedesktop.DBus.Properties",
            "org.freedesktop.DBus.Introspectable",
        ):
            return {}

        logger.warning("MPRIS does not implement %s interface", interface_name)
        return None

    def _set(self, interface_name: str, property_name: str, value: Any) -> None:
        if interface_name != MPRIS.MEDIA_PLAYER2_PLAYER_IFACE:
            logger.warning("MPRIS does not implement %s interface", interface_name)
            return

        if not self.win:
            return

        match property_name:
            case "Rate":
                self.win.rate = (
                    "0.5"
                    if value < RATE_SLOW
                    else "1.0"
                    if value < RATE_NORMAL
                    else "1.25"
                    if value < RATE_FASTER
                    else "1.5"
                    if value < RATE_FASTEST
                    else "2.0"
                )
            case "Volume":
                GLib.idle_add(
                    partial(
                        self.win.pipeline.set_volume,  # pyright: ignore[reportAttributeAccessIssue]
                        GstAudio.StreamVolumeFormat.CUBIC,
                        value,
                    )
                )
            case "LoopStatus":
                pass
            case "Shuffle":
                pass

    def _properties_changed(
        self,
        interface_name: str,
        changed_properties: dict,
        invalidated_properties: list,
    ) -> None:
        self._dbus_emit_signal(
            "PropertiesChanged",
            {
                "interface_name": interface_name,
                "changed_properties": changed_properties,
                "invalidated_properties": invalidated_properties,
            },
        )

    def _introspect(self) -> str | None:
        return INTERFACE
