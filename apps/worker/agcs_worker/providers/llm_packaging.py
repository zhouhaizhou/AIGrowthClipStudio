import json as _json
import logging
from typing import List

from .base import Packaging

_log = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "你是短剧增长运营。为一个高光片段生成运营包装文案：标题适合推荐流点击但不夸大到与剧情不符；"
    "封面文案短、有冲突、最多12个中文字符；推荐语说明适合的场景；标签从片段真实信息提炼。"
    "避免低俗、违法、歧视、明显标题党。务必通过 report_packaging 工具返回。"
)

PACKAGING_TOOL = {
    "name": "report_packaging",
    "description": "Report marketing packaging for one highlight clip.",
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "coverText": {"type": "string"},
            "recommendationText": {"type": "string"},
            "tags": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["title", "coverText", "recommendationText", "tags"],
    },
}


def _build_user(ctx: dict) -> str:
    content = ctx.get("content") or {}
    return (
        f"内容元信息：{_json.dumps(content, ensure_ascii=False)}\n"
        f"片段高光类型：{ctx.get('highlight_type', '')}\n"
        f"目标场景：{ctx.get('scenario', 'feed')}\n"
        f"片段时长(ms)：{ctx.get('duration_ms', 0)}\n"
        f"片段摘要：{ctx.get('summary', '')}\n"
        f"片段字幕：{ctx.get('transcript_text', '')}"
    )


def _extract_tool_input(resp) -> dict:
    for block in getattr(resp, "content", []) or []:
        if getattr(block, "type", None) == "tool_use" and getattr(block, "name", None) == "report_packaging":
            raw = block.input
            return raw if isinstance(raw, dict) else {}
    return {}


def _clean_tags(raw_tags, fallback) -> List[str]:
    safe_fallback = [t.strip() for t in (fallback if isinstance(fallback, list) else [])
                     if isinstance(t, str) and t.strip()][:6]
    if not isinstance(raw_tags, list):
        return safe_fallback
    out: List[str] = []
    for t in raw_tags:
        if isinstance(t, str):
            s = t.strip()
            if s and s not in out:
                out.append(s)
    return out[:6] if out else safe_fallback


def _to_packaging(raw: dict, ctx: dict, cover_max: int) -> Packaging:
    def _s(key: str) -> str:
        v = raw.get(key)
        return v.strip() if isinstance(v, str) else ""

    title = _s("title") or "精彩片段"
    cover = (_s("coverText") or title)[:cover_max]
    rec = _s("recommendationText") or "高能片段，适合推荐流测试。"
    tags = _clean_tags(raw.get("tags"), ctx.get("tags") or [])
    return Packaging(title=title, cover_text=cover, recommendation_text=rec, tags=tags)


class ClaudePackagingProvider:
    def __init__(self, client=None, model: str = "claude-sonnet-4-6",
                 max_tokens: int = 1024, cover_max: int = 12):
        self._client = client
        self._model = model
        self._max_tokens = max_tokens
        self._cover_max = cover_max

    def _ensure_client(self):
        if self._client is None:
            import anthropic  # lazy: only needed for real LLM calls
            self._client = anthropic.Anthropic()
        return self._client

    def generate(self, ctx: dict) -> Packaging:
        client = self._ensure_client()
        resp = client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
            tools=[PACKAGING_TOOL],
            tool_choice={"type": "tool", "name": "report_packaging"},
            messages=[{"role": "user", "content": _build_user(ctx)}],
        )
        raw = _extract_tool_input(resp)
        if not raw:
            _log.warning("ClaudePackagingProvider: no report_packaging tool_use block in response")
        return _to_packaging(raw, ctx, self._cover_max)
