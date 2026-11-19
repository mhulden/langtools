"""Peak pyramid and its disk cache (REIMPLEMENTATION.md §4.4, §6.5).

Every test passes its own ``cache_root`` under ``tmp_path``, so the real user cache is never used.
"""

from __future__ import annotations

import dataclasses
import itertools
import math
import os
import shutil
import time
import wave
from pathlib import Path
from typing import NoReturn

import numpy as np
import pytest
from mediagen import (
    TONE_AMPLITUDE,
    TONE_AMPLITUDE_RIGHT,
    TONE_MS,
    TONE_ONSETS_MS,
    WAV_DURATION_MS,
    WAV_RATE,
)

from elan_ng.media import peaks
from elan_ng.media.peaks import (
    BASE_BUCKET,
    LEVEL_FACTOR,
    NoAudioStream,
    PeakPyramid,
    PeaksCancelled,
    cache_entry_path,
    compute_peaks,
    load_cached,
    store_cached,
)

N_SAMPLES = WAV_RATE * WAV_DURATION_MS // 1000  # 144000
TONE_SAMPLES = WAV_RATE * TONE_MS // 1000  # 9600
TONE_RANGES = tuple(
    (WAV_RATE * onset // 1000, WAV_RATE * onset // 1000 + TONE_SAMPLES) for onset in TONE_ONSETS_MS
)
PEAK_TOLERANCE = 0.01

PERF_HOURS = 2
PERF_CHUNK_FRAMES = WAV_RATE * 10  # 10 s chunks
PERF_WARM_LIMIT_S = 1.0  # hard limit on the warm (cached) run
PERF_COLD_TARGET_S = 30.0  # section 6.5 target, reported only


def _assert_same_pyramid(actual: PeakPyramid, expected: PeakPyramid) -> None:
    assert actual.sample_rate == expected.sample_rate
    assert actual.channels == expected.channels
    assert actual.n_samples == expected.n_samples
    assert len(actual.levels) == len(expected.levels)
    for got, want in zip(actual.levels, expected.levels, strict=True):
        assert got.samples_per_bucket == want.samples_per_bucket
        np.testing.assert_array_equal(got.mins, want.mins)
        np.testing.assert_array_equal(got.maxs, want.maxs)


def _bucket_kind(index: int, samples_per_bucket: int) -> str:
    """Classify a bucket as "tone" (fully inside a tone), "silence" (no overlap) or "edge"."""
    lo = index * samples_per_bucket
    hi = min(lo + samples_per_bucket, N_SAMPLES)
    if any(start <= lo and hi <= end for start, end in TONE_RANGES):
        return "tone"
    if all(hi <= start or end <= lo for start, end in TONE_RANGES):
        return "silence"
    return "edge"


def _count_decodes(monkeypatch: pytest.MonkeyPatch) -> list[object]:
    """Wrap ``av.open`` so each real decode is recorded; the real function still runs."""
    calls: list[object] = []
    real_open = peaks.av.open

    def counting_open(*args: object, **kwargs: object) -> object:
        calls.append(args)
        return real_open(*args, **kwargs)

    monkeypatch.setattr(peaks.av, "open", counting_open)
    return calls


# --- levels ------------------------------------------------------------------------------


def test_mono_wav_pyramid_shape(tone_wav: Path, tmp_path: Path) -> None:
    pyramid = compute_peaks(tone_wav, cache_root=tmp_path / "cache")

    assert pyramid.sample_rate == WAV_RATE
    assert pyramid.channels == 1
    assert pyramid.n_samples == N_SAMPLES
    for i, level in enumerate(pyramid.levels):
        spb = BASE_BUCKET * LEVEL_FACTOR**i
        assert level.samples_per_bucket == spb
        assert level.mins.shape == (1, math.ceil(N_SAMPLES / spb))
        assert level.maxs.shape == level.mins.shape
        assert level.n_buckets == math.ceil(N_SAMPLES / spb)

    assert pyramid.levels[-1].n_buckets == 1
    assert all(level.n_buckets != 1 for level in pyramid.levels[:-1])


def test_silence_is_zero_and_tones_reach_half_amplitude(tone_wav: Path, tmp_path: Path) -> None:
    pyramid = compute_peaks(tone_wav, cache_root=tmp_path / "cache")

    checked_tone = checked_silence = 0
    for level in pyramid.levels:
        spb = level.samples_per_bucket
        for j in range(level.n_buckets):
            kind = _bucket_kind(j, spb)
            if kind == "silence":
                assert level.mins[0, j] == 0.0
                assert level.maxs[0, j] == 0.0
                checked_silence += 1
            elif kind == "tone":
                assert abs(float(level.maxs[0, j]) - TONE_AMPLITUDE) <= PEAK_TOLERANCE
                assert abs(float(level.mins[0, j]) + TONE_AMPLITUDE) <= PEAK_TOLERANCE
                checked_tone += 1
    # both kinds occur on level 0 (about 3 tones of 37 buckets each, the rest silence)
    assert checked_tone > 0
    assert checked_silence > 0


def test_each_level_reduces_the_level_below(tone_wav: Path, tmp_path: Path) -> None:
    pyramid = compute_peaks(tone_wav, cache_root=tmp_path / "cache")

    for k in range(1, len(pyramid.levels)):
        below = pyramid.levels[k - 1]
        level = pyramid.levels[k]
        for j in range(level.n_buckets):
            children = slice(LEVEL_FACTOR * j, LEVEL_FACTOR * (j + 1))
            np.testing.assert_array_equal(
                level.mins[:, j], below.mins[:, children].min(axis=1), err_msg=f"level {k}"
            )
            np.testing.assert_array_equal(
                level.maxs[:, j], below.maxs[:, children].max(axis=1), err_msg=f"level {k}"
            )


def test_stereo_channels_have_their_own_amplitude(stereo_tone_wav: Path, tmp_path: Path) -> None:
    pyramid = compute_peaks(stereo_tone_wav, cache_root=tmp_path / "cache")

    assert pyramid.channels == 2
    assert pyramid.n_samples == N_SAMPLES
    level = pyramid.levels[0]
    assert level.mins.shape[0] == 2
    checked = 0
    for j in range(level.n_buckets):
        kind = _bucket_kind(j, level.samples_per_bucket)
        if kind == "tone":
            assert abs(float(level.maxs[0, j]) - TONE_AMPLITUDE) <= PEAK_TOLERANCE
            assert abs(float(level.mins[0, j]) + TONE_AMPLITUDE) <= PEAK_TOLERANCE
            assert abs(float(level.maxs[1, j]) - TONE_AMPLITUDE_RIGHT) <= PEAK_TOLERANCE
            assert abs(float(level.mins[1, j]) + TONE_AMPLITUDE_RIGHT) <= PEAK_TOLERANCE
            checked += 1
        elif kind == "silence":
            assert level.mins[:, j].tolist() == [0.0, 0.0]
            assert level.maxs[:, j].tolist() == [0.0, 0.0]
    assert checked > 0


def test_aac_m4a_decodes_with_approximate_levels(tone_m4a: Path, tmp_path: Path) -> None:
    pyramid = compute_peaks(tone_m4a, cache_root=tmp_path / "cache")

    assert pyramid.channels == 1
    assert pyramid.sample_rate == 48_000
    # AAC adds encoder priming and frame padding, so the length is only approximate
    assert N_SAMPLES - 1024 <= pyramid.n_samples <= N_SAMPLES + 4096
    top = pyramid.levels[-1]
    assert top.n_buckets == 1
    assert 0.4 <= float(top.maxs.max()) <= 0.6


# --- stream selection --------------------------------------------------------------------


def test_video_only_file_has_no_audio_stream(counter_mp4: Path, tmp_path: Path) -> None:
    with pytest.raises(NoAudioStream):
        compute_peaks(counter_mp4, cache_root=tmp_path / "cache")


def test_missing_audio_stream_index_raises(tone_wav: Path, tmp_path: Path) -> None:
    with pytest.raises(NoAudioStream):
        compute_peaks(tone_wav, stream_index=1, cache_root=tmp_path / "cache")


# --- cache -------------------------------------------------------------------------------


def test_cache_hit_does_not_decode(
    tone_wav: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "cache"
    first = compute_peaks(tone_wav, cache_root=root)

    def fail_open(*args: object, **kwargs: object) -> NoReturn:
        raise AssertionError("the file was decoded although a cache entry exists")

    monkeypatch.setattr(peaks.av, "open", fail_open)
    second = compute_peaks(tone_wav, cache_root=root)
    _assert_same_pyramid(second, first)


def test_cache_miss_when_mtime_changes(
    tone_wav: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "cache"
    copy = tmp_path / "copy.wav"
    shutil.copyfile(tone_wav, copy)
    calls = _count_decodes(monkeypatch)

    compute_peaks(copy, cache_root=root)
    assert len(calls) == 1
    compute_peaks(copy, cache_root=root)
    assert len(calls) == 1  # warm hit

    st = copy.stat()
    os.utime(copy, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))
    compute_peaks(copy, cache_root=root)
    assert len(calls) == 2


def test_cache_miss_when_size_changes(
    tone_wav: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "cache"
    copy = tmp_path / "copy.wav"
    shutil.copyfile(tone_wav, copy)
    calls = _count_decodes(monkeypatch)

    compute_peaks(copy, cache_root=root)
    assert len(calls) == 1

    st = copy.stat()
    with copy.open("ab") as fh:
        fh.write(b"\x00")
    # restore the old mtime so only the size differs
    os.utime(copy, ns=(st.st_atime_ns, st.st_mtime_ns))
    assert copy.stat().st_size == st.st_size + 1

    compute_peaks(copy, cache_root=root)
    assert len(calls) == 2


def test_corrupt_cache_entry_is_replaced(tone_wav: Path, tmp_path: Path) -> None:
    root = tmp_path / "cache"
    reference = compute_peaks(tone_wav, cache_root=root)
    entry = cache_entry_path(tone_wav, 0, root)
    assert entry.is_file()

    entry.write_bytes(b"this is not an npz file" * 200)
    result = compute_peaks(tone_wav, cache_root=root)
    _assert_same_pyramid(result, reference)
    assert load_cached(entry) is not None


def test_truncated_cache_entry_is_replaced(tone_wav: Path, tmp_path: Path) -> None:
    root = tmp_path / "cache"
    reference = compute_peaks(tone_wav, cache_root=root)
    entry = cache_entry_path(tone_wav, 0, root)
    data = entry.read_bytes()
    entry.write_bytes(data[: len(data) // 2])

    result = compute_peaks(tone_wav, cache_root=root)
    _assert_same_pyramid(result, reference)
    assert load_cached(entry) is not None


def test_cache_write_is_atomic_single_file(tone_wav: Path, tmp_path: Path) -> None:
    root = tmp_path / "cache"
    compute_peaks(tone_wav, cache_root=root)

    names = sorted(p.name for p in root.iterdir())
    assert len(names) == 1
    assert names[0].endswith(".npz")
    assert list(root.glob("*.tmp")) == []


def test_progress_is_increasing_and_ends_at_one(tone_wav: Path, tmp_path: Path) -> None:
    seen: list[float] = []
    compute_peaks(
        tone_wav,
        progress=seen.append,
        cache_root=tmp_path / "cold",
    )

    assert len(seen) > 1
    assert all(0.0 < value <= 1.0 for value in seen)
    assert all(b > a for a, b in itertools.pairwise(seen))
    assert seen[-1] == 1.0


def test_cancel_raises_and_caches_nothing(tone_wav: Path, tmp_path: Path) -> None:
    root = tmp_path / "cache"
    calls = 0

    def cancel() -> bool:
        nonlocal calls
        calls += 1
        return calls == 3

    with pytest.raises(PeaksCancelled):
        compute_peaks(tone_wav, cancel=cancel, cache_root=root)
    assert calls == 3
    assert not root.exists() or list(root.glob("*.npz")) == []


def test_cancel_during_the_last_frames_still_caches_nothing(tone_wav: Path, tmp_path: Path) -> None:
    root = tmp_path / "cache"
    requested = False

    def progress(fraction: float) -> None:
        nonlocal requested
        if fraction >= 0.99:  # the final progress report, after the last cancel check in the loop
            requested = True

    with pytest.raises(PeaksCancelled):
        compute_peaks(tone_wav, progress=progress, cancel=lambda: requested, cache_root=root)
    assert requested
    assert not root.exists() or list(root.glob("*.npz")) == []


def test_cancel_before_start_wins_over_a_cache_hit(tone_wav: Path, tmp_path: Path) -> None:
    root = tmp_path / "cache"
    compute_peaks(tone_wav, cache_root=root)

    with pytest.raises(PeaksCancelled):
        compute_peaks(tone_wav, cancel=lambda: True, cache_root=root)


def _store_tampered(
    entry: Path, pyramid: PeakPyramid, mins0: np.ndarray, maxs0: np.ndarray
) -> None:
    first = dataclasses.replace(pyramid.levels[0], mins=mins0, maxs=maxs0)
    store_cached(entry, dataclasses.replace(pyramid, levels=(first, *pyramid.levels[1:])))


@pytest.mark.parametrize("damage", ["nan", "min_above_max", "coarse_mismatch"])
def test_inconsistent_cache_values_are_rebuilt(tone_wav: Path, tmp_path: Path, damage: str) -> None:
    root = tmp_path / "cache"
    reference = compute_peaks(tone_wav, cache_root=root)
    entry = cache_entry_path(tone_wav, 0, root)
    level0 = reference.levels[0]
    mins, maxs = level0.mins.copy(), level0.maxs.copy()
    if damage == "nan":
        mins[0, 0] = np.nan
    elif damage == "min_above_max":
        mins[0, 0], maxs[0, 0] = 0.5, -0.5
    else:  # a level-0 bucket that no longer matches the stored coarser levels
        maxs[0, 0] = 0.75
    _store_tampered(entry, reference, mins, maxs)
    assert load_cached(entry) is None

    _store_tampered(entry, reference, mins, maxs)
    result = compute_peaks(tone_wav, cache_root=root)
    _assert_same_pyramid(result, reference)
    assert load_cached(entry) is not None


@pytest.mark.parametrize(
    "meta",
    [
        np.array([np.inf, 48000, 1, 144000]),  # int(inf) raises OverflowError
        np.array([np.nan, 48000, 1, 144000]),
        np.array([1.0, 48000.0, 1.0, 144000.0]),  # right values, wrong dtype
        np.array([1, 48000, 1], dtype=np.int64),
    ],
    ids=["inf", "nan", "float", "short"],
)
def test_bad_cache_metadata_is_rebuilt(tone_wav: Path, tmp_path: Path, meta: np.ndarray) -> None:
    root = tmp_path / "cache"
    reference = compute_peaks(tone_wav, cache_root=root)
    entry = cache_entry_path(tone_wav, 0, root)
    with np.load(entry, allow_pickle=False) as data:
        arrays = {name: data[name] for name in data.files}
    arrays["meta"] = meta

    with entry.open("wb") as fh:
        np.savez(fh, **arrays)
    assert load_cached(entry) is None

    with entry.open("wb") as fh:
        np.savez(fh, **arrays)
    result = compute_peaks(tone_wav, cache_root=root)
    _assert_same_pyramid(result, reference)
    assert load_cached(entry) is not None


def test_plain_npy_at_the_cache_path_is_rebuilt(tone_wav: Path, tmp_path: Path) -> None:
    root = tmp_path / "cache"
    reference = compute_peaks(tone_wav, cache_root=root)
    entry = cache_entry_path(tone_wav, 0, root)
    with entry.open("wb") as fh:  # np.save on a path would append ".npy"
        np.save(fh, np.zeros(4, dtype=np.float32))

    assert load_cached(entry) is None  # also deletes the bad entry

    with entry.open("wb") as fh:
        np.save(fh, np.zeros(4, dtype=np.float32))
    result = compute_peaks(tone_wav, cache_root=root)
    _assert_same_pyramid(result, reference)
    assert load_cached(entry) is not None


# --- cache location ----------------------------------------------------------------------


def test_default_cache_root_windows(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(peaks.sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    assert peaks.default_cache_root() == tmp_path / "local" / "elan-ng" / "Cache" / "peaks"


def test_default_cache_root_macos(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(peaks.sys, "platform", "darwin")
    assert peaks.default_cache_root().parts[-4:] == ("Library", "Caches", "elan-ng", "peaks")


def test_default_cache_root_linux_uses_absolute_xdg(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(peaks.sys, "platform", "linux")
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
    assert peaks.default_cache_root() == tmp_path / "xdg" / "elan-ng" / "peaks"


def test_default_cache_root_ignores_relative_xdg(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(peaks.sys, "platform", "linux")
    monkeypatch.setenv("XDG_CACHE_HOME", "relative/cache")
    root = peaks.default_cache_root()
    assert root.is_absolute()
    assert "relative" not in root.parts
    assert root.parts[-3:] == (".cache", "elan-ng", "peaks")


# --- performance -------------------------------------------------------------------------


def _write_long_stereo_noise(path: Path) -> None:
    """Write 2 h of 48 kHz stereo 16-bit low-level noise, in 10 s chunks."""
    rng = np.random.default_rng(0)
    total_frames = PERF_HOURS * 3600 * WAV_RATE
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(2)
        wav.setsampwidth(2)
        wav.setframerate(WAV_RATE)
        written = 0
        while written < total_frames:
            n = min(PERF_CHUNK_FRAMES, total_frames - written)
            chunk = rng.integers(-64, 65, size=(n, 2), dtype=np.int16)
            wav.writeframes(chunk.astype("<i2").tobytes())
            written += n


@pytest.mark.perf
def test_peaks_perf_two_hour_stereo_cold_and_warm(tmp_path: Path) -> None:
    long_wav = tmp_path / "long_stereo.wav"
    _write_long_stereo_noise(long_wav)
    root = tmp_path / "cache"

    start = time.perf_counter()
    cold = compute_peaks(long_wav, cache_root=root)
    cold_s = time.perf_counter() - start

    start = time.perf_counter()
    warm = compute_peaks(long_wav, cache_root=root)
    warm_s = time.perf_counter() - start

    print(
        f"\npeaks 2 h stereo ({cold.n_samples} samples): cold {cold_s:.2f} s "
        f"(target {PERF_COLD_TARGET_S} s, reported only), warm {warm_s:.3f} s "
        f"(hard limit {PERF_WARM_LIMIT_S} s)"
    )
    assert cold.n_samples == PERF_HOURS * 3600 * WAV_RATE
    assert cold.channels == 2
    _assert_same_pyramid(warm, cold)
    assert warm_s < PERF_WARM_LIMIT_S
