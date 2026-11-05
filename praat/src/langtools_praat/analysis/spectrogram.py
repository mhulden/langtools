"""Gaussian short-time Fourier spectrogram (spec §6) and its display transform.

``to_spectrogram`` follows the reference's documented grid rules:

- Physical window = 2 x effective length (Gaussian). Time step and frequency step
  are floored at 8x oversampling of the effective widths L/sqrt(pi) and
  sqrt(pi)/L.
- Frame count ``1 + floor((N dx - physical) / step)``, frames centred in the
  sound. FFT length is the smallest power of two that holds the window and
  ``2 * bins * nyquist / fmax`` points. The frequency step is snapped to a whole
  number of FFT bins.
- Power per band = summed |FFT|^2 over its bins / (sum w^2 * bins per band).

``display`` is the separate, pure paint transform: dB re 4e-10, pre-emphasis,
autoscaling, dynamic compression, and the grey endpoints. Stored power is never
modified, so GUI and CLI read identical numbers.

Normalisation note (discrepancy candidate): the reference divides the unscaled FFT
power by ``sum w^2`` and the *number of bins* per band, not by a bandwidth in Hz.
White noise of variance 1 Pa^2 therefore gives values near 1, not 2*dx. The
manual still calls the values Pa^2/Hz, and the dB transform (re 4e-10) assumes
those values. We reproduce the reference's numbers, not the textbook PSD.

Numerical parity with the reference is unverified until oracle capture.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from ..errors import InvalidInput
from ..model.sound import Sound
from ..model.time import SampledAxis
from .contracts import (
    Algorithm,
    AnalysisKind,
    AnalysisRequest,
    ChannelMode,
    Provenance,
    Spectrogram,
    SpectrogramSettings,
)

ALGORITHM = Algorithm("spectrogram.gaussian-stft", "1")
OVERSAMPLING = 8.0
REFERENCE_PSD = 4.0e-10
TINY = 1e-308
_FRAMES_PER_BLOCK = 256


def gaussian_window(samples: int, physical_samples: float) -> NDArray[np.float64]:
    """Edge-subtracted Gaussian, exp(-48 p^2), p in about [-0.5, 0.5] (spec §6)."""
    i = np.arange(1, samples + 1, dtype=np.float64)
    phase = (i - 0.5 * (samples + 1)) / physical_samples
    edge = math.exp(-12.0)
    return (np.exp(-48.0 * phase * phase) - edge) / (1.0 - edge)


def _part(sound: Sound, start: float, end: float) -> tuple[SampledAxis, NDArray[np.float64]]:
    """Samples whose centres lie in [start, end), keeping source times."""
    axis = sound.axis
    xmin, xmax = max(start, axis.xmin), min(end, axis.xmax)
    if xmin >= xmax:
        raise InvalidInput("The analysis range lies outside the sound.")
    if xmin == axis.xmin and xmax == axis.xmax:
        return axis, sound.samples
    first, last = axis.frame_range(xmin, xmax)
    if first == last:
        raise InvalidInput("The analysis range contains no samples.")
    part = SampledAxis(xmin, xmax, last - first, axis.dx, axis.x1 + first * axis.dx)
    return part, sound.samples[:, first:last]


def to_spectrogram(sound: Sound, request: AnalysisRequest) -> Spectrogram:
    """Compute a Spectrogram for ``request`` over ``sound``.

    Channel rule for ``ChannelPolicy.combined()``: the mean of the per-channel power
    spectra, so identical stereo channels give the mono result.
    """
    settings = request.settings
    if request.kind is not AnalysisKind.SPECTROGRAM or not isinstance(
        settings, SpectrogramSettings
    ):
        raise InvalidInput("This request is not a spectrogram request.")
    if request.source_id != sound.id or request.revision != sound.revision:
        raise InvalidInput("The request does not describe this sound revision.")
    request.channels.check(sound.channels)
    axis, samples = _part(sound, request.time_range.start, request.time_range.end)
    if request.channels.mode is ChannelMode.SINGLE:
        samples = samples[request.channels.channel : request.channels.channel + 1]

    dx = axis.dx
    nyquist = 0.5 / dx
    effective = settings.window_length
    physical = 2.0 * effective
    effective_time = effective / math.sqrt(math.pi)
    time_step = max(settings.time_step, effective_time / OVERSAMPLING)
    freq_step = max(settings.frequency_step, (1.0 / effective_time) / OVERSAMPLING)
    duration = dx * axis.nx

    half_window = math.floor(physical / dx) // 2 - 1
    window_samples = 2 * half_window
    if window_samples < 1:
        raise InvalidInput("The analysis window is too short: less than two samples.")
    if physical > duration:
        raise InvalidInput("The sound is too short: it must be at least two window lengths.")
    frames = 1 + math.floor((duration - physical) / time_step)
    t1 = axis.x1 + 0.5 * ((axis.nx - 1) * dx - (frames - 1) * time_step)

    fmax = settings.maximum_frequency
    if fmax <= 0.0 or fmax > nyquist:
        fmax = nyquist
    if math.floor(fmax / freq_step) < 1:
        raise InvalidInput("No frequency bins: raise the maximum frequency or window length.")
    fft_size = 1
    while fft_size < window_samples or fft_size < 2 * math.floor(fmax / freq_step) * (
        nyquist / fmax
    ):
        fft_size *= 2
    bins_per_band = max(1, math.floor(freq_step * dx * fft_size))
    bin_hz = 1.0 / (dx * fft_size)
    freq_step = bins_per_band * bin_hz
    bands = math.floor(fmax / freq_step)
    if bands < 1:
        raise InvalidInput("No frequency bins: raise the maximum frequency or window length.")

    time_axis = SampledAxis(axis.xmin, axis.xmax, frames, time_step, t1)
    freq_axis = SampledAxis(0.0, fmax, bands, freq_step, 0.5 * (freq_step - bin_hz))

    window = gaussian_window(window_samples, physical / dx)
    scale = 1.0 / float(np.sum(window * window)) / bins_per_band

    # Zero-based start of each frame's window: low sample index minus half the window.
    centres = t1 + np.arange(frames) * time_step
    low = np.floor((centres - axis.x1) / dx).astype(np.int64)  # zero-based low index
    starts = low + 1 - half_window
    if starts[0] < 0 or starts[-1] + window_samples > axis.nx:
        raise InvalidInput("Analysis frames do not fit inside the sound.")

    power = np.empty((frames, bands), dtype=np.float64)
    offsets = np.arange(window_samples)
    used = bands * bins_per_band
    for begin in range(0, frames, _FRAMES_PER_BLOCK):
        stop = min(frames, begin + _FRAMES_PER_BLOCK)
        index = starts[begin:stop, None] + offsets[None, :]
        total = np.zeros((stop - begin, fft_size // 2 + 1))
        for channel in samples:
            spectrum = np.fft.rfft(channel[index] * window, n=fft_size, axis=1)
            total += spectrum.real**2 + spectrum.imag**2
        total /= samples.shape[0]
        banded = total[:, :used].reshape(stop - begin, bands, bins_per_band).sum(axis=2)
        power[begin:stop] = banded * scale

    provenance = Provenance(request, ALGORITHM)
    return Spectrogram(provenance, time_axis, freq_axis, power, np.ones_like(power, dtype=bool))


# ---------------------------------------------------------------------------
# Display (``Spectrogram: Paint...`` / editor drawing), pure and non-mutating


@dataclass(frozen=True)
class DisplaySettings:
    """Candidate defaults: editor values; ``Paint...`` uses 50 dB range (spec §6, D04)."""

    maximum: float = 100.0
    autoscaling: bool = True
    dynamic_range: float = 70.0
    preemphasis: float = 6.0
    dynamic_compression: float = 0.0


@dataclass(frozen=True, eq=False)
class SpectrogramImage:
    """dB values (frames, bins) for the window, with the grey endpoints.

    ``white`` = maximum - dynamic range, ``black`` = maximum; linear in between.
    """

    frames: slice
    bands: slice
    db: NDArray[np.float64]
    white: float
    black: float

    def darkness(self) -> NDArray[np.float64]:
        """0 = white, 1 = black, clipped; the grey mapping of the reference."""
        span = self.black - self.white
        if span <= 0:
            span = 1.0
        return np.clip((self.db - self.white) / span, 0.0, 1.0)


def _window_indices(axis: SampledAxis, low: float, high: float) -> slice:
    """Samples whose centres lie within [low - 0.49999 dx, high + 0.49999 dx]."""
    first = math.ceil((low - 0.49999 * axis.dx - axis.x1) / axis.dx)
    last = math.floor((high + 0.49999 * axis.dx - axis.x1) / axis.dx)
    return slice(max(0, first), min(axis.nx, last + 1))


def display(
    spectrogram: Spectrogram,
    settings: DisplaySettings | None = None,
    *,
    time_range: tuple[float, float] | None = None,
    frequency_range: tuple[float, float] | None = None,
) -> SpectrogramImage:
    """Paint transform over the visible window; autoscaling uses only that window."""
    settings = settings or DisplaySettings()
    t = spectrogram.time
    f = spectrogram.frequency
    tmin, tmax = time_range if time_range else (t.xmin, t.xmax)
    fmin, fmax = frequency_range if frequency_range else (f.xmin, f.xmax)
    frames = _window_indices(t, tmin, tmax)
    bands = _window_indices(f, fmin, fmax)
    part = spectrogram.power[frames, bands]
    if part.size == 0:
        return SpectrogramImage(frames, bands, np.empty((0, 0)), 0.0, 0.0)
    centres = f.x1 + np.arange(bands.start, bands.stop) * f.dx
    preemphasis = (settings.preemphasis / math.log(2)) * np.log(
        np.maximum(centres, 0.0) / 1000.0 + TINY
    )
    db = (10.0 / math.log(10)) * np.log(part / REFERENCE_PSD + TINY) + preemphasis[None, :]
    local = np.maximum(db.max(axis=1), 0.0)  # the reference's per-frame maximum starts at 0
    maximum = float(local.max()) if settings.autoscaling else settings.maximum
    if settings.autoscaling:
        maximum = max(maximum, 0.0)
    db = db + (settings.dynamic_compression * (maximum - local))[:, None]
    return SpectrogramImage(frames, bands, db, maximum - settings.dynamic_range, maximum)
