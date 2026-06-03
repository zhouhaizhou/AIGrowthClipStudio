import subprocess
from typing import Optional


class FfmpegError(RuntimeError):
    pass


# 注意：crop 表达式假设输入为横屏（宽 >= 目标比例所需）。M0 样例为 1280x720 横屏，满足。
# 竖屏源后续在真实路径里再补主体检测，详见 02 设计 §4.5。
ASPECT_FILTERS = {
    "9:16": "crop=ih*9/16:ih,scale=720:1280,setsar=1",
    "16:9": "scale=1280:720,setsar=1",
    "1:1": "crop=ih:ih,scale=720:720,setsar=1",
    "4:5": "crop=ih*4/5:ih,scale=720:900,setsar=1",
}


def _run(cmd: list[str], timeout: int = 300) -> str:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        raise FfmpegError(f"{cmd[0]} timed out after {timeout}s") from e
    if proc.returncode != 0:
        raise FfmpegError(f"{cmd[0]} failed ({proc.returncode}): {proc.stderr[-500:]}")
    return proc.stdout


def probe_duration_ms(path: str) -> Optional[int]:
    try:
        out = _run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                    "-of", "default=nw=1:nk=1", path]).strip()
    except FfmpegError:
        return None
    if not out:
        return None
    try:
        return int(float(out) * 1000)
    except ValueError:
        return None


def cut_clip(src: str, start_ms: int, dur_ms: int, aspect_ratio: str, out_path: str) -> None:
    if aspect_ratio not in ASPECT_FILTERS:
        raise ValueError(
            f"Unknown aspect_ratio {aspect_ratio!r}; expected one of {list(ASPECT_FILTERS)}"
        )
    vf = ASPECT_FILTERS[aspect_ratio]
    _run(["ffmpeg", "-y", "-ss", f"{start_ms / 1000:.3f}", "-i", src,
          "-t", f"{dur_ms / 1000:.3f}", "-vf", vf,
          "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac",
          "-movflags", "+faststart", out_path])


def extract_frame(src: str, at_ms: int, out_path: str) -> None:
    _run(["ffmpeg", "-y", "-ss", f"{at_ms / 1000:.3f}", "-i", src,
          "-frames:v", "1", "-q:v", "3", out_path])


def extract_audio(src: str, out_path: str) -> None:
    _run(["ffmpeg", "-y", "-i", src, "-vn", "-ac", "1", "-ar", "16000",
          "-c:a", "pcm_s16le", out_path])
