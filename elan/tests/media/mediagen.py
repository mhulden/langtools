"""Synthetic media generators for the UI and media tests (REIMPLEMENTATION.md §6.4).

Two files are generated, both without the FFmpeg CLI:

* ``tones.wav``: 3 s mono 48 kHz 16-bit PCM, silence with 200 ms 1 kHz tones at known onsets.
* ``counter.mp4``: 50 frames at 25 fps where frame ``k`` shows ``k`` as a binary code of
  squares (the bundled FFmpeg has no freetype, so text cannot be burned in).

Run ``uv run python tests/media/mediagen.py OUTDIR`` to write both files into OUTDIR.
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


def write_tone_wav(path: Path) -> None:
    """Write the 3 s mono 48 kHz test WAV with tones at ``TONE_ONSETS_MS``."""
    n_samples = WAV_RATE * WAV_DURATION_MS // 1000
    signal = np.zeros(n_samples, dtype=np.float64)
    n_tone = WAV_RATE * TONE_MS // 1000
    t = np.arange(n_tone) / WAV_RATE
    tone = TONE_AMPLITUDE * np.sin(2 * np.pi * TONE_HZ * t)
    for onset_ms in TONE_ONSETS_MS:
        start = WAV_RATE * onset_ms // 1000
        signal[start : start + n_tone] = tone
    pcm = np.round(signal * 32767).astype("<i2")
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(WAV_RATE)
        wav.writeframes(pcm.tobytes())


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
    """Write ``tones.wav`` and ``counter.mp4`` into the directory given as the argument."""
    if len(argv) != 2:
        print("usage: mediagen.py OUTDIR", file=sys.stderr)
        return 2
    outdir = Path(argv[1])
    outdir.mkdir(parents=True, exist_ok=True)
    write_tone_wav(outdir / "tones.wav")
    write_counter_mp4(outdir / "counter.mp4")
    print(f"wrote {outdir / 'tones.wav'} and {outdir / 'counter.mp4'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
