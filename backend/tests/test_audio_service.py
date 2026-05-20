import shutil

import pytest

from backend.app.services.audio_service import (
    AudioError,
    normalize_audio,
)

ffmpeg_missing = shutil.which("ffmpeg") is None


@pytest.mark.skipif(ffmpeg_missing, reason="ffmpeg not installed")
def test_normalize_audio_produces_mono_16k_wav(tmp_path):
    import subprocess

    # Generate a 1-second stereo 44.1k test tone to normalize.
    src = tmp_path / "tone.wav"
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi",
            "-i", "sine=frequency=440:duration=1:sample_rate=44100",
            "-ac", "2", str(src),
        ],
        capture_output=True, text=True, check=True,
    )

    out = tmp_path / "out.wav"
    meta = normalize_audio(src, out)

    assert out.exists() and out.stat().st_size > 0
    assert meta.sample_rate == 16000
    assert meta.channels == 1
    assert meta.duration_sec == pytest.approx(1.0, abs=0.2)


def test_normalize_audio_raises_on_bad_input(tmp_path):
    bad = tmp_path / "not_audio.wav"
    bad.write_text("this is not audio")
    out = tmp_path / "out.wav"
    with pytest.raises(AudioError):
        normalize_audio(bad, out)
