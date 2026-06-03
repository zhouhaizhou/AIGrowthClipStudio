import json
import sqlite3
import time
import uuid


def now_ms() -> int:
    return int(time.time() * 1000)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# worker_id is currently unused; reserved for a future worker-affinity column.
def claim_next_task(conn: sqlite3.Connection, worker_id: str):
    row = conn.execute(
        "SELECT id FROM ai_clip_tasks WHERE status='queued' ORDER BY created_at ASC LIMIT 1"
    ).fetchone()
    if row is None:
        return None
    cur = conn.execute(
        "UPDATE ai_clip_tasks SET status='running', progress=1, current_step='claimed', updated_at=? "
        "WHERE id=? AND status='queued'",
        (now_ms(), row["id"]),
    )
    if cur.rowcount != 1:
        conn.rollback()
        return None  # lost the race to another worker
    conn.commit()
    return dict(conn.execute("SELECT * FROM ai_clip_tasks WHERE id=?", (row["id"],)).fetchone())


def update_progress(conn: sqlite3.Connection, task_id: str, progress: int, current_step: str) -> None:
    conn.execute(
        "UPDATE ai_clip_tasks SET progress=?, current_step=?, updated_at=? WHERE id=?",
        (progress, current_step, now_ms(), task_id),
    )
    conn.commit()


def mark_succeeded(conn: sqlite3.Connection, task_id: str) -> None:
    conn.execute(
        "UPDATE ai_clip_tasks SET status='succeeded', progress=100, current_step='done', updated_at=? "
        "WHERE id=?",
        (now_ms(), task_id),
    )
    conn.commit()


def mark_failed(conn: sqlite3.Connection, task_id: str, error_message: str) -> None:
    conn.execute(
        "UPDATE ai_clip_tasks SET status='failed', error_message=?, updated_at=? WHERE id=?",
        (error_message[:1000], now_ms(), task_id),
    )
    conn.commit()


def insert_segment(conn: sqlite3.Connection, seg: dict) -> None:
    pd = seg.get("packaging_draft")
    packaging_draft = json.dumps(pd, ensure_ascii=False) if pd is not None else None
    conn.execute(
        "INSERT INTO ai_clip_segments (id, task_id, source_content_id, start_ms, end_ms, duration_ms, "
        "highlight_type, score, reason, summary, transcript_text, risk_level, risk_reason, "
        "packaging_draft, status, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (seg["id"], seg["task_id"], seg["source_content_id"], seg["start_ms"], seg["end_ms"],
         seg["duration_ms"], seg["highlight_type"], seg["score"], seg.get("reason"), seg.get("summary"),
         seg.get("transcript_text"), seg["risk_level"], seg.get("risk_reason"),
         packaging_draft,
         seg.get("status", "candidate"), now_ms(), now_ms()),
    )
    conn.commit()


def insert_asset(conn: sqlite3.Connection, a: dict) -> None:
    conn.execute(
        "INSERT INTO ai_clip_assets (id, task_id, segment_id, source_content_id, scenario, duration, "
        "aspect_ratio, language, video_url, cover_url, subtitle_url, title, cover_text, "
        "recommendation_text, tags, status, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (a["id"], a["task_id"], a["segment_id"], a["source_content_id"], a["scenario"], a["duration"],
         a["aspect_ratio"], a["language"], a["video_url"], a.get("cover_url"), a.get("subtitle_url"),
         a.get("title"), a.get("cover_text"), a.get("recommendation_text"),
         json.dumps(a.get("tags", []), ensure_ascii=False), a.get("status", "pending_review"),
         now_ms(), now_ms()),
    )
    conn.commit()
