import json
import logging
import os
from typing import Optional

from . import db as dbm
from . import ffmpeg
from . import signals
from .config import Config
from .providers.mock import (
    MockAsrProvider, MockHighlightProvider, MockPackagingProvider,
)

_log = logging.getLogger(__name__)


def get_providers(config: Config):
    return _build_asr(config), _build_highlight(config), MockPackagingProvider()


def _build_highlight(config: Config):
    if config.highlight_provider in ("llm", "claude"):
        from .providers.llm_highlight import ClaudeHighlightProvider  # lazy: avoid import on mock path
        return ClaudeHighlightProvider(model=config.llm_model)
    if config.highlight_provider != "mock":
        _log.warning("Unknown HIGHLIGHT_PROVIDER %r; falling back to mock", config.highlight_provider)
    return MockHighlightProvider()


def _build_asr(config: Config):
    if config.asr_provider in ("whisper", "faster-whisper"):
        from .providers.whisper import WhisperAsrProvider  # lazy: avoid import on mock path
        return WhisperAsrProvider(
            model_size=config.whisper_model,
            device=config.whisper_device,
            compute_type=config.whisper_compute_type,
            language=config.whisper_language,
        )
    if config.asr_provider != "mock":
        _log.warning("Unknown ASR_PROVIDER %r; falling back to mock", config.asr_provider)
    return MockAsrProvider()


def _local_path_from_url(url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    if url.startswith("file://"):
        return url[len("file://"):]
    if os.path.exists(url):
        return url
    return None


def run_task(conn, config: Config, task: dict) -> None:
    task_id = task["id"]
    asr, highlight, packaging = get_providers(config)

    task_dir = os.path.join(config.storage_dir, task_id)
    os.makedirs(os.path.join(task_dir, "clips"), exist_ok=True)
    os.makedirs(os.path.join(task_dir, "covers"), exist_ok=True)

    src = _local_path_from_url(task.get("source_video_url", ""))

    # prepare_video（有源时抽 16k 单声道 wav 供真实 ASR；mock 忽略该路径）
    dbm.update_progress(conn, task_id, 5, "prepare_video")
    duration_ms = ffmpeg.probe_duration_ms(src) if src else None
    if not duration_ms:
        duration_ms = 20000
    audio_path = ""
    if src and getattr(asr, "needs_audio_file", True):
        audio_path = os.path.join(task_dir, "audio.wav")
        ffmpeg.extract_audio(src, audio_path)

    # transcribe_audio
    dbm.update_progress(conn, task_id, 20, "transcribe_audio")
    transcript = asr.transcribe(audio_path, duration_ms)
    with open(os.path.join(task_dir, "transcript.json"), "w", encoding="utf-8") as f:
        json.dump([s.__dict__ for s in transcript.segments], f, ensure_ascii=False)
    with open(os.path.join(task_dir, "zh-CN.vtt"), "w", encoding="utf-8") as f:
        f.write(transcript.vtt)

    # detect_scenes (mock; uniform from transcript)
    dbm.update_progress(conn, task_id, 35, "detect_scenes")
    scenes = [{"start_ms": s.start_ms, "end_ms": s.end_ms} for s in transcript.segments]
    with open(os.path.join(task_dir, "scenes.json"), "w", encoding="utf-8") as f:
        json.dump(scenes, f, ensure_ascii=False)

    # multi-signal candidate windows (audio energy + scene cuts; real source only)
    candidate_wins = []
    audio_features = {}
    if src:
        energy = signals.audio_energy_profile(audio_path) if audio_path else []
        scene_times = signals.scene_change_times(src)
        candidate_wins = signals.candidate_windows(duration_ms, energy, scene_times)
        audio_features = {"window_ms": 500, "energy_len": len(energy)}
        with open(os.path.join(task_dir, "signals.json"), "w", encoding="utf-8") as f:
            json.dump({"candidate_windows": candidate_wins, "audio_features": audio_features,
                       "scene_change_count": len(scene_times)}, f, ensure_ascii=False)

    # analyze_highlights (mock)
    dbm.update_progress(conn, task_id, 50, "analyze_highlights")
    target_scenarios = json.loads(task.get("target_scenarios") or '["feed"]')
    target_durations = json.loads(task.get("target_durations") or "[15]")
    target_aspect_ratios = json.loads(task.get("target_aspect_ratios") or '["9:16"]')
    target_languages = json.loads(task.get("target_languages") or '["zh-CN"]') or ["zh-CN"]
    tags = json.loads(task.get("tags") or "[]")
    highlights = highlight.analyze({
        "duration_ms": duration_ms,
        "clip_count": task.get("clip_count", 3),
        "target_scenarios": target_scenarios,
        "target_durations": target_durations,
        "transcript_segments": [
            {"start_ms": s.start_ms, "end_ms": s.end_ms, "text": s.text}
            for s in transcript.segments
        ],
        "content": {k: v for k, v in {
            "title": task.get("title"),
            "description": task.get("description"),
            "category": task.get("category"),
            "tags": tags,
        }.items() if v not in (None, "", [])},
        "candidate_windows": candidate_wins,
        "audio_features": audio_features,
    })

    # render + cover + packaging + persist
    dbm.update_progress(conn, task_id, 70, "render_clips")
    # TODO(post-M0): wrap the per-segment insert/render loop in a transaction (or add
    # cleanup-on-failure) so a mid-loop ffmpeg failure doesn't leave partial segments/assets.
    for idx, seg in enumerate(highlights):
        seg_id = dbm.new_id("segment")
        pack = packaging.generate({"index": idx, "tags": tags})
        dbm.insert_segment(conn, {
            "id": seg_id, "task_id": task_id, "source_content_id": task["source_content_id"],
            "start_ms": seg.start_ms, "end_ms": seg.end_ms,
            "duration_ms": seg.end_ms - seg.start_ms, "highlight_type": seg.highlight_type,
            "score": seg.score, "reason": seg.reason, "summary": seg.summary,
            "transcript_text": seg.transcript_text, "risk_level": seg.risk_level,
            "risk_reason": seg.risk_reason,
            "packaging_draft": {
                "title": pack.title, "cover_text": pack.cover_text,
                "recommendation_text": pack.recommendation_text, "tags": pack.tags,
            },
            "status": "candidate",
        })

        cover_url = None
        if src:
            cover_path = os.path.join(task_dir, "covers", f"{seg_id}.jpg")
            try:
                ffmpeg.extract_frame(src, seg.start_ms + 500, cover_path)
                cover_url = f"/storage/{task_id}/covers/{seg_id}.jpg"
            except ffmpeg.FfmpegError:
                cover_url = None

        for duration in target_durations:
            for ar in target_aspect_ratios:
                asset_id = dbm.new_id("asset")
                rel_video = f"/storage/{task_id}/clips/{asset_id}.mp4"
                out_path = os.path.join(task_dir, "clips", f"{asset_id}.mp4")
                if src:
                    ffmpeg.cut_clip(src, seg.start_ms, duration * 1000, ar, out_path)
                else:
                    with open(out_path, "wb") as f:  # stub: 占位空文件
                        f.write(b"")
                dbm.insert_asset(conn, {
                    "id": asset_id, "task_id": task_id, "segment_id": seg_id,
                    "source_content_id": task["source_content_id"],
                    "scenario": seg.recommended_scenario, "duration": duration, "aspect_ratio": ar,
                    "language": target_languages[0], "video_url": rel_video, "cover_url": cover_url,
                    "subtitle_url": f"/storage/{task_id}/zh-CN.vtt",
                    "title": pack.title, "cover_text": pack.cover_text,
                    "recommendation_text": pack.recommendation_text, "tags": pack.tags,
                    "status": "pending_review",
                })

    # quality_check (basic; M0 仅占位推进)
    dbm.update_progress(conn, task_id, 95, "quality_check")

    dbm.mark_succeeded(conn, task_id)
