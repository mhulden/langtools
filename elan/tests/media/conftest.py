"""Session-scoped synthetic media fixtures (REIMPLEMENTATION.md §6.4)."""

from __future__ import annotations

from pathlib import Path

import pytest
from mediagen import write_counter_mp4, write_tone_wav


@pytest.fixture(scope="session")
def tone_wav(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("media") / "tones.wav"
    write_tone_wav(path)
    return path


@pytest.fixture(scope="session")
def counter_mp4(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("media") / "counter.mp4"
    write_counter_mp4(path)
    return path
