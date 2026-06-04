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


def test_real_claude_packaging():
    from agcs_worker.providers.llm_packaging import ClaudePackagingProvider

    pack = ClaudePackagingProvider().generate({
        "summary": "女主被当众退婚后，真实身份曝光。",
        "transcript_text": "你不过是个没人要的女人。等等，她竟然是董事长的女儿。",
        "highlight_type": "reversal", "scenario": "feed", "duration_ms": 15000,
        "tags": ["逆袭", "豪门"], "content": {"title": "退婚后身份曝光", "category": "短剧"},
    })
    assert pack.title.strip()
    assert pack.cover_text.strip() and len(pack.cover_text) <= 12
    assert pack.recommendation_text.strip()
    assert isinstance(pack.tags, list)
