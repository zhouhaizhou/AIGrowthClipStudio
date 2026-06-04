import math
import struct
import wave

from agcs_worker import signals


def _write_wav(path, sr=16000, dur=6.0, loud_lo=2.0, loud_hi=3.0):
    frames = []
    for i in range(int(sr * dur)):
        t = i / sr
        amp = 30000 if loud_lo < t < loud_hi else 2000
        frames.append(int(amp * math.sin(2 * math.pi * 440 * t)))
    with wave.open(path, "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(b"".join(struct.pack("<h", f) for f in frames))


def test_audio_energy_profile_locates_loud_section(tmp_path):
    p = str(tmp_path / "e.wav")
    _write_wav(p)
    prof = signals.audio_energy_profile(p, window_ms=500)
    assert len(prof) >= 10
    peak = prof.index(max(prof))
    assert peak in (4, 5)


def test_audio_energy_profile_missing_file_returns_empty():
    assert signals.audio_energy_profile("/no/such.wav") == []


def test_parse_scene_times():
    stderr = "frame:1 ... pts_time:1.234 ...\nframe:2 ... pts_time:5.5 ..."
    assert signals._parse_scene_times(stderr) == [1.234, 5.5]


def test_candidate_windows_locates_energy_peak():
    energy = [2000, 2000, 2000, 2000, 21000, 21000, 2000, 2000, 2000, 2000, 2000, 2000]
    cands = signals.candidate_windows(6000, energy, [], window_ms=500, clip_ms=2000, top_k=3)
    assert cands
    top = cands[0]
    assert top["start_ms"] <= 3000 and top["end_ms"] >= 2000
    assert "audio" in top["sources"]


def test_candidate_windows_scene_only():
    cands = signals.candidate_windows(10000, [], [1.0, 1.2, 5.0],
                                      window_ms=500, scene_weight=1.0, clip_ms=2000, top_k=3)
    assert cands
    top = cands[0]
    assert top["start_ms"] <= 1500 and top["end_ms"] >= 1000
    assert "scene" in top["sources"]


def test_candidate_windows_empty_signals():
    assert signals.candidate_windows(6000, [], []) == []
