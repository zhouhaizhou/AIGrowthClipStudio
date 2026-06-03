import os

import pytest

_RUN = os.environ.get("RUN_LLM_TESTS") == "1"
_HAS_KEY = bool(os.environ.get("ANTHROPIC_API_KEY"))
try:
    import anthropic  # noqa: F401
    _HAS_SDK = True
except Exception:
    _HAS_SDK = False

pytestmark = pytest.mark.skipif(
    not (_RUN and _HAS_SDK and _HAS_KEY),
    reason="needs RUN_LLM_TESTS=1, anthropic installed, ANTHROPIC_API_KEY set",
)


def test_real_claude_highlight():
    from agcs_worker.providers.llm_highlight import ClaudeHighlightProvider

    transcript = [
        {"start_ms": 0, "end_ms": 4000, "text": "你不过是个没人要的女人。"},
        {"start_ms": 4000, "end_ms": 8000, "text": "等等，她竟然是董事长的女儿。"},
        {"start_ms": 8000, "end_ms": 12000, "text": "全场瞬间安静了。"},
    ]
    segs = ClaudeHighlightProvider().analyze({
        "duration_ms": 12000, "clip_count": 2, "target_scenarios": ["feed"],
        "transcript_segments": transcript,
        "content": {"title": "退婚后身份曝光", "category": "短剧"},
    })
    assert len(segs) >= 1
    for s in segs:
        assert 0 <= s.start_ms < s.end_ms <= 12000
        assert s.highlight_type
        assert 0.0 <= s.score <= 1.0
