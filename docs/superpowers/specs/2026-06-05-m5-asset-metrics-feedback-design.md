# M5 — 效果回流（asset metrics + analytics）设计 Spec

- 日期：2026-06-05
- 范围：闭合产品环路的最后一块 —— 素材效果回流。前台/外部埋点上报素材表现（曝光/点击/播放/完播/分享），后端聚合，给出**数据驱动的优化建议**，并在审核台「效果分析」里可视化。设计评审强调的"数据回流优化下一轮素材"。
- 依赖前置：M0–M4 在 main（HEAD 46afb74）。素材表 `ai_clip_assets`、片段表 `ai_clip_segments`（含 highlight_type）已就绪；审核台已托管。
- 自主执行：我自行定稿 spec/plan，subagent-driven + 评审，浏览器 QA，完成后合并并通知。
- 演示性：无需 key。用审核台的「模拟埋点」按钮造数据 → 「效果分析」实时看聚合 + 建议。

## 1. 目标

新增"埋点上报 → 聚合 → 建议"的最小闭环：

成功标准（M5 验收）：

1. 新表 `ai_asset_metrics`（每素材一行计数器）；`recordMetrics(assetId, deltas)` upsert 增量、`getMetrics(assetId)` 读取（缺省零）。
2. `analyticsSummary(db)` 聚合：按 `scenario`、按 `highlight_type`（join segment）算 曝光/点击/CTR/播放/完播/完播率；并产出**规则版建议**（最佳/最差场景与高光类型）。
3. API：`POST /assets/:id/metrics`（增量上报，404 若素材不存在）、`GET /assets/:id/metrics`、`GET /analytics/summary`。
4. 审核台「效果分析」区：刷新看 byScenario/byHighlightType 表 + 建议；每张素材卡加「模拟埋点」按钮上报随机数据（演示用）。
5. 浏览器 QA：模拟埋点几次 → 效果分析出现非零聚合 + 至少一条建议。
6. vitest/全量套件保持绿；mock/worker 不受影响。

## 2. 数据模型

新增（追加到 `db/schema.sql`）：
```sql
CREATE TABLE IF NOT EXISTS ai_asset_metrics (
  asset_id TEXT PRIMARY KEY,
  impressions INTEGER NOT NULL DEFAULT 0,
  clicks INTEGER NOT NULL DEFAULT 0,
  plays INTEGER NOT NULL DEFAULT 0,
  completions INTEGER NOT NULL DEFAULT 0,
  shares INTEGER NOT NULL DEFAULT 0,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
);
```
- 计数器累加模型（非事件流）：上报传增量，upsert 累加。
- 该表由 API 写（埋点回流），worker 不触碰。worker 的 conftest 仍 load 整个 schema（无害）。

## 3. 指标定义
- CTR = clicks / impressions（impressions=0 → 0）。
- 完播率 completionRate = completions / plays（plays=0 → 0）。
- 聚合维度：scenario（素材列）、highlight_type（join segment）。totals 为全局汇总。

## 4. repository（API 侧，TS）
- `recordMetrics(db, assetId, deltas): MetricsRow | undefined` —— 素材不存在返回 undefined；否则 `INSERT ... ON CONFLICT(asset_id) DO UPDATE SET impressions=impressions+@d...`（node:sqlite 支持 upsert）；deltas 缺省 0、负数截断到 0 增量（不允许减）。返回累加后行。
- `getMetrics(db, assetId): MetricsRow`（无行返回全零 + asset_id）。
- `analyticsSummary(db): { totals, byScenario, byHighlightType, suggestions }`：
  - `byScenario`/`byHighlightType`：`[{ key, impressions, clicks, ctr, plays, completions, completionRate, count }]`，按 ctr 降序。
  - `suggestions: string[]`：规则版，仅在有数据时产出，例如：
    - "场景 `feed` CTR 最高（12.3%），优先投放。"
    - "高光类型 `reversal` 完播率最高（68%）。"
    - "场景 `ad` CTR 偏低（1.1%），建议优化开头 hook。"（仅当存在明显低值）
  - 无任何 impressions → suggestions=["暂无足够数据，先投放/模拟埋点。"]。

## 5. API 端点
- `POST /api/ai-growth-clip/assets/:id/metrics`，body（全可选非负整数）`{impressions?,clicks?,plays?,completions?,shares?}` → zod 校验 → recordMetrics → 200 返回 metrics；素材不存在 → 404。
- `GET /api/ai-growth-clip/assets/:id/metrics` → metrics。
- `GET /api/ai-growth-clip/analytics/summary` → analyticsSummary。

## 6. 审核台「效果分析」
- 新增 section：`效果分析` + 刷新按钮 → GET /analytics/summary → 渲染 totals、byScenario 表、byHighlightType 表、suggestions 列表。
- 每张素材卡加「模拟埋点」按钮：POST 该素材一批随机但合理的增量（如 impressions+50、clicks+rand(0..10)、plays+rand(0..40)、completions+rand(0..plays)），toast 后可点效果分析刷新看变化。
- 不改既有审核流；纯新增。

## 7. 错误处理
- 上报负数/非整数 → zod 拒绝（400）或截断到 0；素材不存在 → 404。
- 除零 → 比率 0。
- analytics 无数据 → 空表 + "暂无足够数据"建议，不报错。

## 8. 测试
- `repository.test.ts` 追加：recordMetrics 累加 + 不存在素材→undefined；getMetrics 零；analyticsSummary 在造好的 assets+segments+metrics 上算出正确 ctr/completionRate + 产出建议；空数据→"暂无足够数据"。
- `api.test.ts`/`metrics.test.ts`：POST metrics（含 404、400 非法 body）、GET metrics、GET analytics/summary 形状。
- console.test 不变（控制台仍 200）。
- 全量 API + worker 套件绿。
- 浏览器 QA：模拟埋点 → 效果分析非零 + 建议。

## 9. 不做（M5 范围外）
- 事件级明细/时序图表；真实前台埋点接入（用模拟）；LLM 版优化建议（规则版即可，LLM 钩子留后）；A/B 实验框架；ai_prompt_runs 成本表。

## 10. 受影响文件
- 改：`db/schema.sql`（+ai_asset_metrics）、`apps/api/src/repository.ts`（metrics + analytics）、`apps/api/src/schemas.ts`（MetricsBody）、`apps/api/src/server.ts`（3 端点）、`apps/api/web/index.html`（效果分析 + 模拟埋点）、`README.md`。
- 增：`apps/api/test/metrics.test.ts`。
- `repository.test.ts` 追加 metrics/analytics 断言。
