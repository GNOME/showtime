# window.py
#
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
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The main application window."""
import logging
import pickle
from hashlib import sha256
from os import sep
from pathlib import Path
from time import time
from typing import Any, Optional

from gi.repository import Adw, Gdk, Gio, GLib, GObject, Gst, GstPbutils, GstPlay, Gtk

from afternoon import shared
from afternoon.drag_overlay import AfternoonDragOverlay
from afternoon.utils import get_title, nanoseconds_to_timestamp, screenshot


@Gtk.Template(resource_path=f"{shared.PREFIX}/gtk/window.ui")
class AfternoonWindow(Adw.ApplicationWindow):
    """The main application window."""

    __gtype_name__ = "AfternoonWindow"

    breakpoint_dock: Adw.Breakpoint = Gtk.Template.Child()
    breakpoint_margin: Adw.Breakpoint = Gtk.Template.Child()
    drag_overlay: AfternoonDragOverlay = Gtk.Template.Child()
    toast_overlay: Adw.ToastOverlay = Gtk.Template.Child()
    stack: Gtk.Stack = Gtk.Template.Child()

    context_menu_popover: Gtk.PopoverMenu = Gtk.Template.Child()

    placeholder_page: Adw.ToolbarView = Gtk.Template.Child()
    placeholder_stack: Gtk.Stack = Gtk.Template.Child()
    open_status_page: Adw.StatusPage = Gtk.Template.Child()
    error_status_page: Adw.StatusPage = Gtk.Template.Child()
    missing_plugin_status_page: Adw.StatusPage = Gtk.Template.Child()
    button_open: Gtk.Button = Gtk.Template.Child()

    video_page: Gtk.WindowHandle = Gtk.Template.Child()
    video_overlay: Gtk.Overlay = Gtk.Template.Child()
    picture: Gtk.Picture = Gtk.Template.Child()

    header_revealer_start: Gtk.Revealer = Gtk.Template.Child()
    header_revealer_end: Gtk.Revealer = Gtk.Template.Child()
    header_start: Gtk.Box = Gtk.Template.Child()
    header_end: Gtk.Box = Gtk.Template.Child()
    button_fullscreen: Gtk.Button = Gtk.Template.Child()
    video_primary_menu_button: Gtk.MenuButton = Gtk.Template.Child()

    toolbar_revealer: Gtk.Revealer = Gtk.Template.Child()
    toolbar_box: Gtk.Box = Gtk.Template.Child()
    toolbar_hbox: Gtk.Box = Gtk.Template.Child()

    title_label: Gtk.Label = Gtk.Template.Child()
    play_button: Gtk.Button = Gtk.Template.Child()
    position_label: Gtk.Label = Gtk.Template.Child()
    seek_scale: Gtk.Scale = Gtk.Template.Child()
    duration_label: Gtk.Label = Gtk.Template.Child()

    volume_menu_button: Gtk.MenuButton = Gtk.Template.Child()
    volume_button: Gtk.Button = Gtk.Template.Child()
    volume_scale: Gtk.Scale = Gtk.Template.Child()

    options_popover: Gtk.Popover = Gtk.Template.Child()
    options_menu_button: Gtk.MenuButton = Gtk.Template.Child()
    default_speed_button: Gtk.ToggleButton = Gtk.Template.Child()
    language_menu: Gio.Menu = Gtk.Template.Child()
    subtitles_menu: Gio.Menu = Gtk.Template.Child()

    spinner_revealer: Gtk.Revealer = Gtk.Template.Child()
    restore_revealer: Gtk.Revealer = Gtk.Template.Child()

    overlay_motions: set = set()
    overlay_revealers: set = set()
    overlay_menu_buttons: set = set()

    _paused: bool = True
    stopped: bool = True
    buffering: bool = False
    reveal_timestamp: int = 0
    menus_building: int = 0
    prev_motion_xy: tuple = (0, 0)

    @GObject.Property(type=float)
    def rate(self) -> float:
        """The playback rate."""
        return self.play.get_rate()

    @rate.setter
    def rate(self, rate: float) -> None:
        self.play.set_rate(rate)
        # self.speed_menu_button.get_child().set_label(f"{round(rate, 2)}×")

    @GObject.Property(type=bool, default=True)
    def paused(self) -> bool:
        """Whether the video is currently paused."""
        return self._paused

    @paused.setter
    def paused(self, paused: bool) -> None:
        if not paused:
            self.stopped = False

        if self._paused == paused:
            return

        self._paused = paused

        if not (app := self.get_application()):
            return

        if paused:
            app.uninhibit_win(self)
        else:
            app.inhibit_win(self)

    @GObject.Signal(name="media-info-updated")
    def __media_info_updated(self) -> None:
        """Emitted when the currently playing video's media info is updated."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)

        # Set up GstPlay

        sink = Gst.ElementFactory.make("gtk4paintablesink")
        self.picture.set_paintable(paintable := sink.props.paintable)

        if paintable.props.gl_context:
            gl_sink = Gst.ElementFactory.make("glsinkbin")
            gl_sink.props.sink = sink
            sink = gl_sink

        self.play = GstPlay.Play(
            video_renderer=GstPlay.PlayVideoOverlayVideoRenderer.new_with_sink(
                None, sink
            )
        )

        self.pipeline = self.play.get_pipeline()
        self.pipeline.props.subtitle_font_desc = self.get_settings().props.gtk_font_name

        (bus := self.play.get_message_bus()).add_signal_watch()
        bus.connect("message", self.__on_play_bus_message)

        (bus := self.pipeline.get_bus()).add_signal_watch()
        bus.connect("message", self.__on_pipeline_bus_message)

        # Limit the size of the options popover

        self.options_popover.get_first_child().get_first_child().set_max_content_height(
            300
        )

        # Devel stripes

        if shared.PROFILE == "development":
            self.add_css_class("devel")

        # Primary and secondary click

        primary_click = Gtk.GestureClick(button=Gdk.BUTTON_PRIMARY)
        secondary_click = Gtk.GestureClick(button=Gdk.BUTTON_SECONDARY)

        primary_click.connect("released", self.__on_primary_click_released)
        secondary_click.connect("pressed", self.__on_secondary_click_pressed)

        self.video_overlay.add_controller(primary_click)
        self.video_overlay.add_controller(secondary_click)

        # Unfullscreen on Escape

        (esc := Gtk.ShortcutController()).add_shortcut(
            Gtk.Shortcut.new(
                Gtk.ShortcutTrigger.parse_string("Escape"),
                Gtk.CallbackAction.new(lambda *_: self.unfullscreen()),
            )
        )
        self.add_controller(esc)

        # Hide the toolbar on motion

        self.connect("move-focus", self.__on_motion)

        self.picture_motion = Gtk.EventControllerMotion()
        self.picture_motion.connect("motion", self.__on_motion)
        self.picture.add_controller(self.picture_motion)

        for widget in (
            self.toolbar_box,
            self.header_start,
            self.header_end,
        ):
            widget.add_controller(motion := Gtk.EventControllerMotion())
            self.overlay_motions.add(motion)

        self.overlay_revealers = {
            self.toolbar_revealer,
            self.header_revealer_start,
            self.header_revealer_end,
        }

        self.overlay_menu_buttons = {
            self.video_primary_menu_button,
            self.options_menu_button,
            self.volume_menu_button,
        }

        # Drag and drop

        (drop_target := Gtk.DropTarget.new(Gio.File, Gdk.DragAction.COPY)).connect(
            "drop", lambda _target, gfile, _x, _y: self.play_video(gfile)
        )
        self.add_controller(drop_target)
        self.drag_overlay.drop_target = drop_target

        # Connect signals

        self.stack.connect("notify::visible-child", self.__on_stack_child_changed)
        self.__on_stack_child_changed()

        self.connect("notify::fullscreened", self.__on_fullscreen)

        self.seek_scale.connect(
            "change-value",
            lambda _obj, _scroll, val: self.play.seek(
                max(self.play.get_duration() * val, 0)
            ),
        )

        self.volume_scale.connect(
            "change-value",
            lambda _obj, _scroll, val: self.play.set_volume(max(val, 0)),
        )

        self.breakpoint_margin.connect(
            "apply", lambda *_: self.toolbar_box.remove_css_class("sharp-corners")
        )
        self.breakpoint_margin.connect(
            "unapply", lambda *_: self.toolbar_box.add_css_class("sharp-corners")
        )
        self.breakpoint_dock.connect(
            "apply", lambda *_: self.toolbar_box.remove_css_class("sharp-corners")
        )
        self.breakpoint_dock.connect(
            "unapply", lambda *_: self.toolbar_box.add_css_class("sharp-corners")
        )

    def __on_play_bus_message(self, _bus: Gst.Bus, msg: GstPlay.PlayMessage) -> None:
        match GstPlay.PlayMessage.parse_type(msg):
            case GstPlay.PlayMessage.VIDEO_DIMENSIONS_CHANGED:
                width, height = GstPlay.PlayMessage.parse_video_dimensions_changed(msg)
                if width and height:
                    # Add a timeout to not interfere with loading the stream too much
                    GLib.timeout_add(100, self.__resize_window, width, height)

            case GstPlay.PlayMessage.STATE_CHANGED:
                state = GstPlay.PlayMessage.parse_state_changed(msg)

                # Only show a spinner if buffering for more than a second
                if state == GstPlay.PlayState.BUFFERING:
                    self.buffering = True
                    GLib.timeout_add_seconds(
                        1,
                        lambda *_: self.spinner_revealer.set_reveal_child(True)
                        if self.buffering
                        else None,
                    )
                    return

                self.buffering = False
                self.spinner_revealer.set_reveal_child(False)

                match state:
                    case GstPlay.PlayState.PAUSED:
                        self.play_button.set_icon_name("media-playback-start-symbolic")
                        self.paused = True
                    case GstPlay.PlayState.STOPPED:
                        self.play_button.set_icon_name("media-playback-start-symbolic")
                        self.paused = True
                        self.stopped = True
                    case GstPlay.PlayState.PLAYING:
                        self.play_button.set_icon_name("media-playback-pause-symbolic")
                        self.paused = False

            case GstPlay.PlayMessage.DURATION_CHANGED:
                self.duration_label.set_label(
                    nanoseconds_to_timestamp(
                        GstPlay.PlayMessage.parse_duration_updated(msg)
                    )
                )

            case GstPlay.PlayMessage.POSITION_UPDATED:
                self.seek_scale.set_value(
                    GstPlay.PlayMessage.parse_position_updated(msg)
                    / self.play.get_duration()
                )

                # TODO: This can probably be done only every second instead
                self.position_label.set_label(
                    nanoseconds_to_timestamp(
                        GstPlay.PlayMessage.parse_position_updated(msg)
                    )
                )

            case GstPlay.PlayMessage.SEEK_DONE:
                pos = self.play.get_position()
                dur = self.play.get_duration()

                self.seek_scale.set_value(pos / dur)
                self.position_label.set_label(nanoseconds_to_timestamp(pos))

            case GstPlay.PlayMessage.MEDIA_INFO_UPDATED:
                media_info = GstPlay.PlayMessage.parse_media_info_updated(msg)

                self.title_label.set_label(
                    get_title(media_info) or "",
                )

                # Add a timeout to reduce the things happening at once while the video is loading
                # since the user won't want to change languages/subtitles within 500ms anyway
                self.menus_building += 1
                GLib.timeout_add(500, self.build_menus, media_info)
                self.emit("media-info-updated")

            case GstPlay.PlayMessage.VOLUME_CHANGED:
                vol = GstPlay.PlayMessage.parse_volume_changed(msg)

                self.__set_volume_icons(volume=vol)
                self.volume_scale.set_value(vol)

            case GstPlay.PlayMessage.END_OF_STREAM:
                self.pause()
                self.play.seek(0)

            case GstPlay.PlayMessage.WARNING:
                logging.warning(GstPlay.PlayMessage.parse_warning(msg))

            case GstPlay.PlayMessage.ERROR:
                error, _details = GstPlay.PlayMessage.parse_error(msg)
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

                button = Gtk.Button(
                    halign=Gtk.Align.CENTER, label=_("Copy Technical Details")
                )
                button.add_css_class("pill")
                button.connect("clicked", copy_details)

                self.error_status_page.set_child(button)

                self.placeholder_stack.set_visible_child(self.error_status_page)
                self.stack.set_visible_child(self.placeholder_page)

    def __on_pipeline_bus_message(self, _bus: Gst.Bus, msg: Gst.Message) -> None:
        if not GstPbutils.is_missing_plugin_message(msg):
            return

        # This is so media that is still partially playable doesn't get interrupted
        # https://gstreamer.freedesktop.org/documentation/additional/design/missing-plugins.html#partially-missing-plugins
        if (
            self.pipeline.get_state(Gst.CLOCK_TIME_NONE)[0]
            != Gst.StateChangeReturn.FAILURE
        ):
            return

        desc = GstPbutils.missing_plugin_message_get_description(msg)
        detail = GstPbutils.missing_plugin_message_get_installer_detail(msg)

        self.missing_plugin_status_page.set_description(
            _("The “{}” codecs required to play this video could not be found").format(
                desc
            )
        )

        if not GstPbutils.install_plugins_supported():
            self.missing_plugin_status_page.set_child(None)
            self.placeholder_stack.set_visible_child(self.missing_plugin_status_page)
            self.stack.set_visible_child(self.placeholder_page)
            return

        def on_install_done(result) -> None:
            match result:
                case GstPbutils.InstallPluginsReturn.SUCCESS:
                    logging.debug("Plugin installed.")
                    self.stack.set_visible_child(self.video_page)
                    self.pause()

                case GstPbutils.InstallPluginsReturn.NOT_FOUND:
                    logging.error("Plugin installation failed: Not found.")
                    self.missing_plugin_status_page.set_description(
                        _("No plugin available for this media type")
                    )

                case _:
                    logging.error("Plugin installation failed, result: %d", int(result))
                    self.missing_plugin_status_page.set_description(
                        _("Unable to install the required plugin")
                    )

        button = Gtk.Button(halign=Gtk.Align.CENTER, label=_("Install Plugin"))
        button.add_css_class("pill")
        button.add_css_class("suggested-action")

        def install_plugin(*_args: Any) -> None:
            GstPbutils.install_plugins_async((detail,), None, on_install_done)
            self.toast_overlay.add_toast(Adw.Toast.new(_("Installing…")))
            button.set_sensitive(False)

        button.connect("clicked", install_plugin)

        self.missing_plugin_status_page.set_child(button)

        self.missing_plugin_status_page.set_description(
            _("“{}” codecs are required to play this video").format(desc)
        )
        self.placeholder_stack.set_visible_child(self.missing_plugin_status_page)
        self.stack.set_visible_child(self.placeholder_page)

    def play_video(self, gfile: Gio.File) -> None:
        """Starts playing the given `GFile`."""
        self.media_info_updated = False
        self.stack.set_visible_child(self.video_page)
        self.placeholder_stack.set_visible_child(self.error_status_page)
        self.__select_subtitles(0)

        self.default_speed_button.set_active(True)
        self.play.set_uri(gfile.get_uri())
        self.pause()

        if not (pos := self.__get_previous_play_position()):
            self.unpause()
            return

        # Don't restore the previous play position if it is in the first minute
        if pos < 6e10:
            self.unpause()
            return

        def setup_cb(*_args: Any) -> None:
            self.restore_revealer.set_reveal_child(True)
            self.play.seek(pos)

            self.pipeline.disconnect_by_func(setup_cb)

        self.pipeline.connect("source-setup", setup_cb)

    def save_screenshot(self) -> None:
        """
        Saves a screenshot of the current frame of the video being played in PNG format.

        It tries saving it to `xdg-pictures/Screenshot` and falls back to `~`.
        """

        if not (paintable := self.picture.get_paintable()):
            return

        if not (texture := screenshot(paintable, self)):
            return

        if pictures := GLib.get_user_special_dir(GLib.USER_DIRECTORY_PICTURES):
            path = GLib.build_pathv(sep, (pictures, "Screenshots"))
        else:
            path = GLib.get_home_dir()

        title = get_title(self.play.get_media_info()) or _("Unknown Title")

        timestamp = nanoseconds_to_timestamp(self.play.get_position())

        path = GLib.build_pathv(
            sep,
            (path, f"{Path(title).stem} {timestamp}.png"),
        )

        texture.save_to_png(path)

        toast = Adw.Toast.new(_("Screenshot captured"))
        toast.set_priority(Adw.ToastPriority.HIGH)
        toast.set_button_label(_("Show in Files"))
        toast.connect(
            "button-clicked",
            lambda *_: Gtk.FileLauncher.new(
                Gio.File.new_for_path(path)
            ).open_containing_folder(),
        )

        self.toast_overlay.add_toast(toast)

    def unpause(self) -> None:
        """Starts playing the current video."""
        self.restore_revealer.set_reveal_child(False)
        self.play.play()

    def pause(self, *_args: Any) -> None:
        """Pauses the currently playing video."""
        self.play.pause()

    def toggle_playback(self) -> None:
        """Pauses/unpauses the currently playing video."""
        (self.unpause if self.paused else self.pause)()

    def toggle_mute(self) -> None:
        """Mutes/unmutes the player."""
        self.play.set_mute(muted := not self.play.get_mute())
        self.__set_volume_icons(muted)

    def toggle_fullscreen(self) -> None:
        """Fullscreens `self` if not already in fullscreen, otherwise unfullscreens."""
        if self.is_fullscreen():
            self.unfullscreen()
            return

        self.fullscreen()

    def __choose_video_cb(self, dialog: Gtk.FileDialog, res: Gio.AsyncResult) -> None:
        try:
            if not (gfile := dialog.open_finish(res)):
                return

        except GLib.Error:
            return

        if app := self.get_application():
            app.save_play_position(self)

        self.play_video(gfile)

    def choose_video(self) -> None:
        """Opens a file dialog to pick a video to play."""
        dialog = Gtk.FileDialog()

        file_filter = Gtk.FileFilter()
        file_filter.add_mime_type("video/*")
        file_filter.set_name(_("Video"))

        filters = Gio.ListStore()
        filters.append(file_filter)
        dialog.set_filters(filters)
        dialog.set_default_filter(file_filter)

        dialog.open(self, callback=self.__choose_video_cb)

    def choose_subtitles(
        self,
    ) -> None:
        """Opens a file dialog to pick a subtitle."""
        dialog = Gtk.FileDialog()

        file_filter = Gtk.FileFilter()
        file_filter.add_mime_type("application/x-subrip")
        file_filter.add_mime_type("text/x-ssa")
        file_filter.set_name(_("Subtitles"))

        filters = Gio.ListStore()
        filters.append(file_filter)
        dialog.set_filters(filters)
        dialog.set_default_filter(file_filter)

        dialog.open(self, callback=self.__choose_subtitles_cb)

    def __choose_subtitles_cb(
        self, dialog: Gtk.FileDialog, res: Gio.AsyncResult
    ) -> None:
        try:
            if not (gfile := dialog.open_finish(res)):
                return

        except GLib.Error:
            return

        self.play.set_subtitle_uri(gfile.get_uri())
        self.__select_subtitles(0)

    def __select_subtitles(self, index: int) -> None:
        if not (app := self.get_application()):
            return

        app.lookup_action("select-subtitles").activate(GLib.Variant.new_uint16(index))

    def select_subtitles(self, action: Gio.SimpleAction, state: GLib.Variant) -> None:
        """Selects the given subtitles for the video."""
        action.set_state(state)
        if (index := state.get_uint16()) == shared.MAX_UINT16:
            self.play.set_subtitle_track_enabled(False)
            return

        self.play.set_subtitle_track(index)
        self.play.set_subtitle_track_enabled(True)

    def select_language(self, action: Gio.SimpleAction, state: GLib.Variant) -> None:
        """Selects the given language for the video."""
        action.set_state(state)
        self.play.set_audio_track(state.get_uint16())

    def build_menus(self, media_info: GstPlay.PlayMediaInfo) -> None:
        """(Re)builds the Subtitles and Language menus for the currently playing video."""
        self.menus_building -= 1

        # Don't try to rebuild the menu multiple times when the media info has many changes
        if self.menus_building > 1:
            return

        self.language_menu.remove_all()
        self.subtitles_menu.remove_all()

        langs = 0
        for index, stream in enumerate(media_info.get_audio_streams()):
            self.language_menu.append(
                stream.get_language()
                # Translators: The variable is the number of channels in an audio track
                or _("Undetermined, {} Channels").format(channels)
                if (channels := stream.get_channels()) > 0
                else _("Undetermined"),
                f"app.select-language(uint16 {index})",
            )
            langs += 1

        if not langs:
            self.language_menu.append(_("No Audio"), "nonexistent.action")
            # HACK: This is to make the item insensitive
            # I don't know if there is a better way to do this

        self.subtitles_menu.append(
            _("None"), f"app.select-subtitles(uint16 {shared.MAX_UINT16})"
        )

        subs = 0
        for index, stream in enumerate(media_info.get_subtitle_streams()):
            self.subtitles_menu.append(
                stream.get_language() or _("Undetermined Language"),
                f"app.select-subtitles(uint16 {index})",
            )
            subs += 1

        if not subs:
            self.__select_subtitles(shared.MAX_UINT16)

        self.subtitles_menu.append("Add Subtitle File…", "app.choose-subtitles")

    def __set_volume_icons(
        self, muted: Optional[bool] = None, volume: Optional[float] = None
    ) -> None:
        if muted is None:
            muted = self.play.get_mute()

        if volume is None:
            volume = self.play.get_volume()

        self.volume_button.set_icon_name(
            "audio-volume-muted-symbolic"
            if muted
            else "multimedia-volume-control-symbolic"
        )
        self.volume_menu_button.set_icon_name(
            "audio-volume-muted-symbolic"
            if muted
            else "audio-volume-high-symbolic"
            if volume > 0.7
            else "audio-volume-medium-symbolic"
            if volume > 0.3
            else "audio-volume-low-symbolic",
        )

    def __get_previous_play_position(self) -> Optional[float]:
        if not (uri := self.play.get_uri()):
            return None

        try:
            hist_file = (shared.cache_path / "playback_history").open("rb")
        except FileNotFoundError:
            return None

        try:
            hist = pickle.load(hist_file)
        except EOFError:
            return None

        hist_file.close()

        return hist.get(sha256(uri.encode("utf-8")).hexdigest())

    def __resize_window(self, video_width: int, video_height: int) -> None:
        # Make the window 3/5ths of the display height
        if not (
            monitor := self.props.display.get_monitor_at_surface(self.get_surface())
        ):
            return

        height = monitor.get_geometry().height * 0.6
        width = height * (video_width / video_height)

        init_width, init_height = self.get_default_size()

        for prop, init, target in (
            ("default-width", init_width, int(width)),
            ("default-height", init_height, int(height)),
        ):
            anim = Adw.TimedAnimation.new(
                self, init, target, 500, Adw.PropertyAnimationTarget.new(self, prop)
            )
            anim.set_easing(Adw.Easing.EASE_OUT_EXPO)
            anim.play()

    @Gtk.Template.Callback()
    def _resume(self, *_args: Any) -> None:
        self.unpause()

    @Gtk.Template.Callback()
    def _play_again(self, *_args: Any) -> None:
        self.play.seek(0)
        self.unpause()

    @Gtk.Template.Callback()
    def _set_rate(self, button: Gtk.ToggleButton) -> None:
        match button.get_label():
            case "0.5×":
                self.rate = 0.5
            case "1.25×":
                self.rate = 1.25
            case "1.5×":
                self.rate = 1.5
            case "2.0×":
                self.rate = 2
            case _:
                self.rate = 1

    def __on_stack_child_changed(self, *_args: Any) -> None:
        # HACK
        self.__on_motion(None, 0, 0)
        self.reveal_timestamp = 0

        # TODO: Make this per-window instead of app-wide
        if (self.stack.get_visible_child() != self.video_page) or not (
            app := self.get_application()
        ):
            return

        app.lookup_action("screenshot").set_enabled(True)
        app.lookup_action("show-in-files").set_enabled(True)

    def __on_primary_click_released(
        self,
        gesture: Gtk.Gesture,
        n: int,
        _x: int,
        _y: int,
    ) -> None:
        gesture.set_state(Gtk.EventSequenceState.CLAIMED)

        self.toggle_playback()

        if not n % 2:
            self.toggle_fullscreen()

    def __on_secondary_click_pressed(
        self,
        gesture: Gtk.Gesture,
        _n: Any,
        x: int,
        y: int,
    ) -> None:
        gesture.set_state(Gtk.EventSequenceState.CLAIMED)

        self.context_menu_popover.unparent()
        self.context_menu_popover.set_parent(self)

        rectangle = Gdk.Rectangle()
        rectangle.x, rectangle.y, rectangle.width, rectangle.height = x, y, 0, 0
        self.context_menu_popover.set_pointing_to(rectangle)
        self.context_menu_popover.popup()

    def __on_fullscreen(self, *_args: Any) -> None:
        self.button_fullscreen.set_icon_name(
            "view-restore-symbolic"
            if self.is_fullscreen()
            else "view-fullscreen-symbolic"
        )

    def __hide_revealers(self, timestamp: int) -> None:
        if timestamp != self.reveal_timestamp:
            return

        for motion in self.overlay_motions:
            if motion.contains_pointer():
                return

        for button in self.overlay_menu_buttons:
            if button.get_active():
                return

        for revealer in self.overlay_revealers:
            revealer.set_reveal_child(False)

        if not self.picture_motion.contains_pointer():
            return

        self.set_cursor_from_name("none")

    def __on_motion(
        self, _obj: Any, x: Optional[float] = None, y: Optional[float] = None
    ) -> None:
        # TODO: Optimize this
        if None not in (x, y):
            if (x, y) == self.prev_motion_xy:
                return

            self.prev_motion_xy = (x, y)

        self.set_cursor_from_name(None)

        for revealer in self.overlay_revealers:
            revealer.set_reveal_child(True)

        self.reveal_timestamp = (timestamp := time())
        GLib.timeout_add_seconds(2, self.__hide_revealers, timestamp)
