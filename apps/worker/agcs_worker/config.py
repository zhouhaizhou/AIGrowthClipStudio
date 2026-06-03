import os
from dataclasses import dataclass


def _load_env_file(path: str = ".env") -> None:
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


@dataclass
class Config:
    db_path: str
    storage_dir: str
    poll_interval_ms: int
    asr_provider: str
    highlight_provider: str
    packaging_provider: str


def load_config() -> Config:
    _load_env_file()
    return Config(
        db_path=os.environ.get("DB_PATH", "./data/agcs.db"),
        storage_dir=os.environ.get("STORAGE_DIR", "./storage"),
        poll_interval_ms=int(os.environ.get("WORKER_POLL_INTERVAL_MS", "1000")),
        asr_provider=os.environ.get("ASR_PROVIDER", "mock"),
        highlight_provider=os.environ.get("HIGHLIGHT_PROVIDER", "mock"),
        packaging_provider=os.environ.get("PACKAGING_PROVIDER", "mock"),
    )
