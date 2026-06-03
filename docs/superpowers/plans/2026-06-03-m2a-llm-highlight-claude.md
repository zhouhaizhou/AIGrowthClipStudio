# M2a — LLM 高光 Provider（Claude）+ 评测 harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用 Claude（tool-use 结构化输出）替换 mock 高光识别，基于字幕+元信息产出高光；`HIGHLIGHT_PROVIDER=llm` 时启用，默认仍 mock。配一个能对任意 provider 打 Top-3 命中率的评测 harness。

**Architecture:** 新增 `ClaudeHighlightProvider`（injectable client、懒导入 anthropic、tool-use 强制 JSON、反幻觉校验、grounded transcript_text），`get_providers` 加 `_build_highlight` 选择，pipeline 把字幕+元信息喂进 `analyze`。`evals/` 提供 iou + top3_hit_rate + run_eval（mock 可确定性打分）。

**Tech Stack:** Python 3.9 / anthropic SDK 0.105.2（tool-use + prompt caching）/ pytest。本机无 ANTHROPIC_API_KEY、anthropic 未装但 pip 可达。

**对应 spec：** [docs/superpowers/specs/2026-06-03-m2a-llm-highlight-claude-design.md](../specs/2026-06-03-m2a-llm-highlight-claude-design.md)

**前置：** M1 已在 main（HEAD 58ff797）。从 `apps/worker` 跑 pytest。

> 命名说明：评测包用目录 **`evals/`**（spec 写的是 `eval/`），刻意避开 Python 内置函数 `eval` 造成的命名遮蔽。

---

## File Structure

```text
apps/worker/
  agcs_worker/
    config.py                       # 改：+llm_model
    pipeline.py                     # 改：_build_highlight + analyze ctx 增补字幕/元信息
    providers/llm_highlight.py      # 增：ClaudeHighlightProvider（tool-use + 校验 + grounding）
  evals/
    __init__.py                     # 增（空）
    scoring.py                      # 增：iou + top3_hit_rate
    run_eval.py                     # 增：evaluate() + CLI（mock/llm）
    fixtures/example.json           # 增：示例 labeled fixture
  requirements.txt                  # 改：+anthropic==0.105.2
  tests/
    test_config.py                  # 改：+llm_model 默认
    test_eval_scoring.py            # 增
    test_eval_run.py                # 增（mock 确定性）
    test_llm_highlight_provider.py  # 增（fake client）
    test_get_providers.py           # 改：_cfg +llm_model，+highlight 选择测
    test_pipeline.py / test_main.py # 改：_cfg +llm_model
    test_llm_highlight_integration.py  # 增（env-gate 真实 Claude）
.env.example                        # 改：+LLM_MODEL
README.md                           # 改：LLM 高光说明
```

---

## Task 1: Config 增加 llm_model

**Files:** Modify `apps/worker/agcs_worker/config.py`, `.env.example`; Test `apps/worker/tests/test_config.py`

- [ ] **Step 1: 追加失败测试到 `apps/worker/tests/test_config.py`** （文件末尾追加）

```python
def test_load_config_llm_model_default(monkeypatch):
    monkeypatch.delenv("LLM_MODEL", raising=False)
    assert load_config().llm_model == "claude-sonnet-4-6"


def test_load_config_reads_llm_model_env(monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "claude-opus-4-8")
    assert load_config().llm_model == "claude-opus-4-8"
```

- [ ] **Step 2: 运行确认失败**

Run: `cd apps/worker && python3 -m pytest tests/test_config.py -q`
Expected: FAIL（`AttributeError: 'Config' object has no attribute 'llm_model'`）。

- [ ] **Step 3: 改 `config.py`** — 在 `Config` dataclass 的 `whisper_language: str` 之后追加一行 `llm_model: str`，并在 `load_config()` 的 `whisper_language=...` 之后追加：
```python
        llm_model=os.environ.get("LLM_MODEL", "claude-sonnet-4-6"),
```

- [ ] **Step 4: 改 `.env.example`** — 末尾追加：
```bash
LLM_MODEL=claude-sonnet-4-6
```

- [ ] **Step 5: 运行确认通过**

Run: `python3 -m pytest tests/test_config.py -q`
Expected: PASS（4 passed —— 2 个 whisper + 2 个 llm）。

> 注意：其它构造 `Config(...)` 的测试（test_pipeline/test_main/test_get_providers 的 `_cfg`）此刻会 TypeError —— 预期，Task 5 修。本步只跑 test_config.py。

- [ ] **Step 6: Commit**

```bash
cd /Users/jc/codesOther/AIGrowthClipStudio && git add -A && git commit -m "feat(m2a/worker): add llm_model config field + .env.example

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: 评测打分（iou + top3_hit_rate）

**Files:** Create `apps/worker/evals/__init__.py`, `apps/worker/evals/scoring.py`; Test `apps/worker/tests/test_eval_scoring.py`

- [ ] **Step 1: 写失败测试 `apps/worker/tests/test_eval_scoring.py`**

```python
from evals.scoring import iou, top3_hit_rate


def test_iou_full_overlap():
    assert iou(0, 100, 0, 100) == 1.0


def test_iou_no_overlap():
    assert iou(0, 100, 200, 300) == 0.0


def test_iou_partial():
    assert abs(iou(0, 100, 50, 150) - (50 / 150)) < 1e-9


def test_top3_all_hit():
    pred = [(0, 100), (200, 300), (400, 500)]
    gt = [(0, 100), (200, 300)]
    assert top3_hit_rate(pred, gt) == 1.0


def test_top3_no_hit():
    assert top3_hit_rate([(0, 100)], [(500, 600)]) == 0.0


def test_top3_only_first_three_count():
    # 第 4 个才命中 → 不计入
    pred = [(900, 1000), (900, 1000), (900, 1000), (0, 100)]
    assert top3_hit_rate(pred, [(0, 100)]) == 0.0


def test_top3_empty_ground_truth():
    assert top3_hit_rate([(0, 100)], []) == 0.0
```

- [ ] **Step 2: 运行确认失败**

Run: `cd apps/worker && python3 -m pytest tests/test_eval_scoring.py -q`
Expected: FAIL（`No module named 'evals'` 或 `evals.scoring`）。

- [ ] **Step 3: 写 `apps/worker/evals/__init__.py`**（空文件）

```python
```

- [ ] **Step 4: 写 `apps/worker/evals/scoring.py`**

```python
def iou(a_start: int, a_end: int, b_start: int, b_end: int) -> float:
    inter = max(0, min(a_end, b_end) - max(a_start, b_start))
    union = max(a_end, b_end) - min(a_start, b_start)
    return inter / union if union > 0 else 0.0


def top3_hit_rate(predicted, ground_truth, iou_threshold: float = 0.5) -> float:
    """Recall-style: fraction of ground_truth windows hit (IoU>=threshold) by any of the
    first 3 predicted windows. `predicted`/`ground_truth` are lists of (start_ms, end_ms);
    the caller is responsible for ordering `predicted` by score desc. Empty GT -> 0.0."""
    if not ground_truth:
        return 0.0
    top = predicted[:3]
    hits = 0
    for g in ground_truth:
        if any(iou(p[0], p[1], g[0], g[1]) >= iou_threshold for p in top):
            hits += 1
    return hits / len(ground_truth)
```

- [ ] **Step 5: 运行确认通过**

Run: `python3 -m pytest tests/test_eval_scoring.py -q`
Expected: PASS（7 passed）。

- [ ] **Step 6: Commit**

```bash
cd /Users/jc/codesOther/AIGrowthClipStudio && git add -A && git commit -m "feat(m2a/eval): iou + top3_hit_rate scoring

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: 评测 runner + 示例 fixture

**Files:** Create `apps/worker/evals/run_eval.py`, `apps/worker/evals/fixtures/example.json`; Test `apps/worker/tests/test_eval_run.py`

- [ ] **Step 1: 写示例 fixture `apps/worker/evals/fixtures/example.json`**

```json
{
  "name": "example",
  "content": {"title": "她被退婚后身份曝光", "category": "短剧", "tags": ["逆袭", "豪门", "复仇"]},
  "duration_ms": 20000,
  "clip_count": 3,
  "target_scenarios": ["feed"],
  "target_durations": [15],
  "transcript_segments": [
    {"start_ms": 0, "end_ms": 4000, "text": "你不过是个没人要的女人。"},
    {"start_ms": 4000, "end_ms": 8000, "text": "等等，她竟然是董事长的女儿。"},
    {"start_ms": 8000, "end_ms": 12000, "text": "全场瞬间安静了。"},
    {"start_ms": 12000, "end_ms": 16000, "text": "这一次，轮到你后悔了。"},
    {"start_ms": 16000, "end_ms": 20000, "text": "故事才刚刚开始。"}
  ],
  "ground_truth": [
    {"start_ms": 0, "end_ms": 5000},
    {"start_ms": 5000, "end_ms": 10000}
  ]
}
```

> 该 fixture 的 ground_truth 故意与 MockHighlightProvider 的确定性窗口对齐（duration 20000 → 窗口 5000：[0,5000]、[5000,10000]、[10000,15000]），所以 mock 在它上面应得满分 1.0，可作确定性断言。

- [ ] **Step 2: 写失败测试 `apps/worker/tests/test_eval_run.py`**

```python
import os

from agcs_worker.providers.mock import MockHighlightProvider
from evals.run_eval import evaluate, _load_fixtures

FIX_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "evals", "fixtures"
)


def test_evaluate_mock_on_example_is_perfect_and_deterministic():
    fixtures = _load_fixtures(FIX_DIR)
    assert len(fixtures) >= 1
    result = evaluate(MockHighlightProvider(), fixtures)
    assert 0.0 <= result["mean"] <= 1.0
    # mock 窗口与 example ground_truth 对齐 → 满分
    assert result["mean"] == 1.0
    assert result["per_fixture"][0]["score"] == 1.0
```

- [ ] **Step 3: 运行确认失败**

Run: `cd apps/worker && python3 -m pytest tests/test_eval_run.py -q`
Expected: FAIL（`No module named 'evals.run_eval'`）。

- [ ] **Step 4: 写 `apps/worker/evals/run_eval.py`**

```python
import argparse
import json
import os
import sys
from typing import List, Tuple

from .scoring import top3_hit_rate


def _ctx_from_fixture(fx: dict) -> dict:
    return {
        "duration_ms": fx.get("duration_ms", 0),
        "clip_count": fx.get("clip_count", 3),
        "target_scenarios": fx.get("target_scenarios") or ["feed"],
        "target_durations": fx.get("target_durations") or [15],
        "transcript_segments": fx.get("transcript_segments") or [],
        "content": fx.get("content") or {},
    }


def _predicted_windows(segments) -> List[Tuple[int, int]]:
    ordered = sorted(segments, key=lambda s: s.score, reverse=True)
    return [(s.start_ms, s.end_ms) for s in ordered]


def _gt_windows(fx: dict) -> List[Tuple[int, int]]:
    return [(g["start_ms"], g["end_ms"]) for g in fx.get("ground_truth", [])]


def evaluate(provider, fixtures: List[dict], iou_threshold: float = 0.5) -> dict:
    per_fixture = []
    for fx in fixtures:
        segments = provider.analyze(_ctx_from_fixture(fx))
        score = top3_hit_rate(_predicted_windows(segments), _gt_windows(fx), iou_threshold)
        per_fixture.append({"name": fx.get("name", "?"), "score": score})
    mean = sum(p["score"] for p in per_fixture) / len(per_fixture) if per_fixture else 0.0
    return {"per_fixture": per_fixture, "mean": mean}


def _load_fixtures(dir_path: str) -> List[dict]:
    out = []
    for fn in sorted(os.listdir(dir_path)):
        if fn.endswith(".json"):
            with open(os.path.join(dir_path, fn), "r", encoding="utf-8") as f:
                fx = json.load(f)
            fx.setdefault("name", fn)
            out.append(fx)
    return out


def _build_provider(name: str):
    if name in ("llm", "claude"):
        from agcs_worker.config import load_config
        from agcs_worker.providers.llm_highlight import ClaudeHighlightProvider
        return ClaudeHighlightProvider(model=load_config().llm_model)
    from agcs_worker.providers.mock import MockHighlightProvider
    return MockHighlightProvider()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="AGCS highlight eval")
    parser.add_argument("--provider", default="mock")
    parser.add_argument("--fixtures", default=os.path.join(os.path.dirname(__file__), "fixtures"))
    parser.add_argument("--iou", type=float, default=0.5)
    args = parser.parse_args(argv)
    result = evaluate(_build_provider(args.provider), _load_fixtures(args.fixtures), args.iou)
    for p in result["per_fixture"]:
        print(f"{p['name']}: top3_hit_rate={p['score']:.3f}")
    print(f"MEAN top3_hit_rate={result['mean']:.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: 运行确认通过 + 跑一次 CLI（mock）**

Run: `python3 -m pytest tests/test_eval_run.py -q` → PASS（1 passed）。
Run: `python3 -m evals.run_eval --provider mock` → 打印 `example: top3_hit_rate=1.000` 和 `MEAN top3_hit_rate=1.000`。

- [ ] **Step 6: Commit**

```bash
cd /Users/jc/codesOther/AIGrowthClipStudio && git add -A && git commit -m "feat(m2a/eval): run_eval (evaluate + CLI) + example fixture

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: ClaudeHighlightProvider（fake-client 单测）

**Files:** Create `apps/worker/agcs_worker/providers/llm_highlight.py`; Test `apps/worker/tests/test_llm_highlight_provider.py`

- [ ] **Step 1: 写失败测试 `apps/worker/tests/test_llm_highlight_provider.py`**

```python
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
```

- [ ] **Step 2: 运行确认失败**

Run: `cd apps/worker && python3 -m pytest tests/test_llm_highlight_provider.py -q`
Expected: FAIL（`No module named 'agcs_worker.providers.llm_highlight'`）。

- [ ] **Step 3: 写 `apps/worker/agcs_worker/providers/llm_highlight.py`**

```python
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
```

- [ ] **Step 4: 运行确认通过**

Run: `python3 -m pytest tests/test_llm_highlight_provider.py -q`
Expected: PASS（5 passed）—— 全程未 import anthropic（注入 client / 空字幕短路）。

- [ ] **Step 5: Commit**

```bash
cd /Users/jc/codesOther/AIGrowthClipStudio && git add -A && git commit -m "feat(m2a/worker): ClaudeHighlightProvider (tool-use, validation, grounded transcript_text)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: 接线 _build_highlight + pipeline 喂字幕 + 修 _cfg

**Files:** Modify `apps/worker/agcs_worker/pipeline.py`, `tests/test_pipeline.py`, `tests/test_main.py`, `tests/test_get_providers.py`

- [ ] **Step 1: 追加失败测试到 `apps/worker/tests/test_get_providers.py`**（文件末尾）

```python
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
```

- [ ] **Step 2: 更新 `tests/test_get_providers.py` 的 `_cfg`** —— 在 `whisper_language=""` 后追加 `llm_model="claude-sonnet-4-6"`：
```python
def _cfg(asr):
    return Config(db_path="", storage_dir="", poll_interval_ms=1000,
                  asr_provider=asr, highlight_provider="mock", packaging_provider="mock",
                  whisper_model="base", whisper_device="cpu", whisper_compute_type="int8",
                  whisper_language="", llm_model="claude-sonnet-4-6")
```

- [ ] **Step 3: 运行确认失败**

Run: `cd apps/worker && python3 -m pytest tests/test_get_providers.py -q`
Expected: FAIL（`ImportError: cannot import name '_build_highlight'`，或 highlight 默认仍 mock 但 `_build_highlight` 不存在）。

- [ ] **Step 4: 改 `pipeline.py`** —— 把 `get_providers` 改为用 `_build_highlight`，并新增该函数：
```python
def get_providers(config: Config):
    return _build_asr(config), _build_highlight(config), MockPackagingProvider()


def _build_highlight(config: Config):
    if config.highlight_provider in ("llm", "claude"):
        from .providers.llm_highlight import ClaudeHighlightProvider  # lazy: avoid import on mock path
        return ClaudeHighlightProvider(model=config.llm_model)
    if config.highlight_provider != "mock":
        _log.warning("Unknown HIGHLIGHT_PROVIDER %r; falling back to mock", config.highlight_provider)
    return MockHighlightProvider()
```
（`_build_asr` 保持不变。）

- [ ] **Step 5: 改 `pipeline.py` 的 `highlight.analyze(...)` 调用**（当前 line 85-89）—— 增补字幕与元信息：
```python
    highlights = highlight.analyze({
        "duration_ms": duration_ms,
        "clip_count": task.get("clip_count", 3),
        "target_scenarios": target_scenarios,
        "target_durations": target_durations,
        "transcript_segments": [
            {"start_ms": s.start_ms, "end_ms": s.end_ms, "text": s.text}
            for s in transcript.segments
        ],
        "content": {
            "title": task.get("title"),
            "description": task.get("description"),
            "category": task.get("category"),
            "tags": tags,
        },
    })
```

- [ ] **Step 6: 修 `tests/test_pipeline.py` 与 `tests/test_main.py` 的 `_cfg`** —— 各自在 `whisper_language=""` 后追加 `llm_model="claude-sonnet-4-6"`：

test_pipeline.py 的 `_cfg`：
```python
def _cfg(tmp_path):
    return Config(db_path="", storage_dir=str(tmp_path / "storage"),
                  poll_interval_ms=1000, asr_provider="mock",
                  highlight_provider="mock", packaging_provider="mock",
                  whisper_model="base", whisper_device="cpu",
                  whisper_compute_type="int8", whisper_language="",
                  llm_model="claude-sonnet-4-6")
```
test_main.py 的 `_cfg`：同样在末尾参数追加 `llm_model="claude-sonnet-4-6"`。

- [ ] **Step 7: 运行新测试 + 全量回归**

Run: `python3 -m pytest tests/test_get_providers.py -q` → PASS（4 passed：原 4 个里新增 2 个 highlight，加上原 asr 的；以实际为准，应为 6 passed）。
Run: `python3 -m pytest -q` → 全量 PASS（mock 高光路径不变；test_pipeline 真实视频用例仍 3 segments/3 assets/succeeded，因为默认 highlight 仍 mock）。integration 测被 skip。

- [ ] **Step 8: Commit**

```bash
cd /Users/jc/codesOther/AIGrowthClipStudio && git add -A && git commit -m "feat(m2a/worker): wire _build_highlight + feed transcript/content to analyze

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: requirements + README

**Files:** Modify `apps/worker/requirements.txt`, `README.md`

- [ ] **Step 1: 追加到 `apps/worker/requirements.txt`**（保留 faster-whisper 行，新增一行）：
```text
anthropic==0.105.2
```

- [ ] **Step 2: 在 `README.md` 的「真实 ASR（可选，M1）」一节之后追加新小节**（写入时用真正的三反引号 ```bash）：

```markdown
## LLM 高光（可选，M2a）

默认 `HIGHLIGHT_PROVIDER=mock`。启用 Claude 高光识别：

​```bash
cd apps/worker && python3 -m pip install -r requirements.txt   # 装 anthropic
export ANTHROPIC_API_KEY=sk-...                                # 需要 key
HIGHLIGHT_PROVIDER=llm LLM_MODEL=claude-sonnet-4-6 python3 -m agcs_worker.main --once
​```

评测高光质量（对任意 provider 打 Top-3 命中率）：

​```bash
cd apps/worker && python3 -m evals.run_eval --provider mock     # 或 --provider llm（需 key）
​```

`LLM_MODEL` 可配（默认 `claude-sonnet-4-6`，要更强换 `claude-opus-4-8`）。真实标注评测集为后续工作，当前仅含 1 个示例 fixture。
```

IMPORTANT：上面把围栏写成 `​```` 仅为转义，实际 README.md 用正常三反引号；写完后确认 README ``` 数量为偶数、未破坏其它小节。

- [ ] **Step 3: Commit**

```bash
cd /Users/jc/codesOther/AIGrowthClipStudio && git add -A && git commit -m "docs(m2a): anthropic requirement + LLM-highlight & eval run docs

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: env-gate 集成测 + 安装 + 真实验证（best-effort）

**Files:** Create `apps/worker/tests/test_llm_highlight_integration.py`

### Phase A（必做 + commit；零网络）

- [ ] **Step 1: 写 `apps/worker/tests/test_llm_highlight_integration.py`**

```python
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
```

- [ ] **Step 2: 确认默认 skip + 全量套件仍快**

Run: `cd apps/worker && python3 -m pytest -q`
Expected: 之前用例全 PASS，`test_llm_highlight_integration` 显示 skipped（无 RUN_LLM_TESTS / 无 key）。

- [ ] **Step 3: commit（Phase A）**

```bash
cd /Users/jc/codesOther/AIGrowthClipStudio && git add -A && git commit -m "test(m2a/worker): env-gated real Claude highlight integration test

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

### Phase B（best-effort；需网络/ key）

- [ ] **Step 4: 安装 anthropic**

Run: `cd /Users/jc/codesOther/AIGrowthClipStudio/apps/worker && python3 -m pip install -r requirements.txt`
Expected: 成功安装 anthropic 0.105.2。若失败（网络/代理），STOP Phase B 并报告真实错误；Phase A 已提交。

- [ ] **Step 5: 真实跑通集成测（需 ANTHROPIC_API_KEY 且 api.anthropic.com 可达）**

Run: `cd /Users/jc/codesOther/AIGrowthClipStudio/apps/worker && RUN_LLM_TESTS=1 python3 -m pytest tests/test_llm_highlight_integration.py -q -rs`
Expected：有 key 且可达 → 1 passed；无 key → 仍 skipped（`_HAS_KEY` False）；有 key 但代理挡 → 报告真实错误。如实报告属于哪种。

- [ ] **Step 6: eval CLI（mock）端到端确认**

Run: `cd /Users/jc/codesOther/AIGrowthClipStudio/apps/worker && python3 -m evals.run_eval --provider mock`
Expected: `MEAN top3_hit_rate=1.000`。

> Phase B 不需要额外 commit（无源码改动，只装依赖 + 运行）。

---

## Self-Review（计划自检结论）

- **Spec coverage：** 成功标准 1（契约一致+校验）→ Task 4；2（fake-client 单测零依赖）→ Task 4；3（iou/top3 单测 + mock 确定性 run）→ Task 2/3；4（env-gate 真实）→ Task 7；5（mock 路径不受影响、未装不 import）→ Task 5 Step7 回归 + 懒导入（Task 4/5）。§2.2 喂字幕 → Task 5；§4 评测 harness → Task 2/3；§5 配置/依赖 → Task 1/6；§7 降级（空字幕→[]、未知 provider 告警回退、tool 缺失→[]、丢非法片段）→ Task 4（校验/短路）+ Task 5（告警）；§8 验证 → Task 3/7。无缺口。
- **Placeholder scan：** 无 TBD/“稍后”。每个代码步骤含完整代码 + 确切命令/期望。README 围栏转义已注明。
- **Type consistency：** `ClaudeHighlightProvider(client, model, max_tokens)`、`analyze(ctx)->List[HighlightSegment]`、`_build_highlight(config)`、`_extract_tool_input`/`_grounded_text`/`_to_segments`、`iou(...)`/`top3_hit_rate(pred, gt, iou_threshold)`/`evaluate(provider, fixtures, iou_threshold)->{"per_fixture","mean"}`/`_load_fixtures(dir)`—— 在各 Task 间签名一致；`HighlightSegment` 字段（start_ms/end_ms/highlight_type/score/reason/summary/transcript_text/risk_level/recommended_scenario/risk_reason）与 base.py 一致；`Config` 新增 `llm_model` 的所有构造点（test_get_providers/test_pipeline/test_main 的 `_cfg`）在 Task 5 同步补齐。fixture 的 ground_truth 与 mock 窗口对齐保证 Task 3 断言 1.0 成立。

---

## Execution Handoff

计划已保存。两种执行方式：

1. **Subagent-Driven（推荐）** — 每个 Task 派全新 subagent，任务间两阶段审查。
2. **Inline Execution** — 当前会话用 executing-plans 批量执行。

> Task 7 Phase B 含 `pip install` + 真实 Claude 调用（需 key+网络）；环境受限时如实报告，Phase A（默认 skip 的集成测）是durable 交付。
