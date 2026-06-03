from agcs_worker import db as dbm
from agcs_worker.config import Config
from agcs_worker.pipeline import run_task


def _cfg(tmp_path):
    return Config(db_path="", storage_dir=str(tmp_path / "storage"),
                  poll_interval_ms=1000, asr_provider="mock",
                  highlight_provider="mock", packaging_provider="mock")


def _insert_running_task(conn, source_video_url):
    conn.execute(
        "INSERT INTO ai_clip_tasks (id, source_content_id, source_content_type, source_video_url, "
        "tags, target_scenarios, target_durations, target_aspect_ratios, target_languages, clip_count, "
        "status, progress, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("task_p", "12345", "episode", source_video_url, "[]", '["feed"]', "[15]",
         '["9:16"]', '["zh-CN"]', 3, "running", 1, 1, 1),
    )
    conn.commit()
    return dict(conn.execute("SELECT * FROM ai_clip_tasks WHERE id='task_p'").fetchone())


def test_run_task_with_real_video(conn, sample_video, tmp_path):
    task = _insert_running_task(conn, f"file://{sample_video}")
    run_task(conn, _cfg(tmp_path), task)
    segs = conn.execute("SELECT * FROM ai_clip_segments WHERE task_id='task_p'").fetchall()
    assets = conn.execute("SELECT * FROM ai_clip_assets WHERE task_id='task_p'").fetchall()
    assert len(segs) == 3
    assert len(assets) == 3  # 3 segments × 1 duration × 1 aspect_ratio
    status = conn.execute("SELECT status FROM ai_clip_tasks WHERE id='task_p'").fetchone()["status"]
    assert status == "succeeded"
    # 真实 ffmpeg 产出非空 mp4：video_url 形如 /storage/<taskId>/clips/<assetId>.mp4
    import os
    rel = assets[0]["video_url"].replace("/storage/", "", 1)
    clip_path = os.path.join(str(tmp_path / "storage"), rel)
    assert os.path.exists(clip_path) and os.path.getsize(clip_path) > 0


def test_run_task_stub_without_video(conn, tmp_path):
    task = _insert_running_task(conn, "")
    run_task(conn, _cfg(tmp_path), task)
    status = conn.execute("SELECT status FROM ai_clip_tasks WHERE id='task_p'").fetchone()["status"]
    assert status == "succeeded"
    assert conn.execute("SELECT COUNT(*) c FROM ai_clip_assets").fetchone()["c"] == 3
