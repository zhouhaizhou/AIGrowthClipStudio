import json as _json
from typing import List

from .base import HighlightSegment

ALLOWED_TYPES = ("conflict", "reversal", "emotion", "funny", "suspense",
                 "membership_conversion", "ad_hook")

SYSTEM_PROMPT = (
    "你是短剧增长素材导演。只能基于用户提供的字幕和元信息判断高光，"
    "绝不可编造字幕里不存在的剧情。片段起止时间必须落在字幕时间范围内，"
    "优先开头能抓人的冲突/反转/悬念/情绪片段。务必通过 report_highlights 工具返回结果。"
)

HIGHLIGHT_TOOL = {
    "name": "report_highlights",
    "description": "Report selected highlight segments grounded ONLY in the provided transcript.",
    "input_schema": {
        "type": "object",
        "properties": {
            "segments": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "startMs": {"type": "integer"},
                        "endMs": {"type": "integer"},
                        "highlightType": {"type": "string", "enum": list(ALLOWED_TYPES)},
                        "score": {"type": "number"},
                        "reason": {"type": "string"},
                        "summary": {"type": "string"},
                        "recommendedScenario": {"type": "string"},
                        "riskLevel": {"type": "string", "enum": ["low", "medium", "high"]},
                        "riskReason": {"type": "string"},
                    },
                    "required": ["startMs", "endMs", "highlightType", "score",
                                 "reason", "summary", "recommendedScenario", "riskLevel"],
                },
            },
        },
        "required": ["segments"],
    },
}


def _build_user(content: dict, transcript: list, scenarios: list,
                clip_count: int, duration_ms: int) -> str:
    lines = [f"[{t['start_ms']}-{t['end_ms']}] {t['text']}" for t in transcript]
    return (
        f"内容元信息：{_json.dumps(content, ensure_ascii=False)}\n"
        f"视频总时长(ms)：{duration_ms}\n"
        f"目标场景：{scenarios}\n"
        f"需要的高光数量：{clip_count}\n"
        f"字幕（每行 [起-止ms] 文本）：\n" + "\n".join(lines)
    )


def _extract_tool_input(resp) -> dict:
    for block in getattr(resp, "content", []) or []:
        if getattr(block, "type", None) == "tool_use" and getattr(block, "name", None) == "report_highlights":
            return block.input or {}
    return {}


def _grounded_text(transcript: list, start_ms: int, end_ms: int) -> str:
    return "".join(t["text"] for t in transcript
                   if t["end_ms"] > start_ms and t["start_ms"] < end_ms)


def _to_segments(raw_segments, transcript, duration_ms, scenarios, clip_count) -> List[HighlightSegment]:
    out: List[HighlightSegment] = []
    for r in raw_segments or []:
        try:
            start = int(r["startMs"])
            end = int(r["endMs"])
        except (KeyError, TypeError, ValueError):
            continue
        start = max(0, min(start, duration_ms))
        end = max(0, min(end, duration_ms))
        if end <= start:
            continue
        htype = r.get("highlightType")
        if htype not in ALLOWED_TYPES:
            continue
        try:
            score = max(0.0, min(1.0, float(r.get("score", 0.0))))
        except (TypeError, ValueError):
            score = 0.0
        scenario = r.get("recommendedScenario")
        if scenario not in scenarios:
            scenario = scenarios[0] if scenarios else "feed"
        risk = r.get("riskLevel") if r.get("riskLevel") in ("low", "medium", "high") else "low"
        out.append(HighlightSegment(
            start_ms=start, end_ms=end, highlight_type=htype, score=round(score, 4),
            reason=str(r.get("reason", "")), summary=str(r.get("summary", "")),
            transcript_text=_grounded_text(transcript, start, end),
            risk_level=risk, recommended_scenario=scenario,
            risk_reason=r.get("riskReason"),
        ))
    out.sort(key=lambda s: s.score, reverse=True)
    return out[:clip_count]


class ClaudeHighlightProvider:
    needs_audio_file = False

    def __init__(self, client=None, model: str = "claude-sonnet-4-6", max_tokens: int = 2048):
        self._client = client
        self._model = model
        self._max_tokens = max_tokens

    def _ensure_client(self):
        if self._client is None:
            import anthropic  # lazy: only needed for real LLM calls
            self._client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env
        return self._client

    def analyze(self, ctx: dict) -> List[HighlightSegment]:
        transcript = ctx.get("transcript_segments") or []
        if not transcript:
            return []
        duration_ms = ctx.get("duration_ms") or 0
        clip_count = ctx.get("clip_count", 3)
        scenarios = ctx.get("target_scenarios") or ["feed"]
        content = ctx.get("content") or {}
        client = self._ensure_client()
        resp = client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            system=[{"type": "text", "text": SYSTEM_PROMPT,
                     "cache_control": {"type": "ephemeral"}}],
            tools=[HIGHLIGHT_TOOL],
            tool_choice={"type": "tool", "name": "report_highlights"},
            messages=[{"role": "user",
                       "content": _build_user(content, transcript, scenarios, clip_count, duration_ms)}],
        )
        raw = _extract_tool_input(resp)
        return _to_segments(raw.get("segments", []), transcript, duration_ms, scenarios, clip_count)
