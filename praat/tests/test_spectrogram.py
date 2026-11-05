import math
from dataclasses import replace

import numpy as np
import pytest

from langtools_praat.analysis.contracts import (
    AnalysisRequest,
    ChannelPolicy,
    PitchSettings,
    SpectrogramSettings,
    TimeRange,
    accept,
)
from langtools_praat.analysis.spectrogram import DisplaySettings, display, to_spectrogram
from langtools_praat.errors import InvalidInput
from langtools_praat.model.sound import Sound
from langtools_praat.model.time import SampledAxis

FS = 22050
WINDOW = 0.005
# Praat manual: the Gaussian -3 dB bandwidth is 1.2982804 / window length.
THEORY_WIDTH_HZ = 1.2982804 / WINDOW
MIN_FREQUENCY_STEP = (math.sqrt(math.pi) / WINDOW) / 8.0
MIN_TIME_STEP = (WINDOW / math.sqrt(math.pi)) / 8.0


# ---------------------------------------------------------------------------
# Builders


def _sound(samples, name="x"):
    values = np.atleast_2d(np.asarray(samples, dtype=np.float64))
    return Sound(name, SampledAxis.recording(values.shape[1], FS), values)


def _sine(freq, amplitude=1.0, n=FS):
    t = (np.arange(n) + 0.5) / FS
    return amplitude * np.sin(2 * np.pi * freq * t)


def _request(sound, settings=None, time_range=None, channels=None):
    return AnalysisRequest(
        source_id=sound.id,
        revision=sound.revision,
        settings=SpectrogramSettings() if settings is None else settings,
        time_range=(
            TimeRange(sound.axis.xmin, sound.axis.xmax) if time_range is None else time_range
        ),
        channels=ChannelPolicy.single(0) if channels is None else channels,
    )


def _spectrogram(sound, **kwargs):
    return to_spectrogram(sound, _request(sound, **kwargs))


def _mid_frame(spectrogram):
    return spectrogram.power[spectrogram.time.nx // 2]


def _band_hz(freq_axis):
    return freq_axis.x1 + np.arange(freq_axis.nx) * freq_axis.dx


def _local_maxima(values):
    return [
        i
        for i in range(1, len(values) - 1)
        if values[i] > values[i - 1] and values[i] >= values[i + 1]
    ]


def _half_power_run(values, peak):
    """Contiguous bands around ``peak`` whose power is within 3 dB (at least half) of it."""
    level = values[peak] / 2.0
    lo = peak
    while lo > 0 and values[lo - 1] >= level:
        lo -= 1
    hi = peak
    while hi < len(values) - 1 and values[hi + 1] >= level:
        hi += 1
    return lo, hi


# ---------------------------------------------------------------------------
# Reference behaviour: a single 1000 Hz sine


def test_sine_peak_is_within_one_step_of_1000_hz():
    spec = _spectrogram(_sound(_sine(1000.0)))
    band = _mid_frame(spec)
    peak = int(np.argmax(band))
    peak_hz = spec.frequency.x1 + peak * spec.frequency.dx
    assert abs(peak_hz - 1000.0) <= spec.frequency.dx


def test_sine_3db_width_matches_manual_bandwidth():
    spec = _spectrogram(_sound(_sine(1000.0)))
    band = _mid_frame(spec)
    lo, hi = _half_power_run(band, int(np.argmax(band)))
    width = (hi - lo + 1) * spec.frequency.dx
    assert abs(width - THEORY_WIDTH_HZ) <= spec.frequency.dx


def test_sine_sidelobes_more_than_600_hz_away_are_60_db_down():
    spec = _spectrogram(_sound(_sine(1000.0)))
    band = _mid_frame(spec)
    peak_power = band.max()
    far = np.abs(_band_hz(spec.frequency) - 1000.0) > 600.0
    assert far.any()
    worst_db = 10.0 * math.log10(band[far].max() / peak_power)
    # Measured -67 dB (worst band about 612 Hz away); the Gaussian's own tail gives
    # about -64 dB at exactly 600 Hz, so the 60 dB requirement holds without a waiver.
    assert worst_db <= -60.0


# ---------------------------------------------------------------------------
# Resolution: two tones 200 Hz apart


def test_two_tones_are_resolved_with_long_window():
    sound = _sound(_sine(1000.0) + _sine(1200.0))
    spec = _spectrogram(sound, settings=SpectrogramSettings(window_length=0.03))
    band = _mid_frame(spec)
    hz = _band_hz(spec.frequency)
    maxima = [i for i in _local_maxima(band) if 900.0 <= hz[i] <= 1300.0]
    assert len(maxima) == 2
    low, high = sorted(hz[i] for i in maxima)
    assert abs(low - 1000.0) <= spec.frequency.dx
    assert abs(high - 1200.0) <= spec.frequency.dx


def test_two_tones_are_not_resolved_with_default_window():
    sound = _sound(_sine(1000.0) + _sine(1200.0))
    spec = _spectrogram(sound)
    band = _mid_frame(spec)
    hz = _band_hz(spec.frequency)
    maxima = [i for i in _local_maxima(band) if 900.0 <= hz[i] <= 1300.0]
    assert len(maxima) == 1


# ---------------------------------------------------------------------------
# Grid rules


def test_requested_time_step_is_clamped_up_to_oversampled_effective_length():
    spec = _spectrogram(_sound(_sine(1000.0)), settings=SpectrogramSettings(time_step=0.0001))
    assert spec.time.dx == pytest.approx(MIN_TIME_STEP, rel=1e-12)


def test_frequency_step_is_a_whole_number_of_fft_bins():
    spec = _spectrogram(_sound(_sine(1000.0)))
    step = spec.frequency.dx
    # The first band centre is 0.5 * (step - bin), so the bin width is recoverable.
    bin_hz = step - 2.0 * spec.frequency.x1
    ratio = step / bin_hz
    assert ratio == pytest.approx(round(ratio), abs=1e-9)
    fft_size = FS / bin_hz
    assert fft_size == pytest.approx(round(fft_size), abs=1e-9)
    size = round(fft_size)
    assert size > 0 and size & (size - 1) == 0


def test_frequency_step_snaps_down_to_whole_fft_bins():
    """The reference floors bins-per-band after the oversampling floor (spec §6).

    So the snapped step may fall just below (sqrt(pi)/L)/8: at L = 5 ms the FFT is
    512 points and one bin is 22050/512 = 43.07 Hz, not 44.31 Hz.
    """
    spec = _spectrogram(_sound(_sine(1000.0)))
    bin_hz = FS / 512
    assert spec.frequency.dx == pytest.approx(bin_hz)
    assert spec.frequency.dx > MIN_FREQUENCY_STEP - bin_hz


def test_frames_are_symmetric_within_one_sample_period():
    sound = _sound(_sine(1000.0))
    spec = _spectrogram(sound)
    t = spec.time
    last = t.x1 + (t.nx - 1) * t.dx
    left = t.x1 - t.xmin
    right = t.xmax - last
    assert abs(left - right) <= sound.axis.dx + 1e-12


def test_frame_count_follows_reference_formula():
    sound = _sound(_sine(1000.0))
    spec = _spectrogram(sound)
    duration = sound.axis.nx * sound.axis.dx
    expected = 1 + math.floor((duration - 2.0 * WINDOW) / spec.time.dx)
    assert spec.time.nx == expected


def test_maximum_frequency_above_nyquist_is_clipped():
    sound = _sound(_sine(1000.0))
    spec = _spectrogram(sound, settings=SpectrogramSettings(maximum_frequency=50000.0))
    assert spec.frequency.xmax == pytest.approx(FS / 2.0, rel=1e-12)


# ---------------------------------------------------------------------------
# Errors


def test_rejects_sound_shorter_than_two_window_lengths():
    sound = _sound(np.zeros(100))  # 4.5 ms, below the 10 ms physical window
    with pytest.raises(InvalidInput):
        _spectrogram(sound)


def test_rejects_request_with_mismatched_source_or_revision():
    sound = _sound(_sine(1000.0))
    request = _request(sound)
    with pytest.raises(InvalidInput):
        to_spectrogram(sound, replace(request, source_id="someone-else"))
    with pytest.raises(InvalidInput):
        to_spectrogram(sound, replace(request, revision=sound.revision + 1))


def test_rejects_non_spectrogram_settings():
    sound = _sound(_sine(1000.0))
    request = replace(_request(sound), settings=PitchSettings())
    with pytest.raises(InvalidInput):
        to_spectrogram(sound, request)


def test_rejects_channel_index_outside_recording():
    sound = _sound(_sine(1000.0))
    with pytest.raises(InvalidInput):
        _spectrogram(sound, channels=ChannelPolicy.single(1))


@pytest.mark.parametrize("start, end", [(2.0, 3.0), (-2.0, -1.0)])
def test_rejects_time_range_outside_sound(start, end):
    sound = _sound(_sine(1000.0))
    with pytest.raises(InvalidInput):
        _spectrogram(sound, time_range=TimeRange(start, end))


# ---------------------------------------------------------------------------
# Channels


def test_identical_stereo_channels_combined_match_mono():
    signal = _sine(1000.0) + 0.5 * _sine(3000.0)
    mono = _spectrogram(_sound(signal), channels=ChannelPolicy.single(0))
    stereo = _spectrogram(_sound(np.vstack([signal, signal])), channels=ChannelPolicy.combined())
    assert np.allclose(stereo.power, mono.power)


def test_silent_channel_selected_alone_gives_zero_power():
    stereo = _sound(np.vstack([_sine(1000.0), np.zeros(FS)]))
    silent = _spectrogram(stereo, channels=ChannelPolicy.single(1))
    loud = _spectrogram(stereo, channels=ChannelPolicy.single(0))
    assert np.all(silent.power == 0.0)
    assert loud.power.max() > 0.0


# ---------------------------------------------------------------------------
# Time range


def test_time_range_sets_axis_and_keeps_frames_inside():
    sound = _sound(_sine(1000.0))
    spec = _spectrogram(sound, time_range=TimeRange(0.25, 0.75))
    assert spec.time.xmin == 0.25
    assert spec.time.xmax == 0.75
    times = spec.time.x1 + np.arange(spec.time.nx) * spec.time.dx
    assert times.min() >= 0.25
    assert times.max() <= 0.75


# ---------------------------------------------------------------------------
# Result object, linearity


def test_result_is_immutable_and_carries_its_request():
    sound = _sound(_sine(1000.0))
    request = _request(sound)
    spec = to_spectrogram(sound, request)
    assert not spec.power.flags.writeable
    assert not spec.valid.flags.writeable
    assert np.all(spec.valid)
    assert spec.provenance.request is request
    assert accept(spec, sound.id, sound.revision, request.token)
    assert not accept(spec, sound.id, sound.revision + 1, request.token)


def test_doubling_amplitude_quadruples_power():
    signal = _sine(1000.0) + 0.3 * _sine(2500.0)
    base = _spectrogram(_sound(signal)).power
    doubled = _spectrogram(_sound(2.0 * signal)).power
    assert np.allclose(doubled, 4.0 * base, rtol=1e-12, atol=0.0)


# ---------------------------------------------------------------------------
# Display


def test_autoscaled_black_is_window_maximum_and_white_is_range_below():
    spec = _spectrogram(_sound(_sine(1000.0)))
    settings = DisplaySettings()
    img = display(spec, settings)
    assert img.black >= 0.0
    assert img.black == pytest.approx(max(float(img.db.max()), 0.0))
    assert img.white == pytest.approx(img.black - settings.dynamic_range)


def test_peak_band_is_black_without_preemphasis():
    spec = _spectrogram(_sound(_sine(1000.0)))
    img = display(spec, DisplaySettings(preemphasis=0.0))
    band = _mid_frame(spec)
    peak = int(np.argmax(band))
    assert abs(spec.frequency.x1 + peak * spec.frequency.dx - 1000.0) <= spec.frequency.dx
    mid_row = spec.time.nx // 2 - img.frames.start
    darkness = img.darkness()
    assert darkness[mid_row, peak - img.bands.start] == pytest.approx(1.0, abs=0.02)


def test_darkness_lies_in_unit_interval():
    spec = _spectrogram(_sound(_sine(1000.0)))
    dark = display(spec).darkness()
    assert dark.min() >= 0.0
    assert dark.max() <= 1.0


def test_fixed_maximum_sets_black_level():
    spec = _spectrogram(_sound(_sine(1000.0)))
    settings = DisplaySettings(autoscaling=False)
    img = display(spec, settings)
    assert img.black == settings.maximum
    assert img.white == pytest.approx(settings.maximum - settings.dynamic_range)


def test_time_range_limits_displayed_frames():
    spec = _spectrogram(_sound(_sine(1000.0)))
    img = display(spec, time_range=(0.0, 0.5))
    frames = spec.time.nx
    assert img.db.shape[0] < frames
    assert abs(img.db.shape[0] - frames / 2.0) <= 0.02 * frames


def test_display_does_not_modify_stored_power():
    spec = _spectrogram(_sound(_sine(1000.0)))
    before = spec.power.copy()
    display(spec)
    display(spec, DisplaySettings(autoscaling=False), time_range=(0.0, 0.5))
    assert np.array_equal(spec.power, before)


def test_silence_has_zero_power_and_finite_display():
    spec = _spectrogram(_sound(np.zeros(FS)))
    assert np.all(spec.power == 0.0)
    img = display(spec)
    assert np.isfinite(img.db).all()
    assert math.isfinite(img.black) and math.isfinite(img.white)
    raw = display(spec, DisplaySettings(preemphasis=0.0))
    assert np.allclose(raw.db, -3080.2, atol=0.5)
