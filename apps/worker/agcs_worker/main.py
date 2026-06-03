import argparse
import sys
import time

from . import db as dbm
from .config import load_config
from .pipeline import run_task


def process_once(conn, config) -> bool:
    task = dbm.claim_next_task(conn, worker_id="worker-1")
    if task is None:
        return False
    try:
        run_task(conn, config, task)
    except Exception as e:  # noqa: BLE001 - top-level guard: a task-level failure must not kill the worker
        try:
            dbm.mark_failed(conn, task["id"], f"{type(e).__name__}: {e}")
        except Exception:  # noqa: BLE001 - best-effort; task may stay 'running' (acceptable at M0)
            pass
    return True


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="AGCS worker")
    parser.add_argument("--once", action="store_true", help="process one task then exit")
    args = parser.parse_args(argv)

    config = load_config()
    conn = dbm.connect(config.db_path)

    if args.once:
        return 0 if process_once(conn, config) else 1

    try:
        while True:
            if not process_once(conn, config):
                time.sleep(config.poll_interval_ms / 1000)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
