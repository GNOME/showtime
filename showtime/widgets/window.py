# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2024-2025 kramo

import json
from collections.abc import Callable, Sequence
from functools import partial
from hashlib import sha256
from math import sqrt
from pathlib import Path
from time import time
from typing import TYPE_CHECKING, Any, cast

from gi.repository import (
    Adw,
    Gdk,
    Gio,
    GLib,
    GObject,
    Gst,
    GstAudio,  # pyright: ignore[reportAttributeAccessIssue]
    GstPbutils,
    GstPlay,  # pyright: ignore[reportAttributeAccessIssue]
    Gtk,
)

import showtime
from showtime import (
    APP_ID,
    PREFIX,
    PROFILE,
    VERSION,
    log_file,
    logger,
    state_settings,
    system,
)
from showtime.play import Messenger, gst_play_setup
from showtime.utils import (
    get_title,
    lookup_action,
    nanoseconds_to_timestamp,
    screenshot,
)

from .drag_overlay import DragOverlay
from .options import Options
from .sound_options import SoundOptions

if TYPE_CHECKING:
    from showtime.main import Application

# For large enough monitors, occupy 40% of the screen area
# when opening a window with a video
DEFAULT_OCCUPY_SCREEN = 0.4

# Screens with this resolution or smaller are handled as small
SMALL_SCREEN_AREA = 1280 * 1024

# For small monitors, occupy 80% of the screen area
SMALL_OCCUPY_SCREEN = 0.8

SMALL_SIZE_CHANGE = 10

# So that seeking isn't too rough
SCALE_MULT = 500

MINUTE_IN_NS = 6e10


@Gtk.Template.from_resource(f"{PREFIX}/gtk/window.ui")
class Window(Adw.ApplicationWindow):
    """The main application window."""

    __gtype_name__ = "Window"

    drag_overlay: DragOverlay = Gtk.Template.Child()
    toast_overlay: Adw.ToastOverlay = Gtk.Template.Child()
    stack: Gtk.Stack = Gtk.Template.Child()

    placeholder_page: Adw.ToolbarView = Gtk.Template.Child()
    placeholder_stack: Gtk.Stack = Gtk.Template.Child()
    placeholder_primary_menu_button: Gtk.MenuButton = Gtk.Template.Child()
    error_status_page: Adw.StatusPage = Gtk.Template.Child()
    missing_plugin_status_page: Adw.StatusPage = Gtk.Template.Child()

    video_page: Gtk.WindowHandle = Gtk.Template.Child()
    overlay_motion: Gtk.EventControllerMotion = Gtk.Template.Child()
    picture: Gtk.Picture = Gtk.Template.Child()

    header_handle_start: Gtk.WindowHandle = Gtk.Template.Child()
    header_handle_end: Gtk.WindowHandle = Gtk.Template.Child()
    header_start: Gtk.Box = Gtk.Template.Child()
    header_end: Gtk.Box = Gtk.Template.Child()
    video_primary_menu_button: Gtk.MenuButton = Gtk.Template.Child()

    toolbar_clamp: Adw.Clamp = Gtk.Template.Child()
    controls_box: Gtk.Box = Gtk.Template.Child()
    bottom_overlay_box: Gtk.Box = Gtk.Template.Child()

    title_label: Gtk.Label = Gtk.Template.Child()
    play_button: Gtk.Button = Gtk.Template.Child()
    position_label: Gtk.Label = Gtk.Template.Child()
    seek_scale: Gtk.Scale = Gtk.Template.Child()
    timestamp_box: Gtk.Box = Gtk.Template.Child()
    end_timestamp_button: Gtk.Button = Gtk.Template.Child()

    sound_options: SoundOptions = Gtk.Template.Child()

    options: Options = Gtk.Template.Child()

    spinner: Adw.Spinner = Gtk.Template.Child()  # pyright: ignore[reportAttributeAccessIssue]
    restore_breakpoint_bin: Adw.BreakpointBin = Gtk.Template.Child()
    restore_box: Gtk.Box = Gtk.Template.Child()

    open_video_dialog: Gtk.FileDialog = Gtk.Template.Child()
    choose_subtitles_dialog: Gtk.FileDialog = Gtk.Template.Child()

    overlay_motions: set[Gtk.EventControllerMotion]
    overlay_menu_buttons: set[Gtk.MenuButton]

    stopped: bool = True
    buffering: bool = False

    volume = GObject.Property(type=float)

    media_info_updated = GObject.Signal(name="media-info-updated")
    volume_changed = GObject.Signal(name="volume-changed")
    rate_changed = GObject.Signal(name="rate-changed")
    seeked = GObject.Signal(name="seeked")

    _reveal_animations: dict[Gtk.Widget, Adw.Animation]
    _hide_animations: dict[Gtk.Widget, Adw.Animation]

    _playing_gfile: Gio.File | None = None

    _last_reveal: float = 0.0
    _last_seek: float = 0.0

    _paused: bool = True
    _seeking: bool = False
    _seek_paused: bool = False
    _prev_motion_xy: tuple = (0, 0)
    _prev_volume = -1
    _toplevel_focused: bool = False

    @GObject.Property(type=bool, default=False)
    def mute(self) -> bool:
        """Get the mute state."""
        return self.play.props.mute

    @mute.setter
    def mute(self, mute: bool) -> None:
        self.play.props.mute = mute

    @GObject.Property(type=str)
    def rate(self) -> str:
        """Get the playback rate."""
        return str(self.play.props.rate)

    @rate.setter
    def rate(self, rate: str) -> None:
        self.play.props.rate = float(rate)
        self.options.popover.popdown()
        self.emit("rate-changed")

    @GObject.Property(type=bool, default=True)
    def paused(self) -> bool:
        """Whether the video is currently paused."""
        return self._paused

    @paused.setter
    def paused(self, paused: bool) -> None:
        self.stopped = self.stopped and paused

        if self._paused == paused:
            return

        self._paused = paused

        self.play_button.update_property(
            (Gtk.AccessibleProperty.LABEL,),
            (_("Play") if paused else _("Pause"),),
        )
        self.play_button.props.icon_name = (
            "media-playback-start-symbolic"
            if paused
            else "media-playback-pause-symbolic"
        )

        if not (app := self.props.application):
            return

        (app.uninhibit_win if paused else app.inhibit_win)(self)  # pyright: ignore[reportAttributeAccessIssue]

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(decorated=system != "Darwin", **kwargs)

        Gtk.WindowGroup().add_window(self)

        self._reveal_animations = {}
        self._hide_animations = {}

        if system == "Darwin":
            self.header_start.props.visible = False

        (
            self.paintable,
            self.play,
            self.pipeline,
            self.sink,
        ) = gst_play_setup(self.picture)

        self.paintable.connect("invalidate-size", self._on_paintable_invalidate_size)

        messenger = Messenger(self.play, self.pipeline)
        messenger.connect("state-changed", self._on_playback_state_changed)
        messenger.connect("duration-changed", self._on_duration_changed)
        messenger.connect("position-updated", self._on_position_updated)
        messenger.connect("seek-done", self._on_seek_done)
        messenger.connect("media-info-updated", self._on_media_info_updated)
        messenger.connect("volume-changed", self._on_volume_changed)
        messenger.connect("end-of-stream", self._on_end_of_stream)
        messenger.connect("warning", self._on_warning)
        messenger.connect("error", self._on_error)
        messenger.connect("missing-plugin", self._on_missing_plugin)

        if PROFILE == "development":
            self.add_css_class("devel")

        # Unfullscreen on Escape

        (esc := Gtk.ShortcutController()).add_shortcut(
            Gtk.Shortcut.new(
                Gtk.ShortcutTrigger.parse_string("Escape"),
                Gtk.CallbackAction.new(lambda *_: bool(self.unfullscreen())),
            )
        )
        self.add_controller(esc)

        self.overlay_motions = set()
        for widget in (
            self.controls_box,
            self.bottom_overlay_box,
            self.header_start,
            self.header_end,
            self.restore_box,
        ):
            widget.add_controller(motion := Gtk.EventControllerMotion())
            self.overlay_motions.add(motion)

        self.overlay_widgets = {
            self.toolbar_clamp,
            self.header_handle_start,
            self.header_handle_end,
        }

        self.overlay_menu_buttons = {
            self.video_primary_menu_button,
            self.options.menu_button,
            self.sound_options.menu_button,
        }

        state_settings.connect(
            "changed::end-timestamp-type",
            self._on_end_timestamp_type_changed,
        )

        # Force playback controls and progress bar to be Left-to-Right
        for widget in (
            self.controls_box,
            self.seek_scale,
            self.timestamp_box,
            self.position_label,
            self.end_timestamp_button,
        ):
            widget.set_direction(Gtk.TextDirection.LTR)

        self._create_actions()

    def do_size_allocate(self, width: int, height: int, baseline: int) -> None:
        """Call to set the allocation, if the widget does not have a layout manager."""
        Adw.ApplicationWindow.do_size_allocate(self, width, height, baseline)

        self.sink.props.window_width = self.get_width() * self.props.scale_factor  # pyright: ignore[reportAttributeAccessIssue]
        self.sink.props.window_height = self.get_height() * self.props.scale_factor  # pyright: ignore[reportAttributeAccessIssue]

    def play_video(self, gfile: Gio.File) -> None:
        """Start playing the given `GFile`."""
        if not (app := self.props.application):
            return

        app.save_play_position(self)  # pyright: ignore[reportAttributeAccessIssue]

        self._playing_gfile = gfile

        try:
            file_info = gfile.query_info(
                f"{Gio.FILE_ATTRIBUTE_STANDARD_IS_SYMLINK},{Gio.FILE_ATTRIBUTE_STANDARD_SYMLINK_TARGET}",
                Gio.FileQueryInfoFlags.NOFOLLOW_SYMLINKS,
            )
        except GLib.Error:
            uri = gfile.get_uri()
        else:
            if file_info.get_is_symlink() and (
                target := file_info.get_symlink_target()
            ):
                uri = Gio.File.new_for_path(target).get_uri()
            else:
                uri = gfile.get_uri()

        logger.debug("Playing video: %s", uri)

        def setup_cb(*_args: Any) -> None:
            self.pipeline.disconnect_by_func(setup_cb)

            if not (pos := self._get_previous_play_position()):
                self.unpause()
                logger.debug("No previous play position")
                return

            if pos < MINUTE_IN_NS:
                self.unpause()
                logger.debug("Previous play position before 60s")
                return

            self._reveal_overlay(self.restore_breakpoint_bin)
            self._hide_overlay(self.controls_box)
            self.play.seek(pos)
            logger.debug("Previous play position restored: %i", pos)

        self.pipeline.connect("source-setup", setup_cb)

        self.media_info_updated = False
        self.stack.props.visible_child = self.video_page
        self.placeholder_stack.props.visible_child = self.error_status_page
        self.select_subtitles(0)
        self.rate = "1.0"

        self.play.props.uri = uri
        self.pause()
        self._on_motion()

        if action := lookup_action(self, "screenshot"):
            action.props.enabled = True

        if action := lookup_action(self, "show-in-files"):
            action.props.enabled = True

    def unpause(self) -> None:
        """Start playing the current video."""
        self._hide_overlay(self.restore_breakpoint_bin)
        self._reveal_overlay(self.controls_box)
        self.play.play()
        logger.debug("Video unpaused")

    def pause(self, *_args: Any) -> None:
        """Pause the currently playing video."""
        self.play.pause()
        logger.debug("Video paused")

    def select_subtitles(self, index: int) -> None:
        """Select subtitles for the given index."""
        if action := lookup_action(self, "select-subtitles"):
            action.activate(GLib.Variant.new_uint16(index))

    @Gtk.Template.Callback()
    def _cycle_end_timestamp_type(self, *_args: Any) -> None:
        state_settings.set_enum(
            "end-timestamp-type",
            int(not showtime.end_timestamp_type),
        )

        self._set_end_timestamp_label(
            self.play.props.position, self.play.props.duration
        )

    @Gtk.Template.Callback()
    def _resume(self, *_args: Any) -> None:
        self.unpause()

    @Gtk.Template.Callback()
    def _play_again(self, *_args: Any) -> None:
        self.play.seek(0)
        self.unpause()

    @Gtk.Template.Callback()
    def _rotate_left(self, *_args: Any) -> None:
        match int((props := self.paintable.props).orientation):
            case 0:
                props.orientation = 4
            case 1:
                props.orientation = 4
            case 5:
                props.orientation = 8
            case _:
                props.orientation -= 1

    @Gtk.Template.Callback()
    def _rotate_right(self, *_args: Any) -> None:
        match int((props := self.paintable.props).orientation):
            case 0:
                props.orientation = 2
            case 4:
                props.orientation = 1
            case 8:
                props.orientation = 5
            case _:
                props.orientation += 1

    @Gtk.Template.Callback()
    def _on_drop(self, _target: Any, gfile: Gio.File, _x: Any, _y: Any) -> None:
        self.play_video(gfile)

    def _get_previous_play_position(self) -> float | None:
        if not (uri := self.play.props.uri):
            return None

        try:
            hist_file = (showtime.state_path / "playback_history.json").open("r")
        except FileNotFoundError:
            logger.info("Cannot restore play positon, no playback history file")
            return None

        try:
            hist = json.load(hist_file)
        except EOFError as error:
            logger.warning("Cannot restore play positon: %s", error)
            return None

        hist_file.close()

        return hist.get(sha256(uri.encode("utf-8")).hexdigest())

    def _resize_window(
        self, _obj: Any, paintable: Gdk.Paintable, initial: bool | None = False
    ) -> None:
        logger.debug("Resizing window…")

        if initial:
            self.disconnect_by_func(self._resize_window)

        if not (video_width := paintable.get_intrinsic_width()) or not (
            video_height := paintable.get_intrinsic_height()
        ):
            return

        if not (surface := self.get_surface()):
            logger.error("Could not get GdkSurface to resize window")
            return

        if not (monitor := self.props.display.get_monitor_at_surface(surface)):
            logger.error("Could not get GdkMonitor to resize window")
            return

        video_area = video_width * video_height
        init_width, init_height = self.get_default_size()

        if initial:
            # Algorithm copied from Loupe
            # https://gitlab.gnome.org/GNOME/loupe/-/blob/4ca5f9e03d18667db5d72325597cebc02887777a/src/widgets/image/rendering.rs#L151

            hidpi_scale = surface.props.scale_factor

            monitor_rect = monitor.props.geometry

            monitor_width = monitor_rect.width
            monitor_height = monitor_rect.height

            monitor_area = monitor_width * monitor_height
            logical_monitor_area = monitor_area * pow(hidpi_scale, 2)

            occupy_area_factor = (
                SMALL_OCCUPY_SCREEN
                if logical_monitor_area <= SMALL_SCREEN_AREA
                else DEFAULT_OCCUPY_SCREEN
            )

            size_scale = sqrt(monitor_area / video_area * occupy_area_factor)

            target_scale = min(1, size_scale)
            nat_width = video_width * target_scale
            nat_height = video_height * target_scale

            max_width = monitor_width - 20
            if nat_width > max_width:
                nat_width = max_width
                nat_height = video_height * nat_width / video_width

            max_height = monitor_height - (50 + 35 + 20) * hidpi_scale
            if nat_height > max_height:
                nat_height = max_height
                nat_width = video_width * nat_height / video_height

        else:
            prev_area = init_width * init_height

            if video_width > video_height:
                ratio = video_width / video_height
                nat_width = int(sqrt(prev_area * ratio))
                nat_height = int(nat_width / ratio)
            else:
                ratio = video_height / video_width
                nat_width = int(sqrt(prev_area / ratio))
                nat_height = int(nat_width * ratio)

            if (abs(init_width - nat_width) < SMALL_SIZE_CHANGE) and (
                abs(init_height - nat_height) < SMALL_SIZE_CHANGE
            ):
                return

        nat_width = round(nat_width)
        nat_height = round(nat_height)

        for prop, init, target in (
            ("default-width", init_width, nat_width),
            ("default-height", init_height, nat_height),
        ):
            anim = Adw.TimedAnimation.new(
                self, init, target, 500, Adw.PropertyAnimationTarget.new(self, prop)
            )
            anim.props.easing = Adw.Easing.EASE_OUT_EXPO
            (anim.skip if initial else anim.play)()
            logger.debug("Resized window to %ix%i", nat_width, nat_height)

    def _on_end_timestamp_type_changed(self, *_args: Any) -> None:
        showtime.end_timestamp_type = state_settings.get_enum("end-timestamp-type")
        self._set_end_timestamp_label(
            self.play.props.position, self.play.props.duration
        )

    def _set_end_timestamp_label(self, pos: int, dur: int) -> None:
        match showtime.end_timestamp_type:
            case 0:  # Duration
                self.end_timestamp_button.props.label = nanoseconds_to_timestamp(dur)
            case 1:  # Remaining
                self.end_timestamp_button.props.label = "-" + nanoseconds_to_timestamp(
                    dur - pos
                )

    @Gtk.Template.Callback()
    def _schedule_volume_change(self, _obj: Any, value: float) -> None:
        GLib.idle_add(
            partial(
                self.pipeline.set_volume,  # pyright: ignore[reportAttributeAccessIssue]
                GstAudio.StreamVolumeFormat.CUBIC,
                value,
            )
        )

    def _set_overlay_revealed(self, widget: Gtk.Widget, reveal: bool) -> None:
        animations = self._reveal_animations if reveal else self._hide_animations
        animation = animations.get(widget)

        if animation and (animation.props.state == Adw.AnimationState.PLAYING):
            return

        animations[widget] = Adw.TimedAnimation.new(
            widget,
            widget.props.opacity,
            int(reveal),
            250,
            Adw.PropertyAnimationTarget.new(widget, "opacity"),
        )

        widget.props.can_target = reveal
        animations[widget].play()

    def _reveal_overlay(self, widget: Gtk.Widget) -> None:
        self._set_overlay_revealed(widget, True)

    def _hide_overlay(self, widget: Gtk.Widget) -> None:
        self._set_overlay_revealed(widget, False)

    def _hide_overlays(self, timestamp: float) -> None:
        if (
            # Cursor moved
            timestamp != self._last_reveal
            # Cursor is hovering controls
            or any(motion.props.contains_pointer for motion in self.overlay_motions)
            # Active popover
            or any(button.props.active for button in self.overlay_menu_buttons)
            # Active restore buttons
            or self.restore_breakpoint_bin.props.can_target
        ):
            return

        for widget in self.overlay_widgets:
            self._hide_overlay(widget)

        if self.overlay_motion.contains_pointer():
            self.set_cursor_from_name("none")

    @Gtk.Template.Callback()
    def _on_realize(self, *_args: Any) -> None:
        if not (surface := self.get_surface()):
            return

        if not isinstance(surface, Gdk.Toplevel):
            return

        surface.connect("notify::state", self._on_toplevel_state_changed)

    def _on_toplevel_state_changed(self, toplevel: Gdk.Toplevel, *_args: Any) -> None:
        if (
            focused := toplevel.get_state() & Gdk.ToplevelState.FOCUSED
        ) == self._toplevel_focused:
            return

        if not focused:
            self._hide_overlays(self._last_reveal)

        self._toplevel_focused = bool(focused)

    def _on_paintable_invalidate_size(
        self, paintable: Gdk.Paintable, *_args: Any
    ) -> None:
        if self.is_visible():
            # Add a timeout to not interfere with loading the stream too much
            GLib.timeout_add(100, self._resize_window, None, paintable)
        else:
            self.connect("map", self._resize_window, paintable, True)

    @Gtk.Template.Callback()
    def _on_motion(
        self, _obj: Any = None, x: float | None = None, y: float | None = None
    ) -> None:
        if None not in (x, y):
            if (x, y) == self._prev_motion_xy:
                return

            self._prev_motion_xy = (x, y)

        self.set_cursor_from_name(None)

        for widget in self.overlay_widgets:
            self._reveal_overlay(widget)

        self._last_reveal = time()
        GLib.timeout_add_seconds(2, self._hide_overlays, self._last_reveal)

    def _on_playback_state_changed(self, _obj: Any, state: GstPlay.PlayState) -> None:
        # Only show a spinner if buffering for more than a second
        if state == GstPlay.PlayState.BUFFERING:
            self.buffering = True
            GLib.timeout_add_seconds(
                1,
                lambda *_: (
                    self._reveal_overlay(self.spinner) if self.buffering else None
                ),
            )
            return

        self.buffering = False
        self._hide_overlay(self.spinner)

        match state:
            case GstPlay.PlayState.PAUSED:
                self.paused = True
            case GstPlay.PlayState.STOPPED:
                self.paused = True
                self.stopped = True
            case GstPlay.PlayState.PLAYING:
                self.paused = False

    def _on_duration_changed(self, _obj: Any, dur: int) -> None:
        self._set_end_timestamp_label(self.play.props.position, dur)

    def _on_position_updated(self, _obj: Any, pos: int) -> None:
        dur = self.play.props.duration

        self.seek_scale.set_value((pos / dur) * SCALE_MULT)

        # TODO: This can probably be done only every second instead
        self.position_label.props.label = nanoseconds_to_timestamp(pos)
        self._set_end_timestamp_label(pos, dur)

    @Gtk.Template.Callback()
    def _seek(self, _obj: Any, _scroll: Any, val: float) -> None:
        if not self._seeking:
            self._seeking = True
            self._seek_paused = self.paused

        if not self.paused:
            self.pause()

        self.play.seek(max(self.play.props.duration * (val / SCALE_MULT), 0))
        self.emit("seeked")

        def post_seek(seeked: float) -> None:
            if seeked != self._last_seek:
                return

            if not self._seek_paused:
                self.unpause()

            self._seeking = False

        self._last_seek = time()
        GLib.timeout_add(250, post_seek, self._last_seek)

    def _on_seek_done(self, _obj: Any) -> None:
        pos = self.play.props.position
        dur = self.play.props.duration

        self.seek_scale.set_value((pos / dur) * SCALE_MULT)
        self.position_label.props.label = nanoseconds_to_timestamp(pos)
        self._set_end_timestamp_label(pos, dur)
        logger.debug("Seeked to %i", pos)

    def _on_media_info_updated(
        self, _obj: Any, media_info: GstPlay.PlayMediaInfo
    ) -> None:
        self.title_label.props.label = get_title(media_info) or ""

        # Add a timeout to reduce things happening at once while the video is loading
        # since the user won't want to change languages/subtitles within 500ms anyway
        self.options.menus_building += 1
        GLib.timeout_add(500, self.options.build_menus, media_info)
        self.emit("media-info-updated")

    def _on_volume_changed(self, _obj: Any) -> None:
        vol = self.pipeline.get_volume(GstAudio.StreamVolumeFormat.CUBIC)  # pyright: ignore[reportAttributeAccessIssue]

        if self._prev_volume == vol:
            return

        self._prev_volume = vol
        self.volume = vol
        self.sound_options.adjustment.props.value = vol

        self.emit("volume-changed")

    def _on_end_of_stream(self, _obj: Any) -> None:
        if not state_settings.get_boolean("looping"):
            self.pause()

        self.play.seek(0)

    def _on_warning(self, _obj: Any, warning: GLib.Error) -> None:
        logger.warning(warning)

    def _on_error(self, _obj: Any, error: GLib.Error) -> None:
        logger.error(error.message)

        if (
            self.placeholder_stack.get_visible_child()
            == self.missing_plugin_status_page
        ):
            return

        def copy_details(*_args: Any) -> None:
            if not (display := Gdk.Display.get_default()):
                return

            display.get_clipboard().set(error.message)

            self.toast_overlay.add_toast(Adw.Toast.new(_("Details copied")))

        copy = Adw.ButtonRow(title=_("Copy Technical Details"))  # pyright: ignore[reportAttributeAccessIssue]
        copy.connect("activated", copy_details)

        retry = Adw.ButtonRow(title=_("Try Again"))  # pyright: ignore[reportAttributeAccessIssue]
        retry.add_css_class("suggested-action")
        retry.connect("activated", self._try_again)

        group = Adw.PreferencesGroup(
            halign=Gtk.Align.CENTER,
            width_request=250,
            separate_rows=True,  # pyright: ignore[reportCallIssue]
        )
        group.add(retry)
        group.add(copy)

        self.error_status_page.props.child = group

        self.placeholder_stack.props.visible_child = self.error_status_page
        self.stack.props.visible_child = self.placeholder_page

    def _on_missing_plugin(self, _obj: Any, msg: Gst.Message) -> None:
        # This is so media that is still partially playable doesn't get interrupted
        # https://gstreamer.freedesktop.org/documentation/additional/design/missing-plugins.html#partially-missing-plugins
        if (
            self.pipeline.get_state(Gst.CLOCK_TIME_NONE)[0]
            != Gst.StateChangeReturn.FAILURE
        ):
            return

        desc = GstPbutils.missing_plugin_message_get_description(msg)
        detail = GstPbutils.missing_plugin_message_get_installer_detail(msg)

        self.missing_plugin_status_page.props.description = _(
            "The “{}” codecs required to play this video could not be found"
        ).format(desc)

        if not GstPbutils.install_plugins_supported():
            self.missing_plugin_status_page.props.child = None
            self.placeholder_stack.props.visible_child = self.missing_plugin_status_page
            self.stack.props.visible_child = self.placeholder_page
            return

        def on_install_done(result: GstPbutils.InstallPluginsReturn) -> None:
            match result:
                case GstPbutils.InstallPluginsReturn.SUCCESS:
                    logger.debug("Plugin installed")
                    self._try_again()

                case GstPbutils.InstallPluginsReturn.NOT_FOUND:
                    logger.error("Plugin installation failed: Not found")
                    self.missing_plugin_status_page.props.description = _(
                        "No plugin available for this media type"
                    )

                case _:
                    logger.error("Plugin installation failed, result: %d", int(result))
                    self.missing_plugin_status_page.props.description = _(
                        "Unable to install the required plugin"
                    )

        button = Gtk.Button(halign=Gtk.Align.CENTER, label=_("Install Plugin"))
        button.add_css_class("pill")
        button.add_css_class("suggested-action")

        def install_plugin(*_args: Any) -> None:
            GstPbutils.install_plugins_async(
                (detail,) if detail else (), None, on_install_done
            )
            self.toast_overlay.add_toast(Adw.Toast.new(_("Installing…")))
            button.props.sensitive = False

        button.connect("clicked", install_plugin)

        self.missing_plugin_status_page.props.child = button

        self.missing_plugin_status_page.props.description = _(
            "“{}” codecs are required to play this video"
        ).format(desc)
        self.placeholder_stack.props.visible_child = self.missing_plugin_status_page
        self.stack.props.visible_child = self.placeholder_page

    @Gtk.Template.Callback()
    def _on_primary_click_released(
        self, gesture: Gtk.Gesture, n: int, *_args: Any
    ) -> None:
        gesture.set_state(Gtk.EventSequenceState.CLAIMED)
        self._on_motion()

        if not n % 2:
            self.props.fullscreened = not self.props.fullscreened

    @Gtk.Template.Callback()
    def _on_secondary_click_pressed(
        self, gesture: Gtk.Gesture, _n: Any, x: int, y: int
    ) -> None:
        self.options.on_secondary_click_pressed(self, gesture, x, y)

    def _try_again(self, *_args: Any) -> None:
        if not (app := self.props.application):
            return

        cast("Application", app).do_activate(self._playing_gfile)
        self.close()

    @Gtk.Template.Callback()
    def _get_play_icon(self, _obj: Any, paused: bool) -> str:
        return (
            "media-playback-start-symbolic"
            if paused
            else "media-playback-pause-symbolic"
        )

    @Gtk.Template.Callback()
    def _get_fullscreen_icon(self, _obj: Any, fullscreened: bool) -> str:
        return "view-restore-symbolic" if fullscreened else "view-fullscreen-symbolic"

    def _create_actions(self) -> None:
        self._create_action(
            "close-window",
            lambda *_: self.close(),
            ("<primary>w", "q"),
        )

        self._create_action(
            "about",
            lambda *_: self._present_about_dialog(),
        )

        self._create_action(
            "toggle-fullscreen",
            lambda *_: self.set_property("fullscreened", not self.props.fullscreened),
            ("F11", "f"),
        )

        self._create_action(
            "toggle-playback",
            lambda *_: self.unpause() if self.paused else self.pause(),
            ("p", "k", "space"),
        )

        self._create_action(
            "increase-volume",
            lambda *_: self.play.set_volume(min(self.play.props.volume + 0.05, 1)),
            ("Up",),
        )

        self._create_action(
            "decrease-volume",
            lambda *_: self.play.set_volume(max(self.play.props.volume - 0.05, 0)),
            ("Down",),
        )

        self._create_action(
            "toggle-mute",
            lambda *_: self.set_property("mute", not self.mute),
            ("m",),
        )

        self._create_action(
            "backwards",
            lambda *_: self.play.seek(max(0, self.play.props.position - 1e10)),
            ("Left",),
        )

        self._create_action(
            "forwards",
            lambda *_: self.play.seek(self.play.props.position + 1e10),
            ("Right",),
        )

        self._create_action(
            "screenshot",
            lambda *_: self._save_screenshot(),
            ("<primary><alt>s",),
        ).props.enabled = False

        self._create_action(
            "show-in-files",
            lambda *_: Gtk.FileLauncher.new(
                Gio.File.new_for_uri(self.play.props.uri)
            ).open_containing_folder(),
        ).props.enabled = False

        self._create_action(
            "open-video",
            lambda *_args: self.open_video_dialog.open(
                self, callback=self._on_open_video
            ),
            ("<primary>o",),
        )

        self._create_action(
            "choose-subtitles",
            lambda *_args: self.choose_subtitles_dialog.open(
                self, callback=self._on_choose_subtitles
            ),
        )

        subs_action = Gio.SimpleAction.new_stateful(
            "select-subtitles",
            GLib.VariantType.new("q"),
            GLib.Variant.new_uint16(0),
        )
        subs_action.connect("activate", self._on_subtitles_selected)
        self.add_action(subs_action)

        lang_action = Gio.SimpleAction.new_stateful(
            "select-language",
            GLib.VariantType.new("q"),
            GLib.Variant.new_uint16(0),
        )
        lang_action.connect("activate", self._on_language_selected)
        self.add_action(lang_action)

        toggle_loop_action = Gio.SimpleAction.new_stateful(
            "toggle-loop",
            None,
            GLib.Variant.new_boolean(state_settings.get_boolean("looping")),
        )
        toggle_loop_action.connect("activate", self._on_toggle_loop)
        toggle_loop_action.connect("change-state", self._on_toggle_loop)
        self.add_action(toggle_loop_action)

    def _create_action(
        self,
        name: str,
        callback: Callable,
        shortcuts: Sequence[str] | None = None,
    ) -> Gio.SimpleAction:
        action = Gio.SimpleAction.new(name, None)
        action.connect("activate", callback)
        self.add_action(action)

        if shortcuts and (app := self.props.application):
            if system == "Darwin":
                shortcuts = tuple(s.replace("<primary>", "<meta>") for s in shortcuts)

            app.set_accels_for_action(f"win.{name}", shortcuts)

        return action

    def _present_about_dialog(self) -> None:
        # Get the debug info from the log files
        about = Adw.AboutDialog.new_from_appdata(
            f"{PREFIX}/{APP_ID}.metainfo.xml", VERSION
        )
        about.props.developers = ["kramo https://kramo.page"]
        about.props.designers = [
            "Tobias Bernard https://tobiasbernard.com/",
            "Allan Day https://blogs.gnome.org/aday/",
            "kramo https://kramo.page",
        ]
        about.props.copyright = "© 2024-2025 kramo"
        # Translators: Replace this with your name for it to show up in the about dialog
        about.props.translator_credits = _("translator_credits")

        try:
            about.props.debug_info = log_file.read_text()
        except FileNotFoundError:
            pass
        else:
            about.props.debug_info_filename = log_file.name

        about.present(self)

    def _save_screenshot(self) -> None:
        """Save a snapshot of the current frame of the currently playing video as a PNG.

        It tries saving it to `xdg-pictures/Screenshots` and falls back to `~`.
        """
        logger.debug("Saving screenshot…")

        if not (paintable := self.picture.props.paintable):
            logger.warning("Cannot save screenshot, no paintable")
            return

        if not (texture := screenshot(paintable, self)):
            return

        path = (
            str(Path(pictures, "Screenshots"))
            if (pictures := GLib.get_user_special_dir(GLib.USER_DIRECTORY_PICTURES))  # pyright: ignore[reportArgumentType]
            else GLib.get_home_dir()
        )

        title = get_title(self.play.get_media_info()) or _("Unknown Title")
        timestamp = nanoseconds_to_timestamp(self.play.get_position(), hours=True)

        path = str(Path(path, f"{title} {timestamp}.png"))

        texture.save_to_png(path)

        toast = Adw.Toast(
            title=_("Screenshot captured"),
            priority=Adw.ToastPriority.HIGH,
            button_label=_("Show in Files"),
        )
        toast.connect(
            "button-clicked",
            lambda *_: Gtk.FileLauncher.new(
                Gio.File.new_for_path(path)
            ).open_containing_folder(),
        )
        self.toast_overlay.add_toast(toast)

        logger.debug("Screenshot saved")

    def _on_open_video(self, dialog: Gtk.FileDialog, res: Gio.AsyncResult) -> None:
        try:
            gfile = dialog.open_finish(res)
        except GLib.Error:
            return

        if not gfile:
            return

        self.play_video(gfile)

    def _on_choose_subtitles(
        self, dialog: Gtk.FileDialog, res: Gio.AsyncResult
    ) -> None:
        try:
            gfile = dialog.open_finish(res)
        except GLib.Error:
            return

        if not gfile:
            return

        self.play.props.suburi = gfile.get_uri()
        self.select_subtitles(0)
        logger.debug("External subtitle added: %s", gfile.get_uri())

    def _on_subtitles_selected(
        self,
        action: Gio.SimpleAction,
        state: GLib.Variant,
    ) -> None:
        action.props.state = state

        if (index := state.get_uint16()) == GLib.MAXUINT16:
            self.play.set_subtitle_track_enabled(False)
        else:
            self.play.set_subtitle_track(index)
            self.play.set_subtitle_track_enabled(True)

    def _on_language_selected(
        self,
        action: Gio.SimpleAction,
        state: GLib.Variant,
    ) -> None:
        action.props.state = state
        self.play.set_audio_track(state.get_uint16())

    def _on_toggle_loop(
        self,
        action: Gio.SimpleAction,
        _state: GLib.Variant,
    ) -> None:
        value = not action.props.state.get_boolean()
        action.set_state(GLib.Variant.new_boolean(value))
        state_settings.set_boolean("looping", value)
