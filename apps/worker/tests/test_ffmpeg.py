import os

from agcs_worker import ffmpeg


def test_probe_duration(sample_video):
    ms = ffmpeg.probe_duration_ms(sample_video)
    assert ms is not None and ms > 15000


def test_probe_missing_returns_none():
    assert ffmpeg.probe_duration_ms("/no/such/file.mp4") is None


def test_cut_clip_vertical(sample_video, tmp_path):
    out = str(tmp_path / "clip.mp4")
    ffmpeg.cut_clip(sample_video, 1000, 5000, "9:16", out)
    assert os.path.exists(out) and os.path.getsize(out) > 0


def test_extract_frame(sample_video, tmp_path):
    out = str(tmp_path / "frame.jpg")
    ffmpeg.extract_frame(sample_video, 1000, out)
    assert os.path.exists(out) and os.path.getsize(out) > 0
