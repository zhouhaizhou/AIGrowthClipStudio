import json

from agcs_worker.providers.claude_cli import (
    ClaudeCliHighlightProvider, ClaudeCliPackagingProvider,
    _extract_json_object, _run_and_parse, _default_runner, ClaudeCliError,
)


# ---- _extract_json_object ----

def test_extract_plain_object():
    assert _extract_json_object('{"a": 1}') == {"a": 1}


def test_extract_strips_json_fence():
    txt = "```json\n{\"a\": 1, \"b\": [2,3]}\n```"
    assert _extract_json_object(txt) == {"a": 1, "b": [2, 3]}


def test_extract_ignores_surrounding_prose():
    txt = "好的，结果如下：\n{\"title\": \"x\"}\n以上。"
    assert _extract_json_object(txt) == {"title": "x"}


def test_extract_garbage_returns_empty():
    assert _extract_json_object("no json here") == {}
    assert _extract_json_object("") == {}
    assert _extract_json_object("{not valid}") == {}


def test_extract_trailing_prose_after_json():
    assert _extract_json_object('{"a": 1}\n\n以上就是结果。') == {"a": 1}


def test_extract_handles_braces_inside_strings():
    assert _extract_json_object('{"t": "a{b}c", "n": 2}') == {"t": "a{b}c", "n": 2}


def test_extract_skips_stray_brace_then_finds_real_object():
    # a lone "{" in prose before the real object must not abort extraction
    assert _extract_json_object('note {incomplete then {"ok": true}') == {"ok": True}


def test_extract_nested_segments_object():
    txt = '{"segments":[{"startMs":1,"endMs":2,"highlightType":"reversal"}]}'
    assert _extract_json_object(txt)["segments"][0]["startMs"] == 1


def test_extract_repairs_unescaped_inner_quotes():
    # the real failure mode: model writes ASCII quotes inside a Chinese value
    txt = '{"reason":"反复出现"住"字叠喊","score":0.9}'
    obj = _extract_json_object(txt)
    assert obj["score"] == 0.9
    assert "住" in obj["reason"]


def test_extract_repairs_inner_quotes_with_trailing_prose():
    txt = '{"a":"他说"好"了"}\n完毕'
    assert _extract_json_object(txt)["a"].startswith("他说")


def test_extract_real_world_failing_segment_repairs():
    # condensed from an actual failing claude -p output (unescaped quotes around 住/活动)
    txt = ('{"segments":[{"startMs":73160,"endMs":82360,"highlightType":"conflict",'
           '"score":0.93,"reason":"反复出现"住"字叠喊，找年轻人做"卖命的活动"",'
           '"summary":"激烈对峙","recommendedScenario":"social","riskLevel":"low"}]}')
    obj = _extract_json_object(txt)
    assert len(obj["segments"]) == 1
    assert obj["segments"][0]["highlightType"] == "conflict"


# ---- _run_and_parse retry ----

def test_run_and_parse_retries_then_succeeds():
    calls = {"n": 0}
    def runner(prompt, model, timeout):
        calls["n"] += 1
        return "no json" if calls["n"] == 1 else '{"ok": true}'
    assert _run_and_parse(runner, "p", "m", 5) == {"ok": True}
    assert calls["n"] == 2


def test_run_and_parse_gives_up_returns_empty():
    calls = {"n": 0}
    def runner(prompt, model, timeout):
        calls["n"] += 1
        return "still no json"
    assert _run_and_parse(runner, "p", "m", 5, attempts=2) == {}
    assert calls["n"] == 2


def test_run_and_parse_retries_on_cli_error():
    calls = {"n": 0}
    def runner(prompt, model, timeout):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ClaudeCliError("transient")
        return '{"ok": 1}'
    assert _run_and_parse(runner, "p", "m", 5) == {"ok": 1}
    assert calls["n"] == 2


# ---- highlight provider ----

def _hl_ctx():
    return {
        "duration_ms": 30000, "clip_count": 2, "target_scenarios": ["feed", "ad"],
        "content": {"title": "测试"},
        "transcript_segments": [
            {"start_ms": 0, "end_ms": 6000, "text": "都给我听好了"},
            {"start_ms": 6000, "end_ms": 12000, "text": "她竟是董事长的女儿"},
        ],
        "candidate_windows": [{"start_ms": 0, "end_ms": 8000, "score": 1.0}],
    }


def _runner_returning(text):
    captured = {}
    def run(prompt, model, timeout):
        captured["prompt"] = prompt
        captured["model"] = model
        return text
    run.captured = captured
    return run


def test_highlight_parses_segments():
    payload = json.dumps({"segments": [
        {"startMs": 0, "endMs": 6000, "highlightType": "reversal", "score": 0.9,
         "reason": "强反转", "summary": "身份曝光", "recommendedScenario": "feed", "riskLevel": "low"},
    ]})
    runner = _runner_returning(payload)
    segs = ClaudeCliHighlightProvider(runner=runner).analyze(_hl_ctx())
    assert len(segs) == 1
    s = segs[0]
    assert s.start_ms == 0 and s.end_ms == 6000
    assert s.highlight_type == "reversal"
    assert s.recommended_scenario == "feed"
    # transcript_text is grounded from the real transcript, not invented
    assert "都给我听好了" in s.transcript_text


def test_highlight_prompt_includes_transcript_and_instruction():
    runner = _runner_returning('{"segments": []}')
    ClaudeCliHighlightProvider(runner=runner).analyze(_hl_ctx())
    p = runner.captured["prompt"]
    assert "她竟是董事长的女儿" in p          # real transcript fed in
    assert "只输出一个 JSON" in p or "只输出" in p  # JSON-only instruction appended


def test_highlight_empty_transcript_returns_empty_without_calling_runner():
    called = {"n": 0}
    def run(prompt, model, timeout):
        called["n"] += 1
        return "{}"
    ctx = _hl_ctx(); ctx["transcript_segments"] = []
    assert ClaudeCliHighlightProvider(runner=run).analyze(ctx) == []
    assert called["n"] == 0


def test_highlight_runner_error_falls_back_to_empty():
    def run(prompt, model, timeout):
        raise ClaudeCliError("boom")
    assert ClaudeCliHighlightProvider(runner=run).analyze(_hl_ctx()) == []


def test_highlight_garbage_output_returns_empty():
    assert ClaudeCliHighlightProvider(runner=_runner_returning("not json")).analyze(_hl_ctx()) == []


# ---- packaging provider ----

def _pk_ctx():
    return {"summary": "女主身份曝光", "transcript_text": "她竟是董事长的女儿。",
            "highlight_type": "reversal", "scenario": "feed", "duration_ms": 15000,
            "tags": ["逆袭"], "content": {"title": "退婚", "category": "短剧"}}


def test_packaging_parses_fenced_json():
    payload = "```json\n" + json.dumps({
        "title": "退婚当天身份曝光", "coverText": "全场后悔",
        "recommendationText": "强反转开局。", "tags": ["逆袭", "反转"]}) + "\n```"
    p = ClaudeCliPackagingProvider(runner=_runner_returning(payload)).generate(_pk_ctx())
    assert p.title == "退婚当天身份曝光"
    assert p.cover_text == "全场后悔"
    assert p.tags == ["逆袭", "反转"]


def test_packaging_cover_truncated_to_12():
    payload = json.dumps({"title": "t", "coverText": "这是一个非常非常非常长的封面文案超过十二个字",
                          "recommendationText": "r", "tags": []})
    p = ClaudeCliPackagingProvider(runner=_runner_returning(payload)).generate(_pk_ctx())
    assert len(p.cover_text) == 12


def test_packaging_garbage_falls_back():
    p = ClaudeCliPackagingProvider(runner=_runner_returning("totally not json")).generate(_pk_ctx())
    assert p.title == "精彩片段"
    assert p.tags == ["逆袭"]   # ctx fallback


def test_packaging_runner_error_falls_back():
    def run(prompt, model, timeout):
        raise ClaudeCliError("boom")
    p = ClaudeCliPackagingProvider(runner=run).generate(_pk_ctx())
    assert p.title == "精彩片段"


# ---- envelope parsing in _default_runner (no real subprocess) ----

def test_default_runner_extracts_result_field(monkeypatch):
    import agcs_worker.providers.claude_cli as mod

    class _Proc:
        returncode = 0
        stdout = json.dumps({"type": "result", "subtype": "success", "is_error": False,
                             "result": "{\"ok\": true}"})
        stderr = ""

    monkeypatch.setattr(mod.subprocess, "run", lambda *a, **k: _Proc())
    assert mod._default_runner("p", "claude-sonnet-4-6", 10) == '{"ok": true}'


def test_default_runner_raises_on_error_envelope(monkeypatch):
    import agcs_worker.providers.claude_cli as mod

    class _Proc:
        returncode = 0
        stdout = json.dumps({"type": "result", "subtype": "error_during_execution",
                             "is_error": True, "result": "quota exceeded"})
        stderr = ""

    monkeypatch.setattr(mod.subprocess, "run", lambda *a, **k: _Proc())
    try:
        mod._default_runner("p", "m", 10)
        assert False, "expected ClaudeCliError"
    except ClaudeCliError:
        pass


def test_default_runner_raises_on_nonzero(monkeypatch):
    import agcs_worker.providers.claude_cli as mod

    class _Proc:
        returncode = 1
        stdout = ""
        stderr = "boom"

    monkeypatch.setattr(mod.subprocess, "run", lambda *a, **k: _Proc())
    try:
        mod._default_runner("p", "m", 10)
        assert False, "expected ClaudeCliError"
    except ClaudeCliError:
        pass


# ---- pipeline wiring (no CLI invoked) ----

def _cfg(highlight="mock", packaging="mock"):
    from agcs_worker.config import Config
    return Config(db_path="", storage_dir="", poll_interval_ms=1000,
                  asr_provider="mock", highlight_provider=highlight, packaging_provider=packaging,
                  whisper_model="base", whisper_device="cpu", whisper_compute_type="int8",
                  whisper_language="", llm_model="claude-sonnet-4-6")


def test_pipeline_selects_cli_highlight():
    from agcs_worker.pipeline import _build_highlight
    assert isinstance(_build_highlight(_cfg(highlight="claude-cli")), ClaudeCliHighlightProvider)
    assert isinstance(_build_highlight(_cfg(highlight="cli")), ClaudeCliHighlightProvider)


def test_pipeline_selects_cli_packaging():
    from agcs_worker.pipeline import _build_packaging
    assert isinstance(_build_packaging(_cfg(packaging="claude-cli")), ClaudeCliPackagingProvider)
    assert isinstance(_build_packaging(_cfg(packaging="cli")), ClaudeCliPackagingProvider)
