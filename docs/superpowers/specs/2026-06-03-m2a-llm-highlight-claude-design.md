# M2a — LLM 高光 Provider（Claude）+ 评测 harness 设计 Spec

- 日期：2026-06-03
- 范围：M2 的第一个增量（M2a）。用 Claude 替换 mock 高光识别（基于字幕+元信息），并提供一个能对 labeled fixture 打 Top-3 命中率的评测 harness。多信号候选窗（音频/场景）= M2b，真实标注评测集 = M2c，均不在本期。
- 依赖前置：M1 已合并到 main（HEAD 58ff797）。provider 适配器接缝（`HighlightProvider`）已就绪。
- 状态：已与用户对齐，待写实现计划。

## 1. 目标

新增真实 LLM 高光 provider，并通过 env 切换启用；同时提供可对任意 provider 打分的评测 harness：

- `HIGHLIGHT_PROVIDER=mock`（默认）→ 现有 `MockHighlightProvider`，零外部依赖。
- `HIGHLIGHT_PROVIDER=llm`（或 `claude`）→ 新增 `ClaudeHighlightProvider`，用 Claude tool-use 产出结构化高光。

成功标准（M2a 验收）：

1. `ClaudeHighlightProvider.analyze(ctx)` 返回与 `HighlightProvider` 契约一致的 `List[HighlightSegment]`，字段经反幻觉校验。
2. 映射/校验逻辑有**不依赖 anthropic SDK、零网络**的单测（注入 fake client）。
3. 评测 harness：`iou` + `top3_hit_rate` 有单测；`run_eval` 能用 **mock provider** 在示例 fixture 上确定性打分（可断言、零网络）。
4. env-gate 集成测在 `RUN_LLM_TESTS=1` + anthropic 已装 + `ANTHROPIC_API_KEY` 时，对一小段字幕真实调用 Claude 并断言返回 ≥1 个结构合法高光；默认 skip。
5. mock 路径与现有全部测试不受影响（anthropic 未装时不触发 import）。
6. 本会话内 eval harness + mock 链路 + fake-client 单测全绿；真实 Claude 调用若因无 key/代理不可达则集成测 skip（验证留后）。

## 2. 关键架构决策

### 2.1 复用 provider 接缝，pipeline 结构基本不变（镜像 M1）

- 契约不动：`HighlightProvider.analyze(self, ctx: dict) -> List[HighlightSegment]`（[providers/base.py](../../../apps/worker/agcs_worker/providers/base.py)）。
- `get_providers(config)` 增加 `_build_highlight(config)`，按 `config.highlight_provider` 选择，**懒导入** Claude provider（mock 路径与现有测试无需安装 anthropic）。两级懒加载：构造 provider 便宜；`anthropic` 仅在首次 `analyze` 的 `_ensure_client` 内导入。

### 2.2 pipeline 必须把字幕+元信息喂给 highlight

现状 `highlight.analyze(ctx)` 只传 `duration_ms`/`clip_count`/`target_scenarios`（[pipeline.py:85-89]）。M2a 给 ctx 增补：

- `transcript_segments`：`[{start_ms, end_ms, text}, ...]`（来自 transcript.segments）
- `content`：`{title, description, category, tags}`（来自 task）
- `target_durations`

mock provider 只读旧 key，新增 key 向后兼容、行为不变。

### 2.3 结构化输出用 Claude tool-use

- 定义工具 `report_highlights`，`input_schema` 描述 `segments[]`，`tool_choice` 强制调用，模型返回符合 schema 的 JSON（比"prompt 要 JSON + 宽松解析"更稳）。
- 静态系统提示加 **prompt caching**（`cache_control: ephemeral`），跨多次调用降本（claude-api 最佳实践）。

### 2.4 反幻觉校验 + grounded transcript_text

- LLM 输出经校验：起止裁剪到 `[0, duration_ms]`；`end>start` 否则丢弃；score 夹到 [0,1]；`highlight_type` 不在允许集合则记为校验失败丢弃；`recommended_scenario` 不在 `target_scenarios` 则取第一个；缺失字段给默认（risk_level→"low"）。
- 校验后按 score 降序取前 `clip_count` 个。
- `transcript_text` **由代码用窗口内字幕回填**（拼接与 [start,end] 重叠的 transcript 段文本），不让 LLM 编造。

## 3. ClaudeHighlightProvider 行为

```python
# providers/llm_highlight.py（示意，非最终代码）
ALLOWED_TYPES = {"conflict","reversal","emotion","funny","suspense","membership_conversion","ad_hook"}

HIGHLIGHT_TOOL = {
    "name": "report_highlights",
    "description": "Report selected highlight segments grounded ONLY in the provided transcript.",
    "input_schema": {
        "type": "object",
        "properties": {
            "segments": {"type": "array", "items": {"type": "object", "properties": {
                "startMs": {"type": "integer"}, "endMs": {"type": "integer"},
                "highlightType": {"type": "string", "enum": [...ALLOWED_TYPES...]},
                "score": {"type": "number"}, "reason": {"type": "string"}, "summary": {"type": "string"},
                "recommendedScenario": {"type": "string"},
                "riskLevel": {"type": "string", "enum": ["low","medium","high"]},
                "riskReason": {"type": "string"},
            }, "required": ["startMs","endMs","highlightType","score","reason","summary","recommendedScenario","riskLevel"]}},
        },
        "required": ["segments"],
    },
}

class ClaudeHighlightProvider:
    needs_audio_file = False

    def __init__(self, client=None, model="claude-sonnet-4-6", max_tokens=2048):
        self._client = client; self._model = model; self._max_tokens = max_tokens

    def _ensure_client(self):
        if self._client is None:
            import anthropic  # 懒导入
            self._client = anthropic.Anthropic()  # 从 env 读 ANTHROPIC_API_KEY
        return self._client

    def analyze(self, ctx: dict):
        transcript = ctx.get("transcript_segments") or []
        if not transcript:
            return []
        duration_ms = ctx.get("duration_ms") or 0
        clip_count = ctx.get("clip_count", 3)
        scenarios = ctx.get("target_scenarios") or ["feed"]
        content = ctx.get("content") or {}
        client = self._ensure_client()
        resp = client.messages.create(
            model=self._model, max_tokens=self._max_tokens,
            system=[{"type":"text","text": SYSTEM_PROMPT, "cache_control":{"type":"ephemeral"}}],
            tools=[HIGHLIGHT_TOOL], tool_choice={"type":"tool","name":"report_highlights"},
            messages=[{"role":"user","content": _build_user(content, transcript, scenarios, clip_count, duration_ms)}],
        )
        raw = _extract_tool_input(resp)              # 找 tool_use(report_highlights).input，无则 {}
        return _to_segments(raw.get("segments", []), transcript, duration_ms, scenarios, clip_count)
```

- `_extract_tool_input(resp)`：遍历 `resp.content`，找 `block.type=="tool_use" and block.name=="report_highlights"` → 返回 `block.input`；找不到返回 `{}`（→ 空高光，pipeline 仍继续）。
- `_to_segments(...)`：按 §2.4 校验 + grounded 回填 + 排序裁剪，产出 `HighlightSegment` 列表。
- 空字幕 → 返回 `[]`（不调用 LLM，pipeline 继续，scenes 空、assets 仍由 render 步骤照常）。

## 4. 评测 harness（对任意 provider 可打分）

目录 `apps/worker/eval/`：

- `scoring.py`（纯函数，只吃 `(start_ms, end_ms)` 元组，与 provider/dataclass 解耦）：
  - `iou(a_start, a_end, b_start, b_end) -> float`：交并比。
  - `top3_hit_rate(predicted, ground_truth, iou_threshold=0.5) -> float`：**召回式**。`predicted`、`ground_truth` 均为 `list[(start_ms, end_ms)]`。**不在内部排序** —— 只取 `predicted[:3]`（前 3 个，调用方负责按分数排好序）；返回 `ground_truth` 中被这前 3 个以 IoU≥阈值命中的比例 `hits / len(ground_truth)`（GT 为空返回 0.0）。
- `run_eval.py`：CLI + 可编程入口 `evaluate(provider, fixtures) -> {"per_fixture": [...], "mean": float}`。载入 fixture（JSON），用 fixture 的 content/transcript 构造 ctx，调 `provider.analyze(ctx)`，**把返回的 HighlightSegment 按 `score` 降序排**、转成 `(start_ms, end_ms)` 列表，并把 fixture 的 `ground_truth`（`[{start_ms,end_ms}, ...]`）转成 `(start_ms, end_ms)` 列表，调 `top3_hit_rate`，聚合 mean。CLI：`--provider mock|llm --fixtures <dir> --iou 0.5`。
- `fixtures/example.json`：1 个示例 fixture（content + duration_ms + clip_count + target_scenarios + transcript_segments + ground_truth 窗口）。
- harness 对任意 `HighlightProvider` 可跑 → 用 **mock provider** 在 example fixture 上得确定性分数（可测）。

## 5. 配置 / 依赖

- Config 加 `llm_model`（`LLM_MODEL`，默认 `claude-sonnet-4-6`）。`.env.example` 同步加 `HIGHLIGHT_PROVIDER=mock` 与 `LLM_MODEL=claude-sonnet-4-6`。
- `ANTHROPIC_API_KEY` 由 anthropic SDK 从 env 读；缺失时 `_ensure_client` / 首次调用清晰失败（由 pipeline 外层 `process_once` 捕获 → mark_failed）。
- `apps/worker/requirements.txt` 追加 `anthropic==0.105.2`（与 faster-whisper 并列，均为可选真实 provider 依赖）。README 补 LLM 高光启用说明。
- 默认模型 `claude-sonnet-4-6`（高光抽取量大，性价比优）；要更高质量可 `LLM_MODEL=claude-opus-4-8`。

## 6. 测试策略（镜像 M1 fake + env-gate）

- **fake-client 单测** `tests/test_llm_highlight_provider.py`：注入假 client（`messages.create` 返回带 `tool_use` block 的假响应）→ 断言映射成 HighlightSegment、校验（越界裁剪、score 夹紧、scenario 兜底、丢弃非法 type/零长片段）、`transcript_text` 为 grounded 回填、空字幕短路不建 client。零依赖零网络。
- **eval 打分单测** `tests/test_eval_scoring.py`：`iou`（完全重叠=1、不相交=0、部分）、`top3_hit_rate`（全命中=1、零命中=0、只看前 3、GT 空=0）。
- **eval run 单测** `tests/test_eval_run.py`：`evaluate(MockHighlightProvider(), [example fixture])` → 返回 mean 在 [0,1]，且确定（mock 由 duration 决定窗口）。
- **env-gate 集成测** `tests/test_llm_highlight_integration.py`：`skipif(not (RUN_LLM_TESTS==1 and anthropic importable and ANTHROPIC_API_KEY set))`；小字幕真实调用 Claude，断言 ≥1 个 HighlightSegment 且字段合法、时间在范围内。默认 skip。
- **回归**：运行既有 worker 全量测试，确认 mock 路径不受影响（anthropic 未装时不被 import）。

## 7. 错误处理与降级

- 空 `transcript_segments` → 返回 `[]`，不调用 LLM，pipeline 继续（与现有空字幕语义一致）。
- anthropic 未装但 `HIGHLIGHT_PROVIDER=llm` → 懒导入抛 `ImportError`；`ANTHROPIC_API_KEY` 缺失 → SDK 抛错——均由 `process_once` 捕获 → `mark_failed`，错误信息提示。
- tool_use 缺失 / 解析空 → `[]`（不崩）。
- 校验丢弃非法片段；全被丢弃则该任务高光为空（pipeline 仍 succeeded，M2a 不校验高光质量，质量由 eval harness 单独衡量）。
- 未知 `HIGHLIGHT_PROVIDER` 值 → 告警并回退 mock（与 M1 `_build_asr` 一致）。

## 8. 本会话内验证（实现后执行）

1. `pip install -r apps/worker/requirements.txt`（装 anthropic）。
2. eval harness + mock 链路：`run_eval --provider mock --fixtures eval/fixtures` 打印确定性 Top-3 分数；fake-client 单测全绿。
3. 真实 Claude：若 `ANTHROPIC_API_KEY` 可用且 api.anthropic.com 可达，`RUN_LLM_TESTS=1 pytest tests/test_llm_highlight_integration.py` 真实跑通；否则如实报告 skip（无 key / 代理不可达），验证留后。
4. 用 `HIGHLIGHT_PROVIDER=llm` 跑 smoke（需 key）——可选；无 key 时跳过。

## 9. 不做（M2a 范围外）

- M2b：多信号候选窗（音频能量/场景密度→candidateWindows）。
- M2c：真实人工标注评测集（本期只放 1 个示例 fixture）。
- generate_packaging 接 LLM（= M3）；ai_prompt_runs 成本表；prompt 迭代调优；signalEvidence 字段（依赖多信号，留 M2b）。

## 10. 受影响文件

- 改：`apps/worker/agcs_worker/config.py`（+llm_model）、`apps/worker/agcs_worker/pipeline.py`（_build_highlight + analyze ctx 增补）、`apps/worker/requirements.txt`、`.env.example`、`README.md`。
- 增：`apps/worker/agcs_worker/providers/llm_highlight.py`、`apps/worker/eval/__init__.py`、`apps/worker/eval/scoring.py`、`apps/worker/eval/run_eval.py`、`apps/worker/eval/fixtures/example.json`、`tests/test_llm_highlight_provider.py`、`tests/test_eval_scoring.py`、`tests/test_eval_run.py`、`tests/test_llm_highlight_integration.py`。
- 测试 `_cfg` helper（test_pipeline.py / test_main.py / test_get_providers.py）随 `llm_model` 字段同步补齐。
