from agcs_worker.config import Config
from agcs_worker.pipeline import get_providers, _build_asr
from agcs_worker.providers.mock import MockAsrProvider
from agcs_worker.providers.whisper import WhisperAsrProvider


def _cfg(asr):
    return Config(db_path="", storage_dir="", poll_interval_ms=1000,
                  asr_provider=asr, highlight_provider="mock", packaging_provider="mock",
                  whisper_model="base", whisper_device="cpu", whisper_compute_type="int8",
                  whisper_language="", llm_model="claude-sonnet-4-6")


def test_default_uses_mock_asr():
    asr, _h, _p = get_providers(_cfg("mock"))
    assert isinstance(asr, MockAsrProvider)


def test_whisper_selects_whisper_provider_without_loading_model():
    # 构造 provider 不应加载/下载 faster-whisper 模型（懒加载）
    asr = _build_asr(_cfg("whisper"))
    assert isinstance(asr, WhisperAsrProvider)


def test_unknown_asr_provider_falls_back_to_mock():
    asr = _build_asr(_cfg("whsiper"))  # typo → must fall back to mock
    assert isinstance(asr, MockAsrProvider)


def test_provider_audio_capability_flags():
    assert _build_asr(_cfg("mock")).needs_audio_file is False
    assert _build_asr(_cfg("whisper")).needs_audio_file is True


def test_default_uses_mock_highlight():
    from agcs_worker.providers.mock import MockHighlightProvider
    _a, h, _p = get_providers(_cfg("mock"))
    assert isinstance(h, MockHighlightProvider)


def test_llm_selects_claude_highlight_without_client():
    from agcs_worker.pipeline import _build_highlight
    from agcs_worker.providers.llm_highlight import ClaudeHighlightProvider
    cfg = _cfg("mock")
    cfg.highlight_provider = "llm"
    h = _build_highlight(cfg)
    assert isinstance(h, ClaudeHighlightProvider)


def test_unknown_highlight_provider_falls_back_to_mock():
    from agcs_worker.pipeline import _build_highlight
    from agcs_worker.providers.mock import MockHighlightProvider
    cfg = _cfg("mock")
    cfg.highlight_provider = "typo"
    assert isinstance(_build_highlight(cfg), MockHighlightProvider)


def test_default_uses_mock_packaging():
    from agcs_worker.providers.mock import MockPackagingProvider
    _a, _h, p = get_providers(_cfg("mock"))
    assert isinstance(p, MockPackagingProvider)


def test_llm_selects_claude_packaging_without_client():
    from agcs_worker.pipeline import _build_packaging
    from agcs_worker.providers.llm_packaging import ClaudePackagingProvider
    cfg = _cfg("mock")
    cfg.packaging_provider = "llm"
    assert isinstance(_build_packaging(cfg), ClaudePackagingProvider)


def test_unknown_packaging_provider_falls_back_to_mock():
    from agcs_worker.pipeline import _build_packaging
    from agcs_worker.providers.mock import MockPackagingProvider
    cfg = _cfg("mock")
    cfg.packaging_provider = "typo"
    assert isinstance(_build_packaging(cfg), MockPackagingProvider)
