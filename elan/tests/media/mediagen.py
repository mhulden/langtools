"""Synthetic media generators for the UI and media tests (REIMPLEMENTATION.md §6.4).

Four files are generated, all without the FFmpeg CLI:

* ``tones.wav``: 3 s mono 48 kHz 16-bit PCM, silence with 200 ms 1 kHz tones at known onsets.
* ``tones_stereo.wav``: the same in stereo; the right channel carries the same tones at
  ``TONE_AMPLITUDE_RIGHT`` (a quarter of the left amplitude).
* ``tones.m4a``: the mono tones encoded with FFmpeg's built-in AAC encoder into an MP4
  container (lossy, so only approximate values and timings can be checked).
* ``counter.mp4``: 50 frames at 25 fps where frame ``k`` shows ``k`` as a binary code of
  squares (the bundled FFmpeg has no freetype, so text cannot be burned in).

Run ``uv run python tests/media/mediagen.py OUTDIR`` to write all four files into OUTDIR.
"""

from __future__ import annotations

import sys
import wave
from fractions import Fraction
from pathlib import Path

import av
import numpy as np

# WAV
WAV_RATE = 48_000
WAV_DURATION_MS = 3_000
TONE_MS = 200
TONE_HZ = 1_000
TONE_ONSETS_MS = (500, 1500, 2500)
TONE_AMPLITUDE = 0.5
TONE_AMPLITUDE_RIGHT = 0.25  # right channel of the stereo file

# M4A
AUDIO_CODEC_AAC = "aac"  # FFmpeg's built-in encoder
AAC_FRAME_SIZE = 1024  # samples per AAC frame
AAC_BIT_RATE = 128_000

# MP4
VIDEO_CODEC = "mpeg4"  # built into FFmpeg (LGPL); libx264 is deliberately not used
FPS = 25
N_FRAMES = 50
WIDTH, HEIGHT = 320, 240
VIDEO_BIT_RATE = 4_000_000
COUNTER_BITS = 8
SQUARE_PX = 32
BIT_STRIDE_PX = 40  # bit i is drawn at x = i * BIT_STRIDE_PX
BIT_Y = 100
BACKGROUND = 128
WHITE = 255
BLACK = 0
THRESHOLD = 128

MEDIA_FILES = ("tones.wav", "tones_stereo.wav", "tones.m4a", "counter.mp4")


def _tone_signal(amplitude: float) -> np.ndarray:
    """Return the mono float signal: tones at ``TONE_ONSETS_MS`` with the given amplitude."""
    n_samples = WAV_RATE * WAV_DURATION_MS // 1000
    signal = np.zeros(n_samples, dtype=np.float64)
    n_tone = WAV_RATE * TONE_MS // 1000
    t = np.arange(n_tone) / WAV_RATE
    tone = amplitude * np.sin(2 * np.pi * TONE_HZ * t)
    for onset_ms in TONE_ONSETS_MS:
        start = WAV_RATE * onset_ms // 1000
        signal[start : start + n_tone] = tone
    return signal


def write_tone_wav(path: Path, channels: int = 1) -> None:
    """Write the 3 s 48 kHz test WAV with tones at ``TONE_ONSETS_MS``.

    With ``channels=1`` the file is mono. With ``channels=2`` the left channel is the mono
    signal and the right channel has the same tones at ``TONE_AMPLITUDE_RIGHT``.
    """
    if channels not in (1, 2):
        raise ValueError(f"channels must be 1 or 2, not {channels}")
    left = _tone_signal(TONE_AMPLITUDE)
    if channels == 1:
        samples = left
    else:
        right = _tone_signal(TONE_AMPLITUDE_RIGHT)
        samples = np.stack((left, right), axis=1)
    pcm = np.round(samples * 32767).astype("<i2")
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(2)
        wav.setframerate(WAV_RATE)
        wav.writeframes(pcm.tobytes())


def write_tone_m4a(path: Path) -> None:
    """Write the mono tone signal as AAC in an MP4 container (48 kHz mono).

    The signal is zero-padded to a whole number of AAC frames, so the decoded length is a few
    thousand samples longer than the WAV, plus the encoder's priming delay.
    """
    n_samples = WAV_RATE * WAV_DURATION_MS // 1000
    n_frames = -(-n_samples // AAC_FRAME_SIZE)
    padded = np.zeros(n_frames * AAC_FRAME_SIZE, dtype=np.float32)
    padded[:n_samples] = _tone_signal(TONE_AMPLITUDE)
    container = av.open(str(path), mode="w", format="mp4")
    try:
        stream = container.add_stream(AUDIO_CODEC_AAC, rate=WAV_RATE, layout="mono")
        stream.bit_rate = AAC_BIT_RATE
        for i in range(n_frames):
            chunk = padded[i * AAC_FRAME_SIZE : (i + 1) * AAC_FRAME_SIZE].reshape(1, -1)
            frame = av.AudioFrame.from_ndarray(chunk, format="fltp", layout="mono")
            frame.sample_rate = WAV_RATE
            frame.time_base = Fraction(1, WAV_RATE)
            frame.pts = i * AAC_FRAME_SIZE
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)
    finally:
        container.close()


def counter_frame(k: int) -> np.ndarray:
    """Return frame ``k`` as an RGB array with ``k`` burned in as a binary square code."""
    frame = np.full((HEIGHT, WIDTH, 3), BACKGROUND, dtype=np.uint8)
    for i in range(COUNTER_BITS):
        value = WHITE if (k >> i) & 1 else BLACK
        x0 = i * BIT_STRIDE_PX
        frame[BIT_Y : BIT_Y + SQUARE_PX, x0 : x0 + SQUARE_PX] = value
    return frame


def read_counter(rgb: np.ndarray) -> int:
    """Read the frame number written by ``counter_frame`` from an RGB array."""
    value = 0
    half = SQUARE_PX // 4  # sample an 8x8 patch at the square centre
    cy = BIT_Y + SQUARE_PX // 2
    for i in range(COUNTER_BITS):
        cx = i * BIT_STRIDE_PX + SQUARE_PX // 2
        patch = rgb[cy - half : cy + half, cx - half : cx + half]
        if patch.mean() >= THRESHOLD:
            value |= 1 << i
    return value


def write_counter_mp4(path: Path) -> None:
    """Write the 50-frame counter video at 25 fps (frame k has pts k / FPS seconds)."""
    container = av.open(str(path), mode="w")
    try:
        stream = container.add_stream(VIDEO_CODEC, rate=FPS)
        stream.width = WIDTH
        stream.height = HEIGHT
        stream.pix_fmt = "yuv420p"
        stream.bit_rate = VIDEO_BIT_RATE
        stream.codec_context.time_base = Fraction(1, FPS)
        for k in range(N_FRAMES):
            frame = av.VideoFrame.from_ndarray(counter_frame(k), format="rgb24")
            frame = frame.reformat(format="yuv420p")
            frame.pts = k
            frame.time_base = Fraction(1, FPS)
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)
    finally:
        container.close()


def main(argv: list[str]) -> int:
    """Write the files listed in ``MEDIA_FILES`` into the directory given as the argument."""
    if len(argv) != 2:
        print("usage: mediagen.py OUTDIR", file=sys.stderr)
        return 2
    outdir = Path(argv[1])
    outdir.mkdir(parents=True, exist_ok=True)
    write_tone_wav(outdir / "tones.wav")
    write_tone_wav(outdir / "tones_stereo.wav", channels=2)
    write_tone_m4a(outdir / "tones.m4a")
    write_counter_mp4(outdir / "counter.mp4")
    print(f"wrote {', '.join(MEDIA_FILES)} into {outdir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
