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


RATES_ALLOWED = (0.5, 1.0, 1.25, 1.5, 2.0)
MIN_RATE = RATES_ALLOWED[0]
MAX_RATE = RATES_ALLOWED[-1]


class PlaybackState(GObject.Object):
    """Represents the playback state of a media item."""

    __gtype_name__ = "PlaybackState"

    volume = GObject.Property(type=float, default=1.0)  # Using cubic scale
    state = GObject.Property(type=GstPlay.PlayState, default=GstPlay.PlayState.STOPPED)
    media_info = GObject.Property(type=object, default=None)
    position = GObject.Property(
        type=GObject.TYPE_INT64, default=0
    )  # Position in nanoseconds
    rate = GObject.Property(type=float, default=1.0)

    seeked = GObject.Signal(name="seeked", arg_types=(GObject.TYPE_INT64,))

    def is_playing(self) -> bool:
        """Check if the media is currently playing."""
        return self.state == GstPlay.PlayState.PLAYING

    def get_duration(self) -> int | None:
        """Get the duration of the media in nanoseconds."""
        return self.media_info.length if self.media_info else None

    def get_next_step_rate(self, step: int) -> float:
        """Get the next playback rate based on the given step."""
        current = self.rate if self.rate in RATES_ALLOWED else 1.0
        index = RATES_ALLOWED.index(current)
        return RATES_ALLOWED[max(0, min(index + step, len(RATES_ALLOWED) - 1))]

    def set_rate(self, rate: float) -> float:
        """Set the playback rate to the closest allowed value."""
        closest_rate = min(RATES_ALLOWED, key=lambda r: abs(r - rate))
        self.rate = closest_rate
        return closest_rate
