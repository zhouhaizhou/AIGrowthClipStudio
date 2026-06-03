import os
import shutil
import subprocess

import pytest

from agcs_worker import db as dbm

HERE = os.path.dirname(os.path.abspath(__file__))           # apps/worker/tests
ROOT = os.path.normpath(os.path.join(HERE, "..", "..", "..")) # repo root
SCHEMA = os.path.join(ROOT, "db", "schema.sql")


@pytest.fixture
def conn(tmp_path):
    db_path = str(tmp_path / "t.db")
    c = dbm.connect(db_path)
    with open(SCHEMA, "r", encoding="utf-8") as f:
        c.executescript(f.read())
    c.commit()
    yield c
    c.close()


@pytest.fixture(scope="session")
def sample_video(tmp_path_factory):
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg not available")
    out = str(tmp_path_factory.mktemp("media") / "sample.mp4")
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=duration=20:size=1280x720:rate=25",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=20",
         "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest", out],
        check=True, capture_output=True,
    )
    return out


def insert_queued_task(conn, source_video_url=""):
    conn.execute(
        "INSERT INTO ai_clip_tasks (id, source_content_id, source_content_type, source_video_url, "
        "tags, target_scenarios, target_durations, target_aspect_ratios, target_languages, clip_count, "
        "status, progress, created_at, updated_at) VALUES "
        "(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("task_t", "12345", "episode", source_video_url, "[]", '["feed"]', "[15]",
         '["9:16"]', '["zh-CN"]', 3, "queued", 0, 1, 1),
    )
    conn.commit()
