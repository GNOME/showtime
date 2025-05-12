# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2024-2025 kramo

# pyright: reportAssignmentType=none

"""The main application window."""

import logging
import pickle
from functools import partial
from gettext import ngettext
from hashlib import sha256
from math import sqrt
from pathlib import Path
from time import time
from typing import Any

from gi.repository import (
    Adw,
    Gdk,
    Gio,
    GLib,
    GObject,
    Gst,
    GstAudio,  # type: ignore
    GstPbutils,
    GstPlay,  # type: ignore
    Gtk,
)

import showtime
from showtime import (
    DEFAULT_OCCUPY_SCREEN,
    MAX_UINT16,
    PREFIX,
    PROFILE,
    SMALL_OCCUPY_SCREEN,
    SMALL_SCREEN_AREA,
    state_settings,
    system,
)
from showtime.drag_overlay import DragOverlay
from showtime.messenger import Messenger
from showtime.play import gst_play_setup
from showtime.utils import (
    get_title,
    lookup_action,
    nanoseconds_to_timestamp,
    screenshot,
)

SCALE_MULT = 500  # This is so that seeking isn't too rough


@Gtk.Template(resource_path=f"{PREFIX}/gtk/window.ui")
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
    end_timestamp_button: Gtk.Button = Gtk.Template.Child()

    volume_adjustment: Gtk.Adjustment = Gtk.Template.Child()
    volume_menu_button: Gtk.MenuButton = Gtk.Template.Child()
    mute_button: Gtk.ToggleButton = Gtk.Template.Child()

    options_popover: Gtk.Popover = Gtk.Template.Child()
    options_menu_button: Gtk.MenuButton = Gtk.Template.Child()

    language_menu: Gio.Menu = Gtk.Template.Child()
    subtitles_menu: Gio.Menu = Gtk.Template.Child()

    spinner: Adw.Spinner = Gtk.Template.Child()  # type: ignore
    restore_breakpoint_bin: Adw.BreakpointBin = Gtk.Template.Child()
    restore_box: Gtk.Box = Gtk.Template.Child()

    overlay_motions: set[Gtk.EventControllerMotion] = set()
    overlay_menu_buttons: set[Gtk.MenuButton] = set()

    stopped: bool = True
    buffering: bool = False

    menus_building: int = 0

    _reveal_animations: dict[Gtk.Widget, Adw.Animation] = {}
    _hide_animations: dict[Gtk.Widget, Adw.Animation] = {}

    _last_reveal: float = 0.0
    _last_seek: float = 0.0

    _paused: bool = True
    _seeking: bool = False
    _seek_paused: bool = False
    _prev_motion_xy: tuple = (0, 0)
    _prev_volume = -1
    _toplevel_focused: bool = False

    media_info_updated = GObject.Signal(name="media-info-updated")
    volume_changed = GObject.Signal(name="volume-changed")
    rate_changed = GObject.Signal(name="rate-changed")
    seeked = GObject.Signal(name="seeked")

    volume = GObject.Property(type=float)

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
        self.options_popover.popdown()
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

        (app.uninhibit_win if paused else app.inhibit_win)(self)  # type: ignore

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(decorated=False if system == "Darwin" else True, **kwargs)

        if system == "Darwin":
            self.placeholder_primary_menu_button.props.visible = False
            self.video_primary_menu_button.props.visible = False
            self.spinner.props.margin_top = 6

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
            self.options_menu_button,
            self.volume_menu_button,
        }

        self._window_resized()
        self._on_stack_child_changed()

        state_settings.connect(
            "changed::end-timestamp-type",
            self._on_end_timestamp_type_changed,
        )

    def play_video(self, gfile: Gio.File) -> None:
        """Start playing the given `GFile`."""
        try:
            file_info = gfile.query_info(
                ",".join(
                    (
                        Gio.FILE_ATTRIBUTE_STANDARD_IS_SYMLINK,
                        Gio.FILE_ATTRIBUTE_STANDARD_SYMLINK_TARGET,
                    )
                ),
                Gio.FileQueryInfoFlags.NOFOLLOW_SYMLINKS,
            )
        except GLib.Error:
            uri = gfile.get_uri()
        else:
            uri = (
                target
                if file_info.get_is_symlink()
                and (target := file_info.get_symlink_target())
                else gfile.get_uri()
            )

        logging.debug("Playing video: %s.", uri)

        self.media_info_updated = False
        self.stack.props.visible_child = self.video_page
        self.placeholder_stack.props.visible_child = self.error_status_page
        self._select_subtitles(0)
        self.rate = "1.0"

        self.play.props.uri = uri
        self.pause()
        self._on_motion()

        if not (pos := self._get_previous_play_position()):
            self.unpause()
            logging.debug("No previous play position.")
            return

        # Don't restore the previous play position if it is in the first minute
        if pos < 6e10:
            self.unpause()
            logging.debug("Previous play position before 60s.")
            return

        logging.debug("Previous play position restored: %i.", pos)

        def setup_cb(*_args: Any) -> None:
            self._reveal_overlay(self.restore_breakpoint_bin)
            self._hide_overlay(self.controls_box)
            self.play.seek(pos)

            self.pipeline.disconnect_by_func(setup_cb)

        self.pipeline.connect("source-setup", setup_cb)

    def save_screenshot(self) -> None:
        """Save a screenshot of the current frame of the video being played in PNG format.

        It tries saving it to `xdg-pictures/Screenshots` and falls back to `~`.
        """
        logging.debug("Saving screenshot…")

        if not (paintable := self.picture.props.paintable):
            logging.warning("Cannot save screenshot, no paintable.")
            return

        if not (texture := screenshot(paintable, self)):
            return

        path = (
            str(Path(pictures, "Screenshots"))
            if (pictures := GLib.get_user_special_dir(GLib.USER_DIRECTORY_PICTURES))  # type: ignore
            else GLib.get_home_dir()
        )

        title = get_title(self.play.get_media_info()) or _("Unknown Title")
        timestamp = nanoseconds_to_timestamp(self.play.get_position(), False)

        path = str(Path(path, f"{title} {timestamp}.png"))

        texture.save_to_png(path)

        toast = Adw.Toast.new(_("Screenshot captured"))
        toast.props.priority = Adw.ToastPriority.HIGH
        toast.props.button_label = _("Show in Files")
        toast.connect(
            "button-clicked",
            lambda *_: Gtk.FileLauncher.new(
                Gio.File.new_for_path(path)
            ).open_containing_folder(),
        )

        self.toast_overlay.add_toast(toast)
        logging.debug("Screenshot saved.")

    def unpause(self) -> None:
        """Start playing the current video."""
        self._hide_overlay(self.restore_breakpoint_bin)
        self._reveal_overlay(self.controls_box)
        self.play.play()
        logging.debug("Video unpaused.")

    def pause(self, *_args: Any) -> None:
        """Pause the currently playing video."""
        self.play.pause()
        logging.debug("Video paused.")

    def choose_video(self) -> None:
        """Open a file dialog to pick a video to play."""
        Gtk.FileDialog(
            default_filter=Gtk.FileFilter(name=_("Video"), mime_types=("video/*",))
        ).open(self, callback=self._choose_video_cb)

    def choose_subtitles(self) -> None:
        """Open a file dialog to pick a subtitle."""
        Gtk.FileDialog(
            default_filter=Gtk.FileFilter(
                name=_("Subtitles"),
                mime_types=("application/x-subrip", "text/x-ssa", "text/vtt"),
                suffixes=("srt", "ssa", "ass", "vtt"),
            )
        ).open(self, callback=self._choose_subtitles_cb)

    def select_subtitles(self, action: Gio.SimpleAction, state: GLib.Variant) -> None:
        """Select the given subtitles for the video."""
        action.props.state = state
        if (index := state.get_uint16()) == MAX_UINT16:
            self.play.set_subtitle_track_enabled(False)
            return

        self.play.set_subtitle_track(index)
        self.play.set_subtitle_track_enabled(True)

    def select_language(self, action: Gio.SimpleAction, state: GLib.Variant) -> None:
        """Select the given language for the video."""
        action.props.state = state
        self.play.set_audio_track(state.get_uint16())

    def build_menus(self, media_info: GstPlay.PlayMediaInfo) -> None:
        """(Re)build the Subtitles and Language menus for the currently playing video."""
        self.menus_building -= 1

        # Don't try to rebuild the menu multiple times when the media info has many changes
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
                    # Translators: The variable is the number of channels in an audio track
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
                f"app.select-language(uint16 {index})",
            )
            langs += 1

        if not langs:
            self.language_menu.append(_("No Audio"), "nonexistent.action")
            # HACK: This is to make the item insensitive
            # I don't know if there is a better way to do this

        self.subtitles_menu.append(
            _("None"), f"app.select-subtitles(uint16 {MAX_UINT16})"
        )

        subs = 0
        for index, stream in enumerate(media_info.get_subtitle_streams()):
            has_title, title = stream.get_tags().get_string("title")
            language = stream.get_language() or _("Undetermined Language")

            self.subtitles_menu.append(
                f"{language}{(' - ' + title) if (has_title and title) else ''}",
                f"app.select-subtitles(uint16 {index})",
            )
            subs += 1

        if not subs:
            self._select_subtitles(MAX_UINT16)

        self.subtitles_menu.append(_("Add Subtitle File…"), "app.choose-subtitles")

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

    def _choose_video_cb(self, dialog: Gtk.FileDialog, res: Gio.AsyncResult) -> None:
        try:
            gfile = dialog.open_finish(res)
        except GLib.Error:
            return

        if not gfile or not (app := self.props.application):
            return

        app.save_play_position(self)  # type: ignore
        self.play_video(gfile)

    def _choose_subtitles_cb(
        self, dialog: Gtk.FileDialog, res: Gio.AsyncResult
    ) -> None:
        try:
            gfile = dialog.open_finish(res)
        except GLib.Error:
            return

        if not gfile:
            return

        self.play.props.suburi = gfile.get_uri()
        self._select_subtitles(0)
        logging.debug("External subtitle added: %s.", gfile.get_uri())

    def _select_subtitles(self, index: int) -> None:
        if action := lookup_action(self.props.application, "select-subtitles"):
            action.activate(GLib.Variant.new_uint16(index))

    def _set_volume_display(
        self, muted: bool | None = None, volume: float | None = None
    ) -> None:
        if muted is None:
            muted: bool = self.play.props.mute

        if volume is None:
            volume = self.play.props.volume or 0.0

        self.mute_button.props.active = muted

        if muted:
            icon = "audio-volume-muted-symbolic"
        elif volume > 0.7:
            icon = "audio-volume-high-symbolic"
        elif volume > 0.3:
            icon = "audio-volume-medium-symbolic"
        else:
            icon = "audio-volume-low-symbolic"

        self.volume_menu_button.props.icon_name = icon

    def _get_previous_play_position(self) -> float | None:
        if not (uri := self.play.props.uri):
            return None

        try:
            hist_file = (showtime.cache_path / "playback_history").open("rb")
        except FileNotFoundError:
            logging.info("Cannot restore play positon, no playback history file.")
            return None

        try:
            hist = pickle.load(hist_file)
        except EOFError as error:
            logging.warning("Cannot restore play positon: %s", error)
            return None

        hist_file.close()

        return hist.get(sha256(uri.encode("utf-8")).hexdigest())

    def _resize_window(
        self, _obj: Any, paintable: Gdk.Paintable, initial: bool | None = False
    ) -> None:
        logging.debug("Resizing window…")

        if initial:
            self.disconnect_by_func(self._resize_window)

        if not (video_width := paintable.get_intrinsic_width()) or not (
            video_height := paintable.get_intrinsic_height()
        ):
            return

        if not (surface := self.get_surface()):
            logging.error("Could not get GdkSurface to resize window.")
            return

        if not (monitor := self.props.display.get_monitor_at_surface(surface)):
            logging.error("Could not get GdkMonitor to resize window.")
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

            # Don't resize on really small changes
            if (abs(init_width - nat_width) < 10) and (
                abs(init_height - nat_height) < 10
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
            logging.debug("Resized window to %i×%i.", nat_width, nat_height)

    @Gtk.Template.Callback()
    def _window_resized(self, *_args: Any) -> None:
        self.sink.props.window_width = (  # type: ignore
            self.props.default_width * self.props.scale_factor
        )
        self.sink.props.window_height = (  # type: ignore
            self.props.default_height * self.props.scale_factor
        )

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
    def _schedule_volume_change(self, adj: Gtk.Adjustment, _: Any) -> None:
        GLib.idle_add(
            partial(
                self.pipeline.set_volume,  # type: ignore
                GstAudio.StreamVolumeFormat.CUBIC,
                adj.get_value(),
            )
        )

    def _set_overlay_revealed(self, widget: Gtk.Widget, reveal: bool) -> None:
        animations = self._reveal_animations if reveal else self._hide_animations

        if (
            animation := animations.get(widget)
        ) and animation.get_state() == Adw.AnimationState.PLAYING:
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
        logging.debug("Seeked to %i.", pos)

    def _on_media_info_updated(
        self, _obj: Any, media_info: GstPlay.PlayMediaInfo
    ) -> None:
        self.title_label.props.label = get_title(media_info) or ""

        # Add a timeout to reduce the things happening at once while the video is loading
        # since the user won't want to change languages/subtitles within 500ms anyway
        self.menus_building += 1
        GLib.timeout_add(500, self.build_menus, media_info)
        self.emit("media-info-updated")

    def _on_volume_changed(self, _obj: Any) -> None:
        vol = self.pipeline.get_volume(GstAudio.StreamVolumeFormat.CUBIC)  # type: ignore

        if self._prev_volume == vol:
            return

        self._prev_volume = vol
        self._set_volume_display(volume=vol)
        self.volume_adjustment.props.value = vol

        self.emit("volume-changed")

    def _on_end_of_stream(self, _obj: Any) -> None:
        if not state_settings.get_boolean("looping"):
            self.pause()

        self.play.seek(0)

    def _on_warning(self, _obj: Any, warning: GLib.Error) -> None:
        logging.warning(warning)

    def _on_error(self, _obj: Any, error: GLib.Error) -> None:
        logging.error(error.message)

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

        button = Gtk.Button(halign=Gtk.Align.CENTER, label=_("Copy Technical Details"))
        button.add_css_class("pill")
        button.connect("clicked", copy_details)

        self.error_status_page.props.child = button

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
                    logging.debug("Plugin installed.")
                    self.stack.props.visible_child = self.video_page
                    self.pause()

                case GstPbutils.InstallPluginsReturn.NOT_FOUND:
                    logging.error("Plugin installation failed: Not found.")
                    self.missing_plugin_status_page.props.description = _(
                        "No plugin available for this media type"
                    )

                case _:
                    logging.error("Plugin installation failed, result: %d", int(result))
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
    def _on_stack_child_changed(self, *_args: Any) -> None:
        self._on_motion()

        app = self.props.application

        # TODO: Make this per-window instead of app-wide
        if (self.stack.props.visible_child != self.video_page) or not app:
            return

        if (action := lookup_action(app, "select-subtitles")) and system != "Darwin":
            action.props.enabled = True

        if (action := lookup_action(app, "show-in-files")) and system != "Darwin":
            action.props.enabled = True

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
        self,
        gesture: Gtk.Gesture,
        _n: Any,
        x: int,
        y: int,
    ) -> None:
        gesture.set_state(Gtk.EventSequenceState.CLAIMED)

        self.options_menu_button.props.popover = None
        self.options_popover.set_parent(self)
        self.options_popover.props.has_arrow = False
        self.options_popover.props.halign = Gtk.Align.START

        rectangle = Gdk.Rectangle()
        rectangle.x, rectangle.y, rectangle.width, rectangle.height = x, y, 0, 0
        self.options_popover.props.pointing_to = rectangle

        self.options_popover.popup()

        def closed(*_args: Any) -> None:
            self.options_popover.unparent()
            self.options_popover.props.has_arrow = True
            self.options_popover.props.halign = Gtk.Align.FILL

            self.options_popover.props.pointing_to = None  # type: ignore
            self.options_menu_button.props.popover = self.options_popover

            self.options_popover.disconnect_by_func(closed)

        self.options_popover.connect("closed", closed)

    @Gtk.Template.Callback()
    def _fullscreen_icon(self, _obj: Any, fullscreened: bool) -> str:
        return "view-restore-symbolic" if fullscreened else "view-fullscreen-symbolic"
