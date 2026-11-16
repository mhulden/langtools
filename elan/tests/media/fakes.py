"""Test doubles for the media layer: a controllable clock and a simulated playback backend."""

from __future__ import annotations

import math


class FakeTime:
    """Wall clock in seconds that moves only when a test advances it."""

    def __init__(self, t: float = 0.0) -> None:
        self.t = t

    def now(self) -> float:
        """Current fake time in seconds (usable as a clock's `now`)."""
        return self.t

    def advance(self, ms: float) -> None:
        """Move time forward by `ms` milliseconds."""
        self.t += ms / 1000.0


class FakeBackend:
    """Simulated playback engine. While playing, its position follows the shared FakeTime."""

    def __init__(
        self,
        time: FakeTime,
        *,
        duration: float | None = 10_000.0,
        start_ms: float = 0.0,
        step_ms: float = 0.0,
        drift_per_s_ms: float = 0.0,
    ) -> None:
        self.time = time
        self.duration = duration
        self.step_ms = step_ms  # > 0: position reports are quantized to this step (coarse)
        self.drift_per_s_ms = drift_per_s_ms  # extra media ms per second (a fast-running slave)
        self.playing = False
        self.rate = 1.0
        self.muted = False
        self.seeks: list[float] = []
        self.rates: list[float] = []
        self.mute_calls: list[bool] = []
        self._base = start_ms
        self._anchor = time.t

    def _raw(self) -> float:
        if not self.playing:
            return self._base
        elapsed = self.time.t - self._anchor
        return self._base + elapsed * (1000.0 * self.rate + self.drift_per_s_ms)

    def _rebase(self) -> None:
        self._base = self._raw()
        self._anchor = self.time.t

    def position_ms(self) -> float:
        """Reported media position (quantized when `step_ms` is set)."""
        raw = self._raw()
        if self.step_ms > 0:
            return math.floor(raw / self.step_ms) * self.step_ms
        return raw

    def duration_ms(self) -> float | None:
        """Media duration, or None when unknown."""
        return self.duration

    def play(self) -> None:
        """Start advancing the position."""
        self._rebase()
        self.playing = True

    def pause(self) -> None:
        """Freeze the position."""
        self._rebase()
        self.playing = False

    def seek(self, media_ms: float) -> None:
        """Jump to a media position and record it."""
        self.seeks.append(media_ms)
        self._base = media_ms
        self._anchor = self.time.t

    def set_rate(self, rate: float) -> None:
        """Change the rate from now on and record it."""
        self.rates.append(rate)
        self._rebase()
        self.rate = rate

    def set_muted(self, muted: bool) -> None:
        """Record the mute state."""
        self.mute_calls.append(muted)
        self.muted = muted
