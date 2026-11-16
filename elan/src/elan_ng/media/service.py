"""Master and slave media coordination in document time (REIMPLEMENTATION.md §4.5).

Pure Python: no Qt, no PyAV, no numpy. The UI drives `MediaService.sync_slaves` from a timer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


class MediaBackend(Protocol):
    """Playback engine for one media file. All times are media time in milliseconds."""

    def position_ms(self) -> float:
        """Current media position."""
        ...

    def duration_ms(self) -> float | None:
        """Media duration, or None when unknown."""
        ...

    def play(self) -> None:
        """Start playback at the current rate."""
        ...

    def pause(self) -> None:
        """Pause playback."""
        ...

    def seek(self, media_ms: float) -> None:
        """Move to a media position."""
        ...

    def set_rate(self, rate: float) -> None:
        """Set the playback rate (1.0 is normal speed)."""
        ...

    def set_muted(self, muted: bool) -> None:
        """Mute or unmute the audio output."""
        ...


@dataclass(frozen=True)
class SyncSettings:
    """Tolerances for keeping slaves aligned with the master."""

    check_interval_ms: float = 500.0
    reseek_drift_ms: float = 40.0
    nudge_drift_ms: float = 10.0
    nudge_ratio: float = 0.02


@dataclass
class Slave:
    """A secondary media file. Its media time is document time plus `offset_ms`."""

    backend: MediaBackend
    offset_ms: float = 0.0
    video_only: bool = False
    rate: float | None = field(default=None, init=False, repr=False)  # last rate applied


_DEFAULT_SETTINGS = SyncSettings()


class MediaService:
    """Drives the master backend and keeps slave backends at their document-time targets."""

    def __init__(
        self,
        master: MediaBackend,
        master_offset_ms: float = 0.0,
        settings: SyncSettings = _DEFAULT_SETTINGS,
    ) -> None:
        self.master = master
        self.master_offset_ms = master_offset_ms
        self.settings = settings
        self.slaves: list[Slave] = []
        self.playing = False
        self.base_rate = 1.0

    def add_slave(self, slave: Slave) -> None:
        """Add a slave and align it: mute if video-only, seek to its target, set rate, play."""
        self.slaves.append(slave)
        slave.backend.set_muted(slave.video_only)
        target = self.document_position_ms() + slave.offset_ms
        slave.backend.seek(self._clamp_media(slave.backend, target))
        self._apply_rate(slave, self.base_rate)
        if self.playing:
            slave.backend.play()

    def play(self) -> None:
        """Play the master and all slaves."""
        self.master.play()
        for slave in self.slaves:
            slave.backend.play()
        self.playing = True

    def pause(self) -> None:
        """Pause the master and all slaves."""
        self.master.pause()
        for slave in self.slaves:
            slave.backend.pause()
        self.playing = False

    def seek(self, doc_ms: float) -> None:
        """Seek every backend to document time `doc_ms`, clamped to that backend's duration."""
        self.master.seek(self._clamp_media(self.master, doc_ms + self.master_offset_ms))
        for slave in self.slaves:
            slave.backend.seek(self._clamp_media(slave.backend, doc_ms + slave.offset_ms))

    def set_rate(self, rate: float) -> None:
        """Set the base rate on all backends."""
        self.base_rate = rate
        self.master.set_rate(rate)
        for slave in self.slaves:
            self._apply_rate(slave, rate)

    @staticmethod
    def _apply_rate(slave: Slave, rate: float) -> None:
        """Set a slave's rate only when it differs from the one last applied."""
        if slave.rate != rate:
            slave.backend.set_rate(rate)
            slave.rate = rate

    @staticmethod
    def _clamp_media(backend: MediaBackend, media_ms: float) -> float:
        """Clamp a media target to [0, backend duration]; the upper bound applies when known."""
        target = max(0.0, media_ms)
        duration = backend.duration_ms()
        if duration is not None:
            target = min(target, duration)
        return target

    def document_position_ms(self) -> float:
        """Master position in document time."""
        return self.master.position_ms() - self.master_offset_ms

    def master_end_ms(self) -> float | None:
        """Master end in document time (its duration minus its offset), or None if unknown."""
        duration = self.master.duration_ms()
        return None if duration is None else duration - self.master_offset_ms

    def duration_ms(self) -> float | None:
        """Document length in document time.

        Policy (REIMPLEMENTATION.md §2.3): the maximum over the master and every slave of
        (backend duration - its offset), counting only backends whose duration is known.
        None when no backend reports a duration.
        """
        ends: list[float] = []
        master_end = self.master_end_ms()
        if master_end is not None:
            ends.append(master_end)
        for slave in self.slaves:
            duration = slave.backend.duration_ms()
            if duration is not None:
                ends.append(duration - slave.offset_ms)
        return max(ends) if ends else None

    def master_at_end(self) -> bool:
        """True when the master backend is at (within 1 ms of) its own end."""
        duration = self.master.duration_ms()
        return duration is not None and self.master.position_ms() >= duration - 1.0

    def sync_slaves(self) -> None:
        """Correct each slave's drift: re-seek when large, nudge the rate when small.

        Once the master has reached its end it is no longer a time reference (the document
        can be longer, §2.3), so slaves are not re-seeked; they run freely at the base rate
        (any drift nudge is undone) until the next seek.
        """
        if self.master_at_end():
            for slave in self.slaves:
                self._apply_rate(slave, self.base_rate)
            return
        doc_t = self.document_position_ms()
        cfg = self.settings
        for slave in self.slaves:
            target = self._clamp_media(slave.backend, doc_t + slave.offset_ms)
            drift = slave.backend.position_ms() - target
            size = abs(drift)
            if size > cfg.reseek_drift_ms:
                slave.backend.seek(target)
                self._apply_rate(slave, self.base_rate)
            elif size > cfg.nudge_drift_ms and self.playing:
                # Ahead of the target: slow down. Behind: speed up.
                factor = 1.0 - cfg.nudge_ratio if drift > 0 else 1.0 + cfg.nudge_ratio
                self._apply_rate(slave, self.base_rate * factor)
            else:
                self._apply_rate(slave, self.base_rate)
