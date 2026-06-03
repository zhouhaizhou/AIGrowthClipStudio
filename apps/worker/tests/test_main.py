from agcs_worker.config import Config
from agcs_worker.main import process_once
from conftest import insert_queued_task  # pytest prepend mode puts tests/ on sys.path


def _cfg(tmp_path):
    return Config(db_path="", storage_dir=str(tmp_path / "storage"),
                  poll_interval_ms=1000, asr_provider="mock",
                  highlight_provider="mock", packaging_provider="mock",
                  whisper_model="base", whisper_device="cpu",
                  whisper_compute_type="int8", whisper_language="")


def test_process_once_handles_one_then_empty(conn, tmp_path):
    insert_queued_task(conn, source_video_url="")  # stub path, no video needed
    assert process_once(conn, _cfg(tmp_path)) is True
    status = conn.execute("SELECT status FROM ai_clip_tasks WHERE id='task_t'").fetchone()["status"]
    assert status == "succeeded"
    # no more queued tasks
    assert process_once(conn, _cfg(tmp_path)) is False


def test_process_once_marks_failed_on_error(conn, tmp_path, monkeypatch):
    insert_queued_task(conn, source_video_url="")
    import agcs_worker.main as m
    monkeypatch.setattr(m, "run_task", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    assert process_once(conn, _cfg(tmp_path)) is True
    row = conn.execute("SELECT status, error_message FROM ai_clip_tasks WHERE id='task_t'").fetchone()
    assert row["status"] == "failed"
    assert "boom" in row["error_message"]
