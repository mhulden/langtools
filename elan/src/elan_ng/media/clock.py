"""Document-time clock driven by the master backend (REIMPLEMENTATION.md §4.5).

Pure Python: no Qt. A UI timer calls `tick()` at display refresh while playing.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from elan_ng.media.service import MediaService

TickListener = Callable[[float], None]


class MediaClock:
    """Document time while playing (extrapolated from the master) or paused (frozen)."""

    def __init__(
        self,
        service: MediaService,
        now: Callable[[], float] = time.monotonic,
        frame_ms: float = 40.0,
    ) -> None:
        self.service = service
        self.frame_ms = frame_ms
        self.playing = False
        self.rate = 1.0
        self.selection_end: float | None = None
        self.loop_start: float | None = None
        self._now = now
        self._listeners: list[TickListener] = []
        self._t = 0.0  # last known document time, used while paused
        self._anchor_t = 0.0  # document time at the anchor wall time (seconds)
        self._anchor_wall = 0.0
        self._last_pos: float | None = None  # last master document position seen
        self._last_returned: float | None = None  # monotonic guard while playing

    def add_tick_listener(self, cb: TickListener) -> None:
        """Register a callback that receives document time on each notification."""
        self._listeners.append(cb)

    def remove_tick_listener(self, cb: TickListener) -> None:
        """Unregister a callback; unknown callbacks are ignored."""
        if cb in self._listeners:
            self._listeners.remove(cb)

    def time_ms(self) -> float:
        """Current document time in ms; while playing it never goes backwards (except on seek)."""
        if not self.playing:
            return self._t
        master_t = self.service.document_position_ms()
        low = master_t - self.frame_ms
        high = master_t + self.frame_ms
        if master_t != self._last_pos:
            # New backend report: re-anchor on the old extrapolation (clamped), not on the
            # report itself, so a lagging report cannot pull the clock backwards.
            self._last_pos = master_t
            self._set_anchor(min(max(self._extrapolate(), low), high))
        t = min(max(self._extrapolate(), low), high)
        if self._last_returned is not None:
            t = max(t, self._last_returned)
        self._last_returned = t
        return t

    def _extrapolate(self) -> float:
        elapsed_ms = (self._now() - self._anchor_wall) * 1000.0
        return self._anchor_t + elapsed_ms * self.rate

    def tick(self) -> float:
        """Advance one display frame: apply selection rules and notify listeners while playing."""
        if not self.playing:
            return self._t
        t = self.time_ms()
        end = self.selection_end
        if end is not None and t >= end:
            if self.loop_start is not None:
                t = self.loop_start
                self._jump(t)
            else:
                self.playing = False
                self.service.pause()
                self._jump(end)
                self.selection_end = None
                self.loop_start = None
                t = end
        self._t = t
        self._notify(t)
        return t

    def play(self) -> None:
        """Start playback from the current time."""
        if self.playing:
            return
        self.playing = True
        self._last_returned = None
        self._set_anchor(self._t)
        self._last_pos = self.service.document_position_ms()
        self.service.play()

    def pause(self) -> None:
        """Pause playback and freeze the current time."""
        if not self.playing:
            return
        self._t = self.time_ms()
        self.playing = False
        self.service.pause()

    def seek(self, doc_ms: float) -> None:
        """Seek to document time, clamped to [0, duration]; notifies listeners once."""
        t = max(0.0, doc_ms)
        duration = self.service.duration_ms()
        if duration is not None:
            t = min(t, duration)
        self._jump(t)
        self._notify(t)

    def set_rate(self, rate: float) -> None:
        """Set the playback rate; must be positive."""
        if rate <= 0:
            raise ValueError(f"rate must be positive, got {rate}")
        if self.playing:
            # Re-anchor at the current time so the old rate does not apply retroactively.
            self._set_anchor(self.time_ms())
        self.rate = rate
        self.service.set_rate(rate)

    def play_selection(self, begin_ms: float, end_ms: float, loop: bool = False) -> None:
        """Seek to `begin_ms` and play until `end_ms`, pausing there or looping back."""
        if end_ms <= begin_ms:
            raise ValueError(f"selection end {end_ms} must be after begin {begin_ms}")
        self.seek(begin_ms)
        self.selection_end = end_ms
        self.loop_start = begin_ms if loop else None
        self.play()

    def stop_selection(self) -> None:
        """Clear the selection and loop state; playback continues."""
        self.selection_end = None
        self.loop_start = None

    def _set_anchor(self, t: float) -> None:
        self._anchor_t = t
        self._anchor_wall = self._now()

    def _jump(self, doc_ms: float) -> None:
        """Seek the service and re-anchor without notifying listeners."""
        self.service.seek(doc_ms)
        self._t = doc_ms
        self._last_returned = None
        self._set_anchor(doc_ms)
        self._last_pos = self.service.document_position_ms()

    def _notify(self, t: float) -> None:
        for cb in list(self._listeners):
            cb(t)
