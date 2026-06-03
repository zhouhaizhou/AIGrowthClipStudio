from typing import List

from .base import (
    Transcript, TranscriptSegment, HighlightSegment, Packaging,
)


class MockAsrProvider:
    needs_audio_file = False
    LINES = [
        "你不过是个没人要的女人。",
        "等等，她竟然是董事长的女儿。",
        "全场瞬间安静了。",
        "这一次，轮到你后悔了。",
        "故事才刚刚开始。",
    ]

    def transcribe(self, audio_path: str, duration_ms: int) -> Transcript:
        total = duration_ms or 10000
        step = max(2000, total // 5)
        segs: List[TranscriptSegment] = []
        t = 0
        i = 0
        while t < total and i < len(self.LINES):
            segs.append(TranscriptSegment(start_ms=t, end_ms=min(t + step, total), text=self.LINES[i]))
            t += step
            i += 1
        vtt = "WEBVTT\n\n" + "\n\n".join(f"{s.start_ms} --> {s.end_ms}\n{s.text}" for s in segs)
        return Transcript(segments=segs, vtt=vtt)


class MockHighlightProvider:
    TYPES = ["reversal", "conflict", "emotion", "suspense", "funny"]

    def analyze(self, ctx: dict) -> List[HighlightSegment]:
        duration_ms = ctx.get("duration_ms") or 10000
        clip_count = ctx.get("clip_count", 3)
        scenarios = ctx.get("target_scenarios") or ["feed"]
        win = max(3000, duration_ms // (clip_count + 1))
        out: List[HighlightSegment] = []
        for i in range(clip_count):
            start = min(i * win, max(0, duration_ms - win))
            end = min(start + win, duration_ms)
            out.append(HighlightSegment(
                start_ms=start, end_ms=end, highlight_type=self.TYPES[i % len(self.TYPES)],
                score=round(max(0.0, 0.9 - i * 0.05), 2),
                reason="mock：信号缺失，基于占位规则选取（详见 02 设计的多信号方案）",
                summary=f"高光片段 {i + 1}", transcript_text="（mock 字幕摘要）",
                risk_level="low", recommended_scenario=scenarios[i % len(scenarios)],
            ))
        return out


class MockPackagingProvider:
    TITLES = ["退婚当天，她身份曝光", "全场后悔的一刻", "她的反击开始了"]

    def generate(self, ctx: dict) -> Packaging:
        idx = ctx.get("index", 0)
        tags = ctx.get("tags") or ["逆袭", "反转"]
        return Packaging(
            title=self.TITLES[idx % len(self.TITLES)],
            cover_text="全场后悔",
            recommendation_text="强反转开局，适合推荐流首屏测试。",
            tags=tags,
        )
