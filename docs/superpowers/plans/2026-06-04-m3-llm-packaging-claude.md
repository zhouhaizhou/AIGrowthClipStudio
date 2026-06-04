# M3 — LLM 文案（Claude packaging）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`).

**Goal:** 用 Claude（tool-use）替换 mock 运营包装，为每个高光片段生成标题/封面文案/推荐语/标签；`PACKAGING_PROVIDER=llm` 启用，默认 mock。

**Architecture:** 新增 `ClaudePackagingProvider`（injectable client、懒导入 anthropic、tool-use 强制 JSON、校验=封面截断12字/标题兜底/tags去重截断）。`get_providers` 加 `_build_packaging`；pipeline 把片段上下文喂进 `packaging.generate(ctx)`。mock 忽略新键，向后兼容。复用 `llm_model`，无新依赖（anthropic 已在 M2a 加）、无新 config 字段。

**对应 spec：** [docs/superpowers/specs/2026-06-04-m3-llm-packaging-claude-design.md](../specs/2026-06-04-m3-llm-packaging-claude-design.md)

**前置：** M2a 在 main；M2b 待合并（不冲突）。从 `apps/worker` 跑 pytest。

---

## Task 1: ClaudePackagingProvider（fake-client 单测）

**Files:** Create `apps/worker/agcs_worker/providers/llm_packaging.py`; Test `apps/worker/tests/test_llm_packaging_provider.py`

- [ ] **Step 1: 写失败测试 `tests/test_llm_packaging_provider.py`**

```python
from agcs_worker.providers.llm_packaging import ClaudePackagingProvider


class _FakeBlock:
    def __init__(self, payload):
        self.type = "tool_use"
        self.name = "report_packaging"
        self.input = payload


class _FakeResp:
    def __init__(self, payload):
        self.content = [_FakeBlock(payload)]


class _FakeMessages:
    def __init__(self, payload):
        self._payload = payload
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return _FakeResp(self._payload)


class _FakeClient:
    def __init__(self, payload):
        self.messages = _FakeMessages(payload)


def _ctx():
    return {"summary": "女主身份曝光", "transcript_text": "她竟是董事长的女儿。",
            "highlight_type": "reversal", "scenario": "feed", "duration_ms": 15000,
            "tags": ["逆袭"], "content": {"title": "退婚", "category": "短剧"}}


def test_maps_packaging():
    payload = {"title": "退婚当天身份曝光", "coverText": "全场后悔",
               "recommendationText": "强反转开局。", "tags": ["逆袭", "反转"]}
    p = ClaudePackagingProvider(client=_FakeClient(payload)).generate(_ctx())
    assert p.title == "退婚当天身份曝光"
    assert p.cover_text == "全场后悔"
    assert p.recommendation_text == "强反转开局。"
    assert p.tags == ["逆袭", "反转"]


def test_cover_text_truncated_to_12():
    payload = {"title": "t", "coverText": "这是一个非常非常非常长的封面文案超过十二个字",
               "recommendationText": "r", "tags": []}
    p = ClaudePackagingProvider(client=_FakeClient(payload)).generate(_ctx())
    assert len(p.cover_text) == 12


def test_empty_title_and_bad_tags_fall_back():
    payload = {"title": "  ", "coverText": "", "recommendationText": "", "tags": "notalist"}
    p = ClaudePackagingProvider(client=_FakeClient(payload)).generate(_ctx())
    assert p.title == "精彩片段"
    assert p.cover_text == "精彩片段"        # empty cover -> title (<=12)
    assert p.recommendation_text            # non-empty fallback
    assert p.tags == ["逆袭"]                # non-list tags -> ctx fallback


def test_tags_dedup_strip_and_cap():
    payload = {"title": "t", "coverText": "c", "recommendationText": "r",
               "tags": ["a", "a", " b ", "", "c", "d", "e", "f", "g"]}
    p = ClaudePackagingProvider(client=_FakeClient(payload)).generate(_ctx())
    assert p.tags == ["a", "b", "c", "d", "e", "f"]


def test_missing_tool_block_falls_back():
    class _Empty:
        content = []

    class _C:
        class messages:
            @staticmethod
            def create(**k):
                return _Empty()

    p = ClaudePackagingProvider(client=_C()).generate(_ctx())
    assert p.title == "精彩片段"
```

- [ ] **Step 2: 运行确认失败**

Run: `cd apps/worker && python3 -m pytest tests/test_llm_packaging_provider.py -q` → FAIL (No module named 'agcs_worker.providers.llm_packaging').

- [ ] **Step 3: 写 `apps/worker/agcs_worker/providers/llm_packaging.py`**

```python
import json as _json
from typing import List

from .base import Packaging

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
    if not isinstance(raw_tags, list):
        return list(fallback)
    out: List[str] = []
    for t in raw_tags:
        if isinstance(t, str):
            s = t.strip()
            if s and s not in out:
                out.append(s)
    return out[:6] if out else list(fallback)


def _to_packaging(raw: dict, ctx: dict, cover_max: int) -> Packaging:
    title = str(raw.get("title", "")).strip() or "精彩片段"
    cover = str(raw.get("coverText", "")).strip() or title
    cover = cover[:cover_max]
    rec = str(raw.get("recommendationText", "")).strip() or "高能片段，适合推荐流测试。"
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
        return _to_packaging(raw, ctx, self._cover_max)
```

- [ ] **Step 4: 运行确认通过**

Run: `python3 -m pytest tests/test_llm_packaging_provider.py -q` → 5 passed（全程未 import anthropic）。

- [ ] **Step 5: Commit**

```bash
cd /Users/jc/codesOther/AIGrowthClipStudio && git add -A && git commit -m "feat(m3/worker): ClaudePackagingProvider (tool-use, validation, fallbacks)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: 接线 _build_packaging + pipeline ctx 扩展

**Files:** Modify `apps/worker/agcs_worker/pipeline.py`; Test `apps/worker/tests/test_get_providers.py`

- [ ] **Step 1: APPEND failing tests to `tests/test_get_providers.py`**

```python
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
```

- [ ] **Step 2: 运行确认失败**

Run: `cd apps/worker && python3 -m pytest tests/test_get_providers.py -q` → FAIL (cannot import name '_build_packaging').

- [ ] **Step 3: 改 `pipeline.py` get_providers + 新增 _build_packaging**

把 `get_providers` 改为：
```python
def get_providers(config: Config):
    return _build_asr(config), _build_highlight(config), _build_packaging(config)
```
并新增（放在 `_build_highlight` 附近）：
```python
def _build_packaging(config: Config):
    if config.packaging_provider in ("llm", "claude"):
        from .providers.llm_packaging import ClaudePackagingProvider  # lazy: avoid import on mock path
        return ClaudePackagingProvider(model=config.llm_model)
    if config.packaging_provider != "mock":
        _log.warning("Unknown PACKAGING_PROVIDER %r; falling back to mock", config.packaging_provider)
    return MockPackagingProvider()
```

- [ ] **Step 4: 改 `pipeline.py` 渲染循环的 `packaging.generate(...)` 调用** —— 当前 `pack = packaging.generate({"index": idx, "tags": tags})`，改为传片段上下文：
```python
        pack = packaging.generate({
            "index": idx, "tags": tags,
            "summary": seg.summary, "transcript_text": seg.transcript_text,
            "highlight_type": seg.highlight_type, "scenario": seg.recommended_scenario,
            "duration_ms": seg.end_ms - seg.start_ms,
            "content": {"title": task.get("title"), "category": task.get("category")},
        })
```
（mock 只读 index/tags，新键忽略，行为不变。）

- [ ] **Step 5: 运行新测试 + 全量回归**

Run: `python3 -m pytest tests/test_get_providers.py -q` → PASS（新增 3 个 packaging 测试通过）。
Run: `python3 -m pytest -q` → 全量绿（mock packaging 路径不变；真实视频用例仍 3 segments/6 assets/succeeded；integration skipped）。

- [ ] **Step 6: Commit**

```bash
cd /Users/jc/codesOther/AIGrowthClipStudio && git add -A && git commit -m "feat(m3/worker): wire _build_packaging + feed clip context to packaging.generate

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: env-gate 集成测（真实 Claude 文案）

**Files:** Create `apps/worker/tests/test_llm_packaging_integration.py`

- [ ] **Step 1: 写 `tests/test_llm_packaging_integration.py`**

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
```

- [ ] **Step 2: 确认默认 skip + 全量套件**

Run: `cd apps/worker && python3 -m pytest -q`
Expected: 之前用例全 PASS，`test_llm_packaging_integration` skipped（无 key）。

- [ ] **Step 3: commit**

```bash
cd /Users/jc/codesOther/AIGrowthClipStudio && git add -A && git commit -m "test(m3/worker): env-gated real Claude packaging integration test

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 4（best-effort，需 key）：真实跑通**

Run: `cd apps/worker && RUN_LLM_TESTS=1 python3 -m pytest tests/test_llm_packaging_integration.py -q -rs`
Expected：有 key+可达 → 1 passed；无 key → skipped；如实报告。

---

## Task 4: README（LLM 文案说明）

**Files:** Modify `README.md`

- [ ] **Step 1: 在 README「多信号候选窗（M2b）」一节之后追加（用真正三反引号）**

```markdown
## LLM 文案（M3）

`PACKAGING_PROVIDER=llm` 时用 Claude 为每个高光片段生成标题/封面文案（≤12字）/推荐语/标签（默认 mock）。复用 `LLM_MODEL` 与 `ANTHROPIC_API_KEY`：

​```bash
cd apps/worker && python3 -m pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-...
HIGHLIGHT_PROVIDER=llm PACKAGING_PROVIDER=llm python3 -m agcs_worker.main --once
​```
```

（写 README 时用正常三反引号；写完确认 ``` 数为偶数、未破坏其它小节、放在 M2b 与「测试」之间。）

- [ ] **Step 2: Commit**

```bash
cd /Users/jc/codesOther/AIGrowthClipStudio && git add -A && git commit -m "docs(m3): LLM packaging run docs

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

- **Spec coverage：** 成功标准 1（契约+校验）→ Task 1（_to_packaging）；2（fake-client 单测）→ Task 1；3（pipeline ctx + mock 兼容 + 回归）→ Task 2；4（env-gate 真实）→ Task 3；5（mock 路径不受影响、未装不 import）→ Task 2 回归 + 懒导入。§2.2 校验（封面截断/标题兜底/tags）→ Task 1。无缺口。
- **Placeholder scan：** 无 TBD；每步含完整代码+命令+期望；README 围栏注明。
- **Type consistency：** `ClaudePackagingProvider(client, model, max_tokens, cover_max)`、`generate(ctx)->Packaging`、`_build_packaging(config)`、`_to_packaging(raw, ctx, cover_max)`、`_clean_tags(raw, fallback)`、`_extract_tool_input`、`Packaging(title,cover_text,recommendation_text,tags)`（与 base.py 一致）—— 各 Task 间一致。无新 Config 字段（复用 llm_model），故 test 的 `_cfg` 无需改（与 M2a/M2b 不同，更简单）。

---

## Execution: subagent-driven，每 Task 实现→规格评审→质量评审→修复；完成后合并 main + 推送 + 通知。
> 注：合并前需先把已完成的 M2b 分支合并到 main（被分类器故障挡过，恢复后先收尾 M2b 再做 M3）。
