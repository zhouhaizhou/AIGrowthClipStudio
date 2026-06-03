from agcs_worker import db as dbm
from conftest import insert_queued_task  # pytest prepend mode puts tests/ on sys.path


def test_claim_next_task_is_atomic(conn):
    insert_queued_task(conn)
    t = dbm.claim_next_task(conn, "w1")
    assert t is not None
    assert t["status"] == "running"
    # second claim finds nothing queued
    assert dbm.claim_next_task(conn, "w1") is None


def test_mark_failed(conn):
    insert_queued_task(conn)
    t = dbm.claim_next_task(conn, "w1")
    dbm.mark_failed(conn, t["id"], "boom")
    row = conn.execute(
        "SELECT status, error_message FROM ai_clip_tasks WHERE id=?", (t["id"],)
    ).fetchone()
    assert row["status"] == "failed"
    assert row["error_message"] == "boom"


def test_insert_segment_and_asset(conn):
    insert_queued_task(conn)
    dbm.insert_segment(conn, {
        "id": "seg_1", "task_id": "task_t", "source_content_id": "12345",
        "start_ms": 0, "end_ms": 5000, "duration_ms": 5000, "highlight_type": "reversal",
        "score": 0.9, "reason": "r", "summary": "s", "transcript_text": "t",
        "risk_level": "low", "risk_reason": None, "packaging_draft": {"title": "x"},
    })
    dbm.insert_asset(conn, {
        "id": "asset_1", "task_id": "task_t", "segment_id": "seg_1", "source_content_id": "12345",
        "scenario": "feed", "duration": 15, "aspect_ratio": "9:16", "language": "zh-CN",
        "video_url": "/storage/x.mp4", "title": "x", "cover_text": "c",
        "recommendation_text": "rec", "tags": ["a"],
    })
    assert conn.execute("SELECT COUNT(*) c FROM ai_clip_segments").fetchone()["c"] == 1
    assert conn.execute("SELECT COUNT(*) c FROM ai_clip_assets").fetchone()["c"] == 1
