# M3 — LLM 文案（Claude packaging）设计 Spec

- 日期：2026-06-04
- 范围：用 Claude 替换 mock 运营包装，为每个高光片段生成标题/封面文案/推荐语/标签。`PACKAGING_PROVIDER=llm` 时启用，默认仍 mock。完成 ASR→高光→文案 的"真实 AI 生成"三件套。
- 依赖前置：M2a 已合并到 main；M2b 待合并（不影响 M3，二者文件不冲突）。`PackagingProvider` 接缝、`Packaging` dataclass、anthropic 依赖（M2a 已加）均就绪。
- 自主执行：我自行定稿设计/spec/plan（无人工审批门），subagent-driven + 两阶段评审，完成后合并并通知。

## 1. 目标

新增真实 LLM 文案 provider，env 切换启用；镜像 M2a 的 ClaudeHighlightProvider 模式：

- `PACKAGING_PROVIDER=mock`（默认）→ 现有 `MockPackagingProvider`，零外部依赖。
- `PACKAGING_PROVIDER=llm`（或 `claude`）→ 新增 `ClaudePackagingProvider`，用 Claude tool-use 产出结构化文案。

成功标准（M3 验收）：

1. `ClaudePackagingProvider.generate(ctx)` 返回与 `PackagingProvider` 契约一致的 `Packaging`，字段经校验（封面文案截断、标题非空兜底、tags 为 list）。
2. 映射/校验逻辑有**不依赖 anthropic、零网络**的 fake-client 单测。
3. pipeline 把片段上下文（summary/transcript_text/highlight_type/scenario + content 元信息）传给 `packaging.generate(ctx)`；mock 忽略新键，向后兼容；现有全部测试仍绿。
4. env-gate 集成测在 `RUN_LLM_TESTS=1` + anthropic + `ANTHROPIC_API_KEY` 时真实调用 Claude 并断言结构合法；默认 skip。
5. mock 路径与现有测试不受影响（anthropic 未装时不被 import）。

## 2. 关键架构决策（镜像 M2a）

### 2.1 复用 PackagingProvider 接缝
- 契约不动：`PackagingProvider.generate(self, ctx: dict) -> Packaging`。
- `get_providers` 增加 `_build_packaging(config)`，按 `config.packaging_provider` 选择，懒导入 Claude provider；未知值告警回退 mock（与 `_build_asr`/`_build_highlight` 一致）。

### 2.2 tool-use 结构化输出 + 校验
- 工具 `report_packaging`，input_schema：`{title, coverText, recommendationText, tags[]}`，`tool_choice` 强制。
- 静态系统提示 + prompt caching（cache_control ephemeral）。
- 校验（`_to_packaging`）：`title` 去空白、空则兜底 `"精彩片段"`；`cover_text` 去空白后**截断到 12 个字符**（设计要求封面文案短）、空则用 title 前 12 字；`recommendation_text` 去空白、空则兜底一句；`tags` 取字符串列表、非 list 则 `[]`、去重去空、截断到前 6 个。
- 不编造：prompt 要求只基于片段 summary/字幕/元信息，不夸大到与剧情不符。

### 2.3 模型复用
- 复用 `config.llm_model`（默认 `claude-sonnet-4-6`）；无需新增 config 字段。`ANTHROPIC_API_KEY` 由 SDK 读，缺失清晰失败 → `process_once` 捕获 mark_failed。

## 3. ClaudePackagingProvider 行为

```python
# providers/llm_packaging.py（示意）
PACKAGING_TOOL = {
  "name": "report_packaging",
  "input_schema": {"type":"object","properties":{
     "title":{"type":"string"}, "coverText":{"type":"string"},
     "recommendationText":{"type":"string"}, "tags":{"type":"array","items":{"type":"string"}}},
     "required":["title","coverText","recommendationText","tags"]}}

class ClaudePackagingProvider:
    def __init__(self, client=None, model="claude-sonnet-4-6", max_tokens=1024, cover_max=12): ...
    def _ensure_client(self): # 懒 import anthropic
    def generate(self, ctx: dict) -> Packaging:
        client=self._ensure_client()
        resp=client.messages.create(model, max_tokens, system=[{...cache_control}],
              tools=[PACKAGING_TOOL], tool_choice={"type":"tool","name":"report_packaging"},
              messages=[{"role":"user","content": _build_user(ctx)}])
        raw=_extract_tool_input(resp)         # 复用 tool_use 提取逻辑
        return _to_packaging(raw, ctx, self._cover_max)
```

- `_build_user(ctx)`：拼接 content 元信息、片段 summary、transcript_text、highlight_type、scenario、duration，要求按场景写抓人但不夸大的文案。
- `_extract_tool_input`/tool-use 提取与 M2a 同构（可各自实现，避免跨模块耦合）。
- 空/缺失 tool 输出 → 用 `_to_packaging({}, ctx, ...)` 走兜底（不崩、返回合法 Packaging）。

## 4. pipeline 接入

- `get_providers` → `_build_asr(config), _build_highlight(config), _build_packaging(config)`。
- 渲染循环里把 `packaging.generate({...})` 的 ctx 扩为：
```python
        pack = packaging.generate({
            "index": idx, "tags": tags,
            "summary": seg.summary, "transcript_text": seg.transcript_text,
            "highlight_type": seg.highlight_type, "scenario": seg.recommended_scenario,
            "duration_ms": seg.end_ms - seg.start_ms,
            "content": {"title": task.get("title"), "category": task.get("category")},
        })
```
- mock 只读 `index`/`tags`，新键忽略，行为不变。
- **性能注意**：LLM packaging 每个高光一次调用（N 次/任务）。M3 不做批量/缓存（留后）；comment 注明成本。

## 5. 测试策略（镜像 M2a/M2b）

- `tests/test_llm_packaging_provider.py`（fake client）：tool_use 响应 → Packaging 映射；cover_text 超 12 字被截断；title 空 → 兜底；tags 非 list → []、去重截断；tool 缺失 → 合法兜底 Packaging。零依赖零网络。
- `tests/test_get_providers.py`（追加）：默认 mock packaging；`packaging_provider="llm"` 经 `_build_packaging` → ClaudePackagingProvider（不建 client）；未知值回退 mock。
- pipeline 回归：mock packaging 路径不变（真实视频仍 3 segments/6 assets/succeeded）。
- env-gate 集成测 `tests/test_llm_packaging_integration.py`：真实 Claude 生成一条文案，断言 title/cover_text/recommendation_text 非空、cover_text ≤12、tags 为 list。默认 skip。

## 6. 错误处理与降级
- anthropic 未装但 `PACKAGING_PROVIDER=llm` → 懒导入 ImportError；key 缺失 → SDK 报错 → process_once mark_failed。
- tool 缺失/解析空 → 兜底 Packaging（不崩）。
- 校验保证写库字段始终合法（title/cover_text/recommendation_text 非空、cover_text 截断、tags list）。
- 未知 `PACKAGING_PROVIDER` → 告警回退 mock。

## 7. 本会话验证
- fake-client 单测 + get_providers + pipeline 回归本会话全绿（无需 key）。
- 真实 Claude 调用需 key+联网；无 key/被代理挡则集成测 skip（同 M1/M2a）。

## 8. 不做（M3 范围外）
- 多语言文案/封面（M1 多语言预留之外）；批量/缓存多片段一次调用；A/B 多版本标题落库（packaging_draft 已存单版本）；成本表 ai_prompt_runs；signalEvidence。

## 9. 受影响文件
- 增：`apps/worker/agcs_worker/providers/llm_packaging.py`、`tests/test_llm_packaging_provider.py`、`tests/test_llm_packaging_integration.py`。
- 改：`apps/worker/agcs_worker/pipeline.py`（_build_packaging + 渲染循环 ctx 扩展）、`tests/test_get_providers.py`（packaging 选择测）、`README.md`（LLM 文案说明）。
- `.env.example`：`PACKAGING_PROVIDER` 已存在（M0），无需新增；复用 `LLM_MODEL`。
