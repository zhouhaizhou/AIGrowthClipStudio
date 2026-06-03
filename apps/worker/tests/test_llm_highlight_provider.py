from agcs_worker.providers.llm_highlight import ClaudeHighlightProvider


class _FakeBlock:
    def __init__(self, payload):
        self.type = "tool_use"
        self.name = "report_highlights"
        self.input = payload


class _FakeResp:
    def __init__(self, segments):
        self.content = [_FakeBlock({"segments": segments})]


class _FakeMessages:
    def __init__(self, segments):
        self._segments = segments
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return _FakeResp(self._segments)


class _FakeClient:
    def __init__(self, segments):
        self.messages = _FakeMessages(segments)


TRANSCRIPT = [
    {"start_ms": 0, "end_ms": 4000, "text": "你不过是个没人要的女人。"},
    {"start_ms": 4000, "end_ms": 8000, "text": "等等，她竟然是董事长的女儿。"},
]


def _ctx():
    return {"duration_ms": 8000, "clip_count": 3, "target_scenarios": ["feed", "membership"],
            "transcript_segments": TRANSCRIPT, "content": {"title": "x"}}


def test_maps_and_grounds_transcript_text():
    raw = [{"startMs": 0, "endMs": 4000, "highlightType": "conflict", "score": 0.9,
            "reason": "r", "summary": "s", "recommendedScenario": "feed", "riskLevel": "low"}]
    segs = ClaudeHighlightProvider(client=_FakeClient(raw)).analyze(_ctx())
    assert len(segs) == 1
    assert segs[0].start_ms == 0 and segs[0].end_ms == 4000
    assert segs[0].highlight_type == "conflict"
    assert segs[0].transcript_text == "你不过是个没人要的女人。"   # grounded, not from LLM


def test_clamps_bounds_score_and_scenario():
    raw = [{"startMs": -500, "endMs": 999999, "highlightType": "reversal", "score": 5,
            "reason": "r", "summary": "s", "recommendedScenario": "social", "riskLevel": "low"}]
    segs = ClaudeHighlightProvider(client=_FakeClient(raw)).analyze(_ctx())
    assert segs[0].start_ms == 0 and segs[0].end_ms == 8000
    assert segs[0].score == 1.0
    assert segs[0].recommended_scenario == "feed"   # 'social' not in targets -> first


def test_drops_invalid_type_and_zero_length():
    raw = [
        {"startMs": 0, "endMs": 0, "highlightType": "conflict", "score": 0.5,
         "reason": "", "summary": "", "recommendedScenario": "feed", "riskLevel": "low"},
        {"startMs": 0, "endMs": 1000, "highlightType": "not_a_type", "score": 0.5,
         "reason": "", "summary": "", "recommendedScenario": "feed", "riskLevel": "low"},
    ]
    assert ClaudeHighlightProvider(client=_FakeClient(raw)).analyze(_ctx()) == []


def test_empty_transcript_returns_empty_without_client():
    p = ClaudeHighlightProvider(client=None)  # client must never be touched
    assert p.analyze({"transcript_segments": [], "duration_ms": 1000}) == []


def test_sorts_by_score_and_caps_clip_count():
    raw = [
        {"startMs": 0, "endMs": 1000, "highlightType": "emotion", "score": 0.2,
         "reason": "", "summary": "", "recommendedScenario": "feed", "riskLevel": "low"},
        {"startMs": 1000, "endMs": 2000, "highlightType": "emotion", "score": 0.9,
         "reason": "", "summary": "", "recommendedScenario": "feed", "riskLevel": "low"},
        {"startMs": 2000, "endMs": 3000, "highlightType": "emotion", "score": 0.5,
         "reason": "", "summary": "", "recommendedScenario": "feed", "riskLevel": "low"},
    ]
    ctx = _ctx()
    ctx["clip_count"] = 2
    segs = ClaudeHighlightProvider(client=_FakeClient(raw)).analyze(ctx)
    assert [s.score for s in segs] == [0.9, 0.5]
