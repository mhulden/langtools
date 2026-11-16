"""Tests for MediaClock and MediaService against the simulated FakeBackend."""

from __future__ import annotations

import itertools

import pytest
from fakes import FakeBackend, FakeTime

from elan_ng.media.clock import MediaClock
from elan_ng.media.service import MediaService, Slave, SyncSettings


def make_clock(step_ms: float = 0.0) -> tuple[FakeTime, FakeBackend, MediaService, MediaClock]:
    time = FakeTime()
    master = FakeBackend(time, step_ms=step_ms)
    service = MediaService(master)
    clock = MediaClock(service, now=time.now)
    return time, master, service, clock


def test_play_advances_time_with_rate() -> None:
    time, master, _service, clock = make_clock()
    clock.play()
    time.advance(500)
    assert clock.tick() == pytest.approx(500)
    clock.set_rate(2.0)
    time.advance(500)
    assert clock.tick() == pytest.approx(1500)
    assert master.rates == [2.0]


def test_pause_freezes_time() -> None:
    time, _master, _service, clock = make_clock()
    clock.play()
    time.advance(300)
    clock.pause()
    frozen = clock.time_ms()
    time.advance(1000)
    assert frozen == pytest.approx(300)
    assert clock.time_ms() == frozen
    assert clock.tick() == frozen


def test_seek_while_paused_notifies_once_and_tick_is_silent() -> None:
    _time, master, _service, clock = make_clock()
    received: list[float] = []
    clock.add_tick_listener(received.append)
    clock.seek(4000)
    assert received == [4000]
    assert master.seeks == [4000]
    assert clock.tick() == 4000
    assert received == [4000]


def test_remove_tick_listener_stops_notifications() -> None:
    _time, _master, _service, clock = make_clock()
    received: list[float] = []
    clock.add_tick_listener(received.append)
    clock.remove_tick_listener(received.append)
    clock.seek(1000)
    assert received == []


def test_seek_clamps_to_zero_and_duration() -> None:
    _time, master, _service, clock = make_clock()
    clock.seek(-500)
    assert clock.time_ms() == 0.0
    assert master.seeks[-1] == 0.0
    clock.seek(50_000)
    assert clock.time_ms() == 10_000.0
    assert master.seeks[-1] == 10_000.0


def test_set_rate_rejects_non_positive() -> None:
    _time, _master, _service, clock = make_clock()
    with pytest.raises(ValueError):
        clock.set_rate(0)
    with pytest.raises(ValueError):
        clock.set_rate(-1.0)
    assert clock.rate == 1.0


def test_extrapolation_stays_within_frame_of_coarse_backend() -> None:
    time, master, _service, clock = make_clock(step_ms=50.0)
    clock.play()
    ticks: list[float] = []
    for _ in range(400):
        time.advance(16)
        t = clock.tick()
        ticks.append(t)
        assert abs(t - master.position_ms()) <= clock.frame_ms + 1e-9
    # Extrapolation fills the 50 ms gaps between backend reports.
    assert any(t % 50 != 0 for t in ticks)


def test_stalled_backend_is_capped_at_one_frame() -> None:
    time, master, _service, clock = make_clock()
    clock.play()
    master.pause()  # simulate a backend that stopped reporting progress
    time.advance(1000)
    assert clock.tick() == pytest.approx(40.0)


def test_play_selection_stops_exactly_at_end() -> None:
    time, master, service, clock = make_clock()
    clock.play_selection(1000, 2000)
    received: list[float] = []
    clock.add_tick_listener(received.append)
    for _ in range(1000):
        time.advance(16)
        clock.tick()
        if not clock.playing:
            break
    assert not clock.playing
    assert not service.playing
    assert received[-1] == 2000.0
    assert master.seeks[-1] == 2000.0
    assert clock.time_ms() == 2000.0
    assert clock.selection_end is None
    assert clock.loop_start is None


def test_play_selection_loop_jumps_back_to_begin() -> None:
    time, _master, _service, clock = make_clock()
    clock.play_selection(1000, 2000, loop=True)
    received: list[float] = []
    clock.add_tick_listener(received.append)
    for _ in range(400):
        time.advance(16)
        clock.tick()
    assert clock.playing
    assert 1000.0 in received
    assert all(t < 2000.0 for t in received)


def test_play_selection_rejects_empty_range() -> None:
    _time, _master, _service, clock = make_clock()
    with pytest.raises(ValueError):
        clock.play_selection(2000, 2000)


def test_stop_selection_clears_state_and_keeps_playing() -> None:
    time, _master, _service, clock = make_clock()
    clock.play_selection(1000, 2000, loop=True)
    clock.stop_selection()
    assert clock.selection_end is None
    assert clock.loop_start is None
    time.advance(2000)
    clock.tick()
    assert clock.playing
    assert clock.time_ms() > 2000


def test_master_offset_maps_document_time() -> None:
    time = FakeTime()
    master = FakeBackend(time, duration=10_000.0, start_ms=2000.0)
    service = MediaService(master, master_offset_ms=2000.0)
    clock = MediaClock(service, now=time.now)
    assert service.document_position_ms() == 0.0
    assert service.duration_ms() == 8000.0

    clock.seek(1000)
    assert master.seeks == [3000.0]
    assert clock.time_ms() == 1000.0

    clock.play()
    time.advance(500)
    assert clock.tick() == pytest.approx(1500)
    assert service.document_position_ms() == pytest.approx(master.position_ms() - 2000.0)


def test_master_offset_applies_to_seek_clamp() -> None:
    time = FakeTime()
    master = FakeBackend(time, duration=10_000.0)
    clock = MediaClock(MediaService(master, master_offset_ms=2000.0), now=time.now)
    clock.seek(9000)
    assert clock.time_ms() == 8000.0
    assert master.seeks[-1] == 10_000.0


def test_slave_seek_targets_include_offsets() -> None:
    time, master, service, clock = make_clock()
    slave = FakeBackend(time)
    service.add_slave(Slave(slave, offset_ms=500.0))
    clock.seek(1000)
    assert master.seeks == [1000.0]
    assert slave.seeks[-1] == 1500.0


def test_video_only_slave_is_muted() -> None:
    time, _master, service, _clock = make_clock()
    video = FakeBackend(time)
    audio = FakeBackend(time)
    service.add_slave(Slave(video, video_only=True))
    service.add_slave(Slave(audio))
    assert video.muted is True
    assert audio.muted is False


def _slave_setup(
    base_rate: float = 1.0,
) -> tuple[FakeTime, FakeBackend, MediaService, MediaClock]:
    time, _master, service, clock = make_clock()
    slave = FakeBackend(time)
    service.add_slave(Slave(slave))
    clock.set_rate(base_rate)
    clock.seek(1000)
    clock.play()
    return time, slave, service, clock


def test_sync_reseeks_slave_drifted_over_40ms_and_restores_base_rate() -> None:
    _time, slave, service, _clock = _slave_setup(base_rate=2.0)
    slave.seek(1050.0)  # 50 ms ahead of the target 1000
    service.sync_slaves()
    assert slave.seeks[-1] == pytest.approx(1000.0)
    assert slave.rate == pytest.approx(2.0)


def test_sync_nudges_ahead_slave_slower() -> None:
    _time, slave, service, _clock = _slave_setup(base_rate=2.0)
    slave.seek(1025.0)  # 25 ms ahead: nudge, no re-seek
    seeks_before = len(slave.seeks)
    service.sync_slaves()
    assert len(slave.seeks) == seeks_before
    assert slave.rate == pytest.approx(2.0 * 0.98)


def test_sync_nudges_behind_slave_faster() -> None:
    _time, slave, service, _clock = _slave_setup(base_rate=2.0)
    slave.seek(975.0)  # 25 ms behind
    service.sync_slaves()
    assert slave.rate == pytest.approx(2.0 * 1.02)


def test_sync_restores_base_rate_within_10ms() -> None:
    _time, slave, service, _clock = _slave_setup(base_rate=2.0)
    slave.seek(1025.0)
    service.sync_slaves()
    slave.seek(1005.0)  # 5 ms ahead
    service.sync_slaves()
    assert slave.rate == pytest.approx(2.0)


def test_sync_does_not_nudge_while_paused() -> None:
    _time, slave, service, clock = _slave_setup()
    clock.pause()
    slave.seek(1025.0)
    service.sync_slaves()
    assert slave.rate == pytest.approx(1.0)


def test_sync_settings_are_used() -> None:
    time = FakeTime()
    master = FakeBackend(time)
    service = MediaService(master, settings=SyncSettings(reseek_drift_ms=100.0))
    slave = FakeBackend(time)
    service.add_slave(Slave(slave))
    service.seek(1000.0)
    service.play()
    slave.seek(1050.0)  # below the custom 100 ms threshold: nudged, not re-seeked
    service.sync_slaves()
    assert slave.seeks[-1] == 1050.0
    assert slave.rate == pytest.approx(0.98)


def test_drifting_slave_is_nudged_then_reseeked() -> None:
    time = FakeTime()
    master = FakeBackend(time)
    service = MediaService(master)
    slave = FakeBackend(time, drift_per_s_ms=100.0)  # runs 10% fast
    service.add_slave(Slave(slave))
    service.seek(0.0)
    service.play()
    time.advance(300)
    service.sync_slaves()  # slave at 330, target 300: nudged slower
    assert slave.rate == pytest.approx(0.98)
    time.advance(700)
    service.sync_slaves()  # drift grew past 40 ms: re-seek to the target
    assert slave.seeks[-1] == pytest.approx(1000.0)
    assert slave.rate == pytest.approx(1.0)


def test_coarse_backend_time_is_monotonic_and_within_frame() -> None:
    time, master, _service, clock = make_clock(step_ms=50.0)
    clock.play()
    ticks: list[float] = []
    for _ in range(500):  # about 8 s at 60 Hz, before the 10 s media ends
        time.advance(1000.0 / 60.0)
        t = clock.tick()
        ticks.append(t)
        assert abs(t - master.position_ms()) <= clock.frame_ms + 1e-9
    assert all(later >= earlier for earlier, later in itertools.pairwise(ticks))
    assert ticks[-1] > ticks[0]


def test_seek_backwards_while_playing_moves_time_back() -> None:
    time, _master, _service, clock = make_clock()
    clock.play()
    time.advance(1000)
    assert clock.tick() == pytest.approx(1000)
    clock.seek(200)
    time.advance(16)
    t = clock.tick()
    assert t == pytest.approx(216)
    assert t < 1000


def test_added_slave_is_seeked_to_document_position_plus_offset() -> None:
    time, _master, service, clock = make_clock()
    clock.seek(1000)
    slave = FakeBackend(time)
    service.add_slave(Slave(slave, offset_ms=300.0))
    assert slave.seeks == [1300.0]


def test_added_slave_gets_base_rate() -> None:
    time, _master, service, _clock = make_clock()
    service.set_rate(2.0)
    slave = FakeBackend(time)
    service.add_slave(Slave(slave))
    assert slave.rate == 2.0
    assert slave.rates == [2.0]


def test_added_slave_plays_only_when_service_is_playing() -> None:
    time, _master, service, clock = make_clock()
    idle = FakeBackend(time)
    service.add_slave(Slave(idle))
    assert idle.playing is False

    clock.play()
    time.advance(500)
    late = FakeBackend(time)
    service.add_slave(Slave(late))
    assert late.playing is True
    assert late.seeks == [500.0]


def test_sync_skips_set_rate_when_rate_is_unchanged() -> None:
    _time, slave, service, _clock = _slave_setup()
    slave.seek(1025.0)
    service.sync_slaves()
    calls = len(slave.rates)
    service.sync_slaves()
    assert len(slave.rates) == calls


def test_negative_start_loop_never_seeks_below_zero() -> None:
    time, master, _service, clock = make_clock()
    clock.play_selection(-500, 500, loop=True)
    assert clock.selection_end == 500.0
    assert clock.loop_start == 0.0
    for _ in range(40):  # 640 ms: passes the selection end and loops
        time.advance(16)
        clock.tick()
    assert clock.playing
    assert 0.0 in master.seeks
    assert min(master.seeks) >= 0.0


def test_selection_beyond_media_end_is_clamped_and_stops_at_end() -> None:
    time, master, service, clock = make_clock()
    clock.play_selection(9000, 11000)
    assert clock.selection_end == 10_000.0
    received: list[float] = []
    clock.add_tick_listener(received.append)
    for _ in range(400):
        time.advance(16)
        clock.tick()
        if not clock.playing:
            break
    assert not clock.playing
    assert not service.playing
    assert received.count(10_000.0) == 1
    assert received[-1] == 10_000.0
    assert clock.selection_end is None
    assert max(master.seeks) <= 10_000.0


def test_selection_fully_outside_media_raises_and_changes_nothing() -> None:
    _time, master, _service, clock = make_clock()
    with pytest.raises(ValueError):
        clock.play_selection(12_000, 13_000)
    assert not clock.playing
    assert clock.selection_end is None
    assert clock.loop_start is None
    assert master.seeks == []
    assert master.playing is False


def test_selection_ending_before_media_start_raises() -> None:
    _time, _master, _service, clock = make_clock()
    with pytest.raises(ValueError):
        clock.play_selection(-500, -100)
    assert clock.selection_end is None


def test_eof_clamped_backend_stops_playback_at_media_end() -> None:
    time, master, service, clock = make_clock()
    clock.seek(9000)
    clock.play()
    for _ in range(400):
        time.advance(16)
        clock.tick()
        if not clock.playing:
            break
    assert not clock.playing
    assert not service.playing
    assert clock.time_ms() == 10_000.0
    assert master.position_ms() == 10_000.0
    assert master.seeks[-1] == 10_000.0


def test_fake_backend_clamps_position_to_duration() -> None:
    time = FakeTime()
    backend = FakeBackend(time, duration=1000.0)
    backend.seek(900.0)
    backend.play()
    time.advance(500)
    assert backend.position_ms() == 1000.0
    backend.seek(5000.0)
    assert backend.seeks[-1] == 5000.0
    assert backend.position_ms() == 1000.0


def test_document_length_is_longest_media() -> None:
    time = FakeTime()
    master = FakeBackend(time, duration=10_000.0)
    slave = FakeBackend(time, duration=15_000.0)
    service = MediaService(master)
    service.add_slave(Slave(slave))
    clock = MediaClock(service, now=time.now)
    assert service.master_end_ms() == 10_000.0
    assert service.duration_ms() == 15_000.0
    clock.seek(12_000)
    assert clock.time_ms() == 12_000.0
    assert master.seeks[-1] == 10_000.0
    assert slave.seeks[-1] == 12_000.0


def test_slave_offset_extends_document_length() -> None:
    time = FakeTime()
    master = FakeBackend(time, duration=10_000.0)
    slave = FakeBackend(time, duration=15_000.0)
    service = MediaService(master)
    service.add_slave(Slave(slave, offset_ms=2000.0))
    clock = MediaClock(service, now=time.now)
    assert service.duration_ms() == 13_000.0
    clock.seek(20_000)
    assert clock.time_ms() == 13_000.0
    assert master.seeks[-1] == 10_000.0
    assert slave.seeks[-1] == 15_000.0


def test_playing_past_master_end_runs_to_document_end() -> None:
    time = FakeTime()
    master = FakeBackend(time, duration=10_000.0)
    slave = FakeBackend(time, duration=15_000.0)
    service = MediaService(master)
    service.add_slave(Slave(slave, offset_ms=2000.0))
    clock = MediaClock(service, now=time.now)
    clock.seek(9000)
    clock.play()
    ticks: list[float] = []
    clock.add_tick_listener(ticks.append)
    for _ in range(125):  # 2 s of wall time: the master ends at 10 s, playback continues
        time.advance(16)
        clock.tick()
    assert clock.playing
    assert clock.time_ms() == pytest.approx(11_000.0)
    assert master.position_ms() == 10_000.0
    for _ in range(400):
        time.advance(16)
        clock.tick()
        if not clock.playing:
            break
    assert not clock.playing
    assert ticks[-1] == 13_000.0
    assert ticks.count(13_000.0) == 1
    assert master.seeks[-1] == 10_000.0
    assert all(later >= earlier for earlier, later in itertools.pairwise(ticks))


def test_duration_ignores_unknown_slave_duration() -> None:
    time = FakeTime()
    master = FakeBackend(time, duration=10_000.0)
    service = MediaService(master)
    service.add_slave(Slave(FakeBackend(time, duration=None)))
    assert service.duration_ms() == 10_000.0
    assert MediaService(FakeBackend(time, duration=None)).duration_ms() is None


def test_sync_does_not_pull_a_longer_slave_back_after_master_end() -> None:
    time = FakeTime()
    master = FakeBackend(time, duration=10_000.0)
    slave = FakeBackend(time, duration=15_000.0)
    service = MediaService(master)
    service.add_slave(Slave(slave))
    clock = MediaClock(service, now=time.now)
    clock.seek(9_000)
    clock.play()
    for _ in range(3):  # 3 s: the master stops at 10 s, the slave keeps playing to 12 s
        time.advance(1_000)
        clock.tick()
        service.sync_slaves()
    assert master.position_ms() == 10_000.0
    assert slave.position_ms() == pytest.approx(12_000.0)
    assert clock.time_ms() == pytest.approx(12_000.0)


def test_nudged_slave_returns_to_base_rate_after_master_end() -> None:
    time = FakeTime()
    master = FakeBackend(time, duration=10_000.0)
    slave = FakeBackend(time, duration=15_000.0)
    service = MediaService(master)
    service.add_slave(Slave(slave))
    clock = MediaClock(service, now=time.now)
    clock.seek(9_000)
    clock.play()
    slave.seek(9_025)  # 25 ms ahead: sync nudges it to 0.98
    service.sync_slaves()
    assert slave.rate == pytest.approx(0.98)
    time.advance(1_500)  # master reaches its end at 10 s
    clock.tick()
    seeks_before = len(slave.seeks)
    service.sync_slaves()
    assert slave.rate == 1.0
    assert len(slave.seeks) == seeks_before  # no re-seek toward the ended master
