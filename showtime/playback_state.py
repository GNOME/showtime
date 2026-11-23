from dataclasses import dataclass

from gi.repository import GObject, GstPlay  # pyright: ignore[reportAttributeAccessIssue]


@dataclass(frozen=True)
class MediaInfo:
    """Represents media information for a media item."""

    uri: str
    title: str
    length: int | None  # Length in nanoseconds

    def with_length(self, length: int | None) -> "MediaInfo":
        """Return a new MediaInfo instance with the specified length."""
        return MediaInfo(uri=self.uri, title=self.title, length=length)


class PlaybackState(GObject.Object):
    """Represents the playback state of a media item."""

    __gtype_name__ = "PlaybackState"

    volume = GObject.Property(type=float, default=1.0)  # Using cubic scale
    state = GObject.Property(type=GstPlay.PlayState, default=GstPlay.PlayState.STOPPED)
    media_info = GObject.Property(type=object, default=None)
    position = GObject.Property(
        type=GObject.TYPE_INT64, default=0
    )  # Position in nanoseconds

    seeked = GObject.Signal(name="seeked", arg_types=(GObject.TYPE_INT64,))

    def get_duration(self) -> int | None:
        """Get the duration of the media in nanoseconds."""
        return self.media_info.length if self.media_info else None
