from agcs_worker.config import Config
from agcs_worker.pipeline import get_providers, _build_asr
from agcs_worker.providers.mock import MockAsrProvider
from agcs_worker.providers.whisper import WhisperAsrProvider


def _cfg(asr):
    return Config(db_path="", storage_dir="", poll_interval_ms=1000,
                  asr_provider=asr, highlight_provider="mock", packaging_provider="mock",
                  whisper_model="base", whisper_device="cpu", whisper_compute_type="int8",
                  whisper_language="")


def test_default_uses_mock_asr():
    asr, _h, _p = get_providers(_cfg("mock"))
    assert isinstance(asr, MockAsrProvider)


def test_whisper_selects_whisper_provider_without_loading_model():
    # 构造 provider 不应加载/下载 faster-whisper 模型（懒加载）
    asr = _build_asr(_cfg("whisper"))
    assert isinstance(asr, WhisperAsrProvider)
