"""Checks that the synthetic media files decode to the values they were built with."""

from __future__ import annotations

from pathlib import Path

import av
import numpy as np
from mediagen import (
    FPS,
    N_FRAMES,
    TONE_ONSETS_MS,
    WAV_DURATION_MS,
    WAV_RATE,
    read_counter,
)

ONSET_TOLERANCE_MS = 5.0
DURATION_TOLERANCE_MS = 1.0
FRAME_TIME_TOLERANCE_S = 0.001
ENVELOPE_THRESHOLD = 0.05  # 1 kHz tone at amplitude 0.5 has RMS of about 0.35


def _decode_audio(path: Path) -> tuple[np.ndarray, int]:
    """Return all decoded mono samples as floats in [-1, 1] and the sample rate."""
    chunks: list[np.ndarray] = []
    with av.open(str(path)) as container:
        stream = container.streams.audio[0]
        rate = stream.rate
        for frame in container.decode(stream):
            chunks.append(frame.to_ndarray().reshape(-1))
    raw = np.concatenate(chunks)
    # s16 decodes to int16; scale to [-1, 1] before any float maths
    samples = raw / 32768.0 if raw.dtype.kind == "i" else raw.astype(np.float64)
    assert np.abs(samples).max() <= 1.0
    return samples, rate


def test_tone_wav_onsets_and_format(tone_wav: Path) -> None:
    samples, rate = _decode_audio(tone_wav)
    assert rate == WAV_RATE

    duration_ms = len(samples) * 1000 / rate
    assert abs(duration_ms - WAV_DURATION_MS) <= DURATION_TOLERANCE_MS

    # 1 ms RMS envelope: one block per millisecond of audio.
    block = rate // 1000
    n_blocks = len(samples) // block
    blocks = samples[: n_blocks * block].reshape(n_blocks, block)
    envelope = np.sqrt((blocks**2).mean(axis=1))
    active = envelope > ENVELOPE_THRESHOLD
    rising = np.flatnonzero(active & ~np.concatenate(([False], active[:-1])))

    assert len(rising) == len(TONE_ONSETS_MS)
    for found_ms, expected_ms in zip(rising, TONE_ONSETS_MS, strict=True):
        assert abs(found_ms - expected_ms) <= ONSET_TOLERANCE_MS


def test_counter_mp4_frames_and_timestamps(counter_mp4: Path) -> None:
    with av.open(str(counter_mp4)) as container:
        frames = list(container.decode(video=0))

    assert len(frames) == N_FRAMES
    for k, frame in enumerate(frames):
        assert read_counter(frame.to_ndarray(format="rgb24")) == k
        assert abs(float(frame.time) - k / FPS) <= FRAME_TIME_TOLERANCE_S
