"""Waveform peak pyramid and its disk cache (REIMPLEMENTATION.md §4.4 "Peak cache", §6.5).

The audio of a media file is decoded once with PyAV, streaming, into ``(min, max)`` pairs per
channel at 256 samples per bucket. Each coarser level covers 4 buckets of the level below
(1024, 4096, 16384 ... samples) and is built from that level, never by decoding again. The
pyramid stops at the first level with a single bucket.

No Qt here: the UI runs `compute_peaks` in a worker thread and passes a progress callback and a
cancel flag. Results are cached on disk, keyed by (absolute path, size, mtime, stream index).
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import os
import sys
import tempfile
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import av
import numpy as np
from numpy.typing import NDArray

BASE_BUCKET = 256
"""Samples per bucket at level 0."""

LEVEL_FACTOR = 4
"""Each level has one bucket for every ``LEVEL_FACTOR`` buckets of the level below."""

CACHE_VERSION = 1
"""Bumped when the cache layout or the peak computation changes, so old entries miss."""

APP_DIR_NAME = "elan-ng"

Peaks = NDArray[np.float32]
ProgressCallback = Callable[[float], None]
CancelCheck = Callable[[], bool]


class PeaksCancelled(Exception):
    """`compute_peaks` was stopped by its cancel check. No cache entry was written."""


class NoAudioStream(ValueError):
    """The file has no audio stream with the requested index."""


@dataclass(frozen=True)
class PeakLevel:
    """One level of the pyramid. ``mins`` and ``maxs`` have shape ``(channels, buckets)``."""

    samples_per_bucket: int
    mins: Peaks
    maxs: Peaks

    @property
    def n_buckets(self) -> int:
        return int(self.mins.shape[1])


@dataclass(frozen=True)
class PeakPyramid:
    """All levels for one audio stream, finest first. Sample values are floats in [-1, 1]."""

    sample_rate: int
    channels: int
    n_samples: int
    levels: tuple[PeakLevel, ...]

    def level_for(self, samples_per_pixel: float) -> PeakLevel:
        """Return the coarsest level whose buckets are no wider than ``samples_per_pixel``."""
        best = self.levels[0]
        for level in self.levels:
            if level.samples_per_bucket <= samples_per_pixel:
                best = level
        return best


# --- computation -------------------------------------------------------------------------


def compute_peaks(
    path: str | os.PathLike[str],
    stream_index: int = 0,
    progress: ProgressCallback | None = None,
    cancel: CancelCheck | None = None,
    *,
    cache_root: Path | None = None,
    use_cache: bool = True,
) -> PeakPyramid:
    """Return the peak pyramid of audio stream ``stream_index`` of ``path``.

    ``stream_index`` counts audio streams only (0 is the first audio stream). With ``use_cache``
    a valid cache entry is loaded without decoding; otherwise the file is decoded once and the
    result is written to the cache. ``progress(fraction)`` gets increasing values that end at
    1.0. When ``cancel()`` returns True, `PeaksCancelled` is raised and nothing is cached.
    """
    source = Path(path).resolve()
    _check_cancel(cancel, source)
    entry: Path | None = None
    if use_cache:
        entry = cache_entry_path(source, stream_index, cache_root)
        cached = load_cached(entry)
        if cached is not None:
            if progress is not None:
                progress(1.0)
            return cached

    pyramid = _decode_pyramid(source, stream_index, progress, cancel)
    _check_cancel(cancel, source)  # a request during the last frames still wins over caching
    if entry is not None:
        store_cached(entry, pyramid)
    if progress is not None:
        progress(1.0)
    return pyramid


def _check_cancel(cancel: CancelCheck | None, source: Path) -> None:
    if cancel is not None and cancel():
        raise PeaksCancelled(str(source))


def build_levels(level0_mins: Peaks, level0_maxs: Peaks) -> tuple[PeakLevel, ...]:
    """Build the pyramid from level 0 by reducing groups of ``LEVEL_FACTOR`` buckets."""
    levels = [PeakLevel(BASE_BUCKET, level0_mins, level0_maxs)]
    while levels[-1].n_buckets > 1:
        prev = levels[-1]
        starts = np.arange(0, prev.n_buckets, LEVEL_FACTOR)
        mins = np.minimum.reduceat(prev.mins, starts, axis=1)
        maxs = np.maximum.reduceat(prev.maxs, starts, axis=1)
        levels.append(PeakLevel(prev.samples_per_bucket * LEVEL_FACTOR, mins, maxs))
    return tuple(levels)


def _decode_pyramid(
    source: Path,
    stream_index: int,
    progress: ProgressCallback | None,
    cancel: CancelCheck | None,
) -> PeakPyramid:
    with av.open(str(source)) as container:
        audio_streams = container.streams.audio
        if not 0 <= stream_index < len(audio_streams):
            raise NoAudioStream(f"{source} has no audio stream {stream_index}")
        stream = audio_streams[stream_index]
        sample_rate = int(stream.rate)
        channels = int(stream.channels)
        total_s = _duration_seconds(container, stream)
        resampler = av.AudioResampler(format="fltp", layout=stream.layout, rate=sample_rate)

        pending = np.zeros((channels, 0), dtype=np.float32)
        min_chunks: list[Peaks] = []
        max_chunks: list[Peaks] = []
        n_samples = 0
        last_fraction = 0.0

        def consume(data: Peaks) -> None:
            nonlocal pending, n_samples
            n_samples += data.shape[1]
            joined = np.concatenate((pending, data), axis=1) if pending.shape[1] else data
            n_full = joined.shape[1] // BASE_BUCKET
            if n_full:
                blocks = joined[:, : n_full * BASE_BUCKET].reshape(channels, n_full, BASE_BUCKET)
                min_chunks.append(blocks.min(axis=2))
                max_chunks.append(blocks.max(axis=2))
            pending = joined[:, n_full * BASE_BUCKET :]

        for frame in container.decode(stream):
            _check_cancel(cancel, source)
            for out in resampler.resample(frame):
                consume(np.asarray(out.to_ndarray(), dtype=np.float32))
            if progress is not None and total_s and frame.time is not None:
                fraction = min(float(frame.time) / total_s, 0.99)
                if fraction > last_fraction:
                    last_fraction = fraction
                    progress(fraction)
        for out in resampler.resample(None):
            consume(np.asarray(out.to_ndarray(), dtype=np.float32))

    if pending.shape[1]:
        min_chunks.append(pending.min(axis=1, keepdims=True))
        max_chunks.append(pending.max(axis=1, keepdims=True))
    if min_chunks:
        mins = np.ascontiguousarray(np.concatenate(min_chunks, axis=1), dtype=np.float32)
        maxs = np.ascontiguousarray(np.concatenate(max_chunks, axis=1), dtype=np.float32)
    else:  # an audio stream with no samples
        mins = np.zeros((channels, 0), dtype=np.float32)
        maxs = np.zeros((channels, 0), dtype=np.float32)
    levels = build_levels(mins, maxs) if mins.shape[1] else (PeakLevel(BASE_BUCKET, mins, maxs),)
    return PeakPyramid(sample_rate, channels, n_samples, levels)


def _duration_seconds(container: av.container.InputContainer, stream: av.AudioStream) -> float:
    if stream.duration is not None and stream.time_base is not None:
        return float(stream.duration * stream.time_base)
    if container.duration is not None:
        return container.duration / av.time_base
    return 0.0


# --- cache -------------------------------------------------------------------------------


def default_cache_root() -> Path:
    """Return the per-user cache directory for peak files (created on first write).

    Windows ``%LOCALAPPDATA%``, macOS ``~/Library/Caches``, otherwise ``$XDG_CACHE_HOME`` or
    ``~/.cache``; each with ``elan-ng/peaks`` below it.
    """
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / APP_DIR_NAME / "Cache" / "peaks"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / APP_DIR_NAME / "peaks"
    xdg = os.environ.get("XDG_CACHE_HOME")
    base_path = Path(xdg) if xdg and Path(xdg).is_absolute() else Path.home() / ".cache"
    return base_path / APP_DIR_NAME / "peaks"


def cache_key(source: Path, stream_index: int) -> str:
    """Hash of (absolute path, size, mtime, stream index, cache version)."""
    st = source.stat()
    raw = f"{source.resolve()}\0{st.st_size}\0{st.st_mtime_ns}\0{stream_index}\0{CACHE_VERSION}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def cache_entry_path(source: Path, stream_index: int, cache_root: Path | None = None) -> Path:
    root = cache_root if cache_root is not None else default_cache_root()
    return root / f"{cache_key(source, stream_index)}.npz"


def store_cached(entry: Path, pyramid: PeakPyramid) -> None:
    """Write ``pyramid`` atomically (temp file in the same directory, then rename).

    The entry is an uncompressed ``.npz``: a zip of plain ``.npy`` arrays, one per level and
    side, read back without pickle. Write errors are ignored; the cache is only an optimization.
    """
    arrays: dict[str, NDArray[np.generic]] = {
        "meta": np.array(
            [CACHE_VERSION, pyramid.sample_rate, pyramid.channels, pyramid.n_samples],
            dtype=np.int64,
        )
    }
    for i, level in enumerate(pyramid.levels):
        arrays[f"min{i}"] = level.mins
        arrays[f"max{i}"] = level.maxs
    tmp_name: str | None = None
    try:
        entry.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=entry.parent, prefix=entry.stem, suffix=".tmp")
        with os.fdopen(fd, "wb") as fh:
            np.savez(fh, allow_pickle=False, **arrays)
        os.replace(tmp_name, entry)
        tmp_name = None
    except OSError:
        pass
    finally:
        if tmp_name is not None:
            Path(tmp_name).unlink(missing_ok=True)


def load_cached(entry: Path) -> PeakPyramid | None:
    """Load a cache entry, or return None when it is missing, partial or corrupt.

    A bad entry is deleted so the next computation can replace it.
    """
    if not entry.is_file():
        return None
    try:
        # Parse from memory: np.load keeps the file open when a zip is truncated, and an open
        # file cannot be deleted on Windows.
        loaded = np.load(io.BytesIO(entry.read_bytes()), allow_pickle=False)
        if not isinstance(loaded, np.lib.npyio.NpzFile):  # e.g. a plain .npy at this path
            raise ValueError("not an .npz archive")
        with loaded as data:
            meta = data["meta"]
            if meta.shape != (4,) or meta.dtype.kind not in "iu" or int(meta[0]) != CACHE_VERSION:
                raise ValueError("cache version")
            sample_rate, channels, n_samples = (int(v) for v in meta[1:])
            levels: list[PeakLevel] = []
            i = 0
            while f"min{i}" in data.files:
                mins = np.asarray(data[f"min{i}"], dtype=np.float32)
                maxs = np.asarray(data[f"max{i}"], dtype=np.float32)
                levels.append(PeakLevel(BASE_BUCKET * LEVEL_FACTOR**i, mins, maxs))
                i += 1
        _validate(levels, sample_rate, channels, n_samples)
        return PeakPyramid(sample_rate, channels, n_samples, tuple(levels))
    except (OSError, ValueError, TypeError, OverflowError, KeyError, EOFError, zipfile.BadZipFile):
        with contextlib.suppress(OSError):
            entry.unlink(missing_ok=True)
        return None


def _validate(levels: list[PeakLevel], sample_rate: int, channels: int, n_samples: int) -> None:
    """Reject entries that could not have come from `compute_peaks`."""
    if sample_rate <= 0 or channels <= 0 or n_samples < 0 or not levels:
        raise ValueError("bad metadata")
    for level in levels:
        expected = -(-n_samples // level.samples_per_bucket)
        shape = (channels, expected)
        if level.mins.shape != shape or level.maxs.shape != shape:
            raise ValueError("level shape")
        if not (np.isfinite(level.mins).all() and np.isfinite(level.maxs).all()):
            raise ValueError("non-finite peak")
        if (level.mins > level.maxs).any():
            raise ValueError("min above max")
    if n_samples and levels[-1].n_buckets != 1:
        raise ValueError("pyramid incomplete")
    if n_samples:
        rebuilt = build_levels(levels[0].mins, levels[0].maxs)
        if len(rebuilt) != len(levels) or not all(
            np.array_equal(a.mins, b.mins) and np.array_equal(a.maxs, b.maxs)
            for a, b in zip(rebuilt, levels, strict=True)
        ):
            raise ValueError("coarse levels do not match level 0")
