from agcs_worker.providers.mock import (
    MockAsrProvider, MockHighlightProvider, MockPackagingProvider,
)


def test_mock_asr_returns_segments_and_vtt():
    t = MockAsrProvider().transcribe("", 10000)
    assert len(t.segments) >= 1
    assert t.vtt.startswith("WEBVTT")


def test_mock_highlight_respects_clip_count():
    segs = MockHighlightProvider().analyze(
        {"duration_ms": 20000, "clip_count": 3, "target_scenarios": ["feed", "membership"]}
    )
    assert len(segs) == 3
    assert all(s.end_ms > s.start_ms for s in segs)
    assert all(s.recommended_scenario in ("feed", "membership") for s in segs)


def test_mock_packaging_builds_copy():
    p = MockPackagingProvider().generate({"index": 0, "tags": ["逆袭"]})
    assert p.title
    assert "逆袭" in p.tags
