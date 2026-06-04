# audioop: deprecated in Python 3.11, removed in 3.13. OK on 3.9; replace with a
# struct-based RMS (or soundfile) when upgrading Python.
import audioop
import re
import subprocess
import wave
from typing import List


def audio_energy_profile(wav_path: str, window_ms: int = 500) -> List[int]:
    """RMS energy per window_ms window of a PCM wav. Returns [] on any read failure.
    Note: loads the whole wav into memory (fine for short clips)."""
    try:
        with wave.open(wav_path, "rb") as w:
            sr = w.getframerate()
            sw = w.getsampwidth()
            ch = w.getnchannels()
            data = w.readframes(w.getnframes())
    except (wave.Error, EOFError, OSError):
        return []
    if not data or sr <= 0:
        return []
    if ch == 2:
        data = audioop.tomono(data, sw, 0.5, 0.5)
    elif ch > 2:
        # tomono is stereo-only; for >2 channels take the first channel
        frame = sw * ch
        data = b"".join(data[i:i + sw] for i in range(0, len(data), frame))
    win_bytes = max(sw, int(sr * window_ms / 1000) * sw)
    profile = []
    for off in range(0, len(data), win_bytes):
        chunk = data[off:off + win_bytes]
        if len(chunk) >= sw:
            profile.append(audioop.rms(chunk, sw))
    return profile


def _parse_scene_times(stderr: str) -> List[float]:
    out = []
    for m in re.findall(r"pts_time:([0-9.]+)", stderr or ""):
        try:
            out.append(float(m))
        except ValueError:
            continue
    return out


def scene_change_times(video_path: str, threshold: float = 0.3) -> List[float]:
    """Scene-change timestamps (seconds) via ffmpeg scene detection. Returns [] on failure."""
    cmd = ["ffmpeg", "-hide_banner", "-nostats", "-i", video_path,
           "-vf", f"select='gt(scene,{threshold})',showinfo", "-an", "-f", "null", "-"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    except Exception:
        return []
    return _parse_scene_times(proc.stderr)


def candidate_windows(duration_ms: int, energy_profile: List[int], scene_times: List[float],
                      window_ms: int = 500, scene_weight: float = 1.0,
                      clip_ms: int = 8000, top_k: int = 6) -> List[dict]:
    """Fuse audio energy + scene cuts into ranked candidate windows.
    Each window scored = normalized_energy + scene_weight*scene_count; the highest-scoring
    window centers are expanded to clip_ms-wide windows, overlap-deduped, top_k kept.
    Returns [{start_ms, end_ms, score, sources}], score desc. Empty signals -> []."""
    if duration_ms <= 0 or window_ms <= 0:
        return []
    num_windows = (duration_ms + window_ms - 1) // window_ms
    max_e = max(energy_profile) if energy_profile else 0
    scored = []
    for i in range(num_windows):
        win_start = i * window_ms
        win_end = min(win_start + window_ms, duration_ms)
        e = energy_profile[i] if i < len(energy_profile) else 0
        e_norm = (e / max_e) if max_e > 0 else 0.0
        scene_count = sum(1 for t in scene_times if win_start <= t * 1000 < win_end)
        score = e_norm + scene_weight * scene_count
        if score <= 0:
            continue
        sources = []
        if e_norm > 0:
            sources.append("audio")
        if scene_count > 0:
            sources.append("scene")
        center = (win_start + win_end) // 2
        scored.append((score, center, sources))
    scored.sort(key=lambda x: x[0], reverse=True)
    out: List[dict] = []
    for score, center, sources in scored:
        start = max(0, center - clip_ms // 2)
        end = min(duration_ms, start + clip_ms)
        start = max(0, end - clip_ms)
        if any(not (end <= c["start_ms"] or start >= c["end_ms"]) for c in out):
            continue
        out.append({"start_ms": start, "end_ms": end, "score": round(score, 4), "sources": sources})
        if len(out) >= top_k:
            break
    return out
