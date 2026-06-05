# M5 — 效果回流（asset metrics + analytics）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`).

**Goal:** 素材效果回流闭环：埋点上报（曝光/点击/播放/完播/分享）→ 聚合（按场景/高光类型，算 CTR/完播率）→ 规则版优化建议 → 审核台「效果分析」可视化 + 「模拟埋点」演示。无需 key。

**Architecture:** 新表 `ai_asset_metrics`（每素材计数器，upsert 累加）。API 加 3 端点（POST metrics、GET metrics、GET analytics/summary）。repository 加 recordMetrics/getMetrics/analyticsSummary。审核台加效果分析区。mock/worker 不受影响。

**对应 spec：** [docs/superpowers/specs/2026-06-05-m5-asset-metrics-feedback-design.md](../specs/2026-06-05-m5-asset-metrics-feedback-design.md)

**前置：** M0–M4 在 main（HEAD 46afb74）。API 测试从 `apps/api` 跑 `npx vitest`。

---

## Task 1: schema + recordMetrics/getMetrics + MetricsBody

**Files:** Modify `db/schema.sql`, `apps/api/src/repository.ts`, `apps/api/src/schemas.ts`; Test `apps/api/test/repository.test.ts`

- [ ] **Step 1: APPEND failing tests to `apps/api/test/repository.test.ts`**（末尾；沿用已有 openDb/repo/baseInput）

```ts
function seedAsset(db: any, id: string, scenario = 'feed', segId = 'seg_x', htype = 'reversal') {
  const now = Date.now()
  db.prepare(`INSERT OR IGNORE INTO ai_clip_segments (id, task_id, source_content_id, start_ms, end_ms, duration_ms, highlight_type, score, risk_level, status, created_at, updated_at) VALUES (@s,'t','12345',0,5000,5000,@h,0.9,'low','candidate',@n,@n)`).run({ s: segId, h: htype, n: now })
  db.prepare(`INSERT INTO ai_clip_assets (id, task_id, segment_id, source_content_id, scenario, duration, aspect_ratio, language, video_url, status, tags, created_at, updated_at) VALUES (@id,'t',@seg,'12345',@sc,15,'9:16','zh-CN','/v.mp4','approved','[]',@n,@n)`).run({ id, seg: segId, sc: scenario, n: now })
}

describe('metrics', () => {
  it('recordMetrics upserts and accumulates', () => {
    const db = openDb(':memory:')
    seedAsset(db, 'asset_m1')
    expect(repo.recordMetrics(db, 'asset_m1', { impressions: 10, clicks: 2 })?.impressions).toBe(10)
    const m = repo.recordMetrics(db, 'asset_m1', { clicks: 3, plays: 4 })
    expect(m?.clicks).toBe(5)
    expect(m?.plays).toBe(4)
    expect(repo.getMetrics(db, 'asset_m1').clicks).toBe(5)
  })

  it('recordMetrics on unknown asset returns undefined', () => {
    const db = openDb(':memory:')
    expect(repo.recordMetrics(db, 'nope', { impressions: 1 })).toBeUndefined()
  })

  it('getMetrics returns zeros for unknown', () => {
    const db = openDb(':memory:')
    expect(repo.getMetrics(db, 'nope')).toEqual({ assetId: 'nope', impressions: 0, clicks: 0, plays: 0, completions: 0, shares: 0 })
  })

  it('negative deltas are floored to 0', () => {
    const db = openDb(':memory:')
    seedAsset(db, 'asset_m2')
    repo.recordMetrics(db, 'asset_m2', { impressions: -5, clicks: 2 })
    expect(repo.getMetrics(db, 'asset_m2').impressions).toBe(0)
    expect(repo.getMetrics(db, 'asset_m2').clicks).toBe(2)
  })
})
```

- [ ] **Step 2: 运行确认失败**

Run: `cd apps/api && npx vitest run test/repository.test.ts` → FAIL（recordMetrics 不存在 / 无表）。

- [ ] **Step 3: APPEND to `db/schema.sql`**

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

- [ ] **Step 4: APPEND to `apps/api/src/schemas.ts`**

```ts
export const MetricsBody = z.object({
  impressions: z.number().int().nonnegative().optional(),
  clicks: z.number().int().nonnegative().optional(),
  plays: z.number().int().nonnegative().optional(),
  completions: z.number().int().nonnegative().optional(),
  shares: z.number().int().nonnegative().optional(),
})
export type MetricsInput = z.infer<typeof MetricsBody>
```

- [ ] **Step 5: APPEND to `apps/api/src/repository.ts`** (after the existing exports)

```ts
export interface MetricsRow {
  assetId: string
  impressions: number
  clicks: number
  plays: number
  completions: number
  shares: number
}

function toMetricsRow(assetId: string, row: any): MetricsRow {
  return {
    assetId,
    impressions: row?.impressions ?? 0,
    clicks: row?.clicks ?? 0,
    plays: row?.plays ?? 0,
    completions: row?.completions ?? 0,
    shares: row?.shares ?? 0,
  }
}

export function getMetrics(db: DB, assetId: string): MetricsRow {
  return toMetricsRow(assetId, db.prepare('SELECT * FROM ai_asset_metrics WHERE asset_id = ?').get(assetId))
}

export function recordMetrics(
  db: DB,
  assetId: string,
  deltas: { impressions?: number; clicks?: number; plays?: number; completions?: number; shares?: number },
): MetricsRow | undefined {
  const exists = db.prepare('SELECT id FROM ai_clip_assets WHERE id = ?').get(assetId)
  if (!exists) return undefined
  const nn = (v: number | undefined) => Math.max(0, Math.floor(v ?? 0))
  const d = {
    impressions: nn(deltas.impressions), clicks: nn(deltas.clicks), plays: nn(deltas.plays),
    completions: nn(deltas.completions), shares: nn(deltas.shares),
  }
  const now = Date.now()
  db.prepare(
    `INSERT INTO ai_asset_metrics (asset_id, impressions, clicks, plays, completions, shares, created_at, updated_at)
     VALUES (@id, @impressions, @clicks, @plays, @completions, @shares, @now, @now)
     ON CONFLICT(asset_id) DO UPDATE SET
       impressions = impressions + @impressions, clicks = clicks + @clicks, plays = plays + @plays,
       completions = completions + @completions, shares = shares + @shares, updated_at = @now`,
  ).run({ id: assetId, ...d, now })
  return getMetrics(db, assetId)
}
```

- [ ] **Step 6: 运行确认通过 + 全量**

Run: `npx vitest run test/repository.test.ts` → PASS。`npx vitest run` → 全量 API 套件绿。

- [ ] **Step 7: Commit**

```bash
cd /Users/jc/codesOther/AIGrowthClipStudio && git add -A && git commit -m "feat(m5/api): ai_asset_metrics table + recordMetrics/getMetrics + MetricsBody

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: analyticsSummary + 规则建议

**Files:** Modify `apps/api/src/repository.ts`; Test `apps/api/test/repository.test.ts`

- [ ] **Step 1: APPEND failing test to `apps/api/test/repository.test.ts`**（复用 Task 1 的 `seedAsset`）

```ts
describe('analytics', () => {
  it('aggregates ctr/completion and emits suggestions', () => {
    const db = openDb(':memory:')
    seedAsset(db, 'a_feed', 'feed', 'seg_feed', 'reversal')
    seedAsset(db, 'a_ad', 'ad', 'seg_ad', 'conflict')
    repo.recordMetrics(db, 'a_feed', { impressions: 100, clicks: 20, plays: 80, completions: 60 })
    repo.recordMetrics(db, 'a_ad', { impressions: 100, clicks: 2, plays: 50, completions: 10 })
    const s = repo.analyticsSummary(db)
    expect(s.totals.impressions).toBe(200)
    const feed = s.byScenario.find((x: any) => x.key === 'feed')
    expect(feed.ctr).toBeCloseTo(0.2, 5)
    // byScenario sorted by ctr desc -> feed first
    expect(s.byScenario[0].key).toBe('feed')
    expect(s.suggestions.length).toBeGreaterThan(0)
    expect(s.suggestions.join(' ')).toContain('feed')
  })

  it('empty data yields a no-data suggestion', () => {
    const db = openDb(':memory:')
    const s = repo.analyticsSummary(db)
    expect(s.totals.impressions).toBe(0)
    expect(s.suggestions).toEqual(['暂无足够数据，先投放/模拟埋点。'])
  })
})
```

- [ ] **Step 2: 运行确认失败**

Run: `cd apps/api && npx vitest run test/repository.test.ts` → FAIL（analyticsSummary 不存在）。

- [ ] **Step 3: APPEND to `apps/api/src/repository.ts`**

```ts
export interface AggRow {
  key: string
  impressions: number
  clicks: number
  ctr: number
  plays: number
  completions: number
  completionRate: number
  count: number
}

function aggregate(rows: any[], keyField: string): AggRow[] {
  const map = new Map<string, AggRow>()
  for (const r of rows) {
    const key = r[keyField] ?? 'unknown'
    let a = map.get(key)
    if (!a) {
      a = { key, impressions: 0, clicks: 0, ctr: 0, plays: 0, completions: 0, completionRate: 0, count: 0 }
      map.set(key, a)
    }
    a.impressions += r.impressions
    a.clicks += r.clicks
    a.plays += r.plays
    a.completions += r.completions
    a.count += 1
  }
  const out = [...map.values()]
  for (const a of out) {
    a.ctr = a.impressions > 0 ? a.clicks / a.impressions : 0
    a.completionRate = a.plays > 0 ? a.completions / a.plays : 0
  }
  out.sort((x, y) => y.ctr - x.ctr)
  return out
}

function pct(x: number): string {
  return (x * 100).toFixed(1) + '%'
}

function buildSuggestions(totals: any, byScenario: AggRow[], byHighlightType: AggRow[]): string[] {
  if (totals.impressions === 0) return ['暂无足够数据，先投放/模拟埋点。']
  const out: string[] = []
  const scen = byScenario.filter((a) => a.impressions > 0)
  if (scen.length) {
    const best = scen[0]
    out.push('场景 `' + best.key + '` CTR 最高（' + pct(best.ctr) + '），优先投放。')
    const worst = scen[scen.length - 1]
    if (worst.key !== best.key && worst.ctr < best.ctr) {
      out.push('场景 `' + worst.key + '` CTR 偏低（' + pct(worst.ctr) + '），建议优化开头 hook。')
    }
  }
  const ht = byHighlightType.filter((a) => a.plays > 0)
  if (ht.length) {
    const bestC = [...ht].sort((a, b) => b.completionRate - a.completionRate)[0]
    out.push('高光类型 `' + bestC.key + '` 完播率最高（' + pct(bestC.completionRate) + '）。')
  }
  return out
}

export function analyticsSummary(db: DB) {
  const rows = db
    .prepare(
      `SELECT a.scenario AS scenario, s.highlight_type AS highlight_type,
              COALESCE(m.impressions,0) AS impressions, COALESCE(m.clicks,0) AS clicks,
              COALESCE(m.plays,0) AS plays, COALESCE(m.completions,0) AS completions,
              COALESCE(m.shares,0) AS shares
       FROM ai_clip_assets a
       JOIN ai_clip_segments s ON s.id = a.segment_id
       LEFT JOIN ai_asset_metrics m ON m.asset_id = a.id`,
    )
    .all() as any[]
  const totals: any = { impressions: 0, clicks: 0, plays: 0, completions: 0, shares: 0 }
  for (const r of rows) {
    totals.impressions += r.impressions
    totals.clicks += r.clicks
    totals.plays += r.plays
    totals.completions += r.completions
    totals.shares += r.shares
  }
  totals.ctr = totals.impressions > 0 ? totals.clicks / totals.impressions : 0
  totals.completionRate = totals.plays > 0 ? totals.completions / totals.plays : 0
  const byScenario = aggregate(rows, 'scenario')
  const byHighlightType = aggregate(rows, 'highlight_type')
  return { totals, byScenario, byHighlightType, suggestions: buildSuggestions(totals, byScenario, byHighlightType) }
}
```

- [ ] **Step 4: 运行确认通过 + 全量**

Run: `npx vitest run test/repository.test.ts` → PASS。`npx vitest run` → 全量绿。

- [ ] **Step 5: Commit**

```bash
cd /Users/jc/codesOther/AIGrowthClipStudio && git add -A && git commit -m "feat(m5/api): analyticsSummary aggregation (ctr/completion) + rule-based suggestions

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: API 端点（metrics + analytics）

**Files:** Modify `apps/api/src/server.ts`; Test `apps/api/test/metrics.test.ts`

- [ ] **Step 1: 写失败测试 `apps/api/test/metrics.test.ts`**

```ts
import { describe, it, expect } from 'vitest'
import { mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { openDb } from '../src/db.js'
import { buildServer } from '../src/server.js'

function setup() {
  const db = openDb(':memory:')
  const now = Date.now()
  db.prepare(`INSERT INTO ai_clip_segments (id, task_id, source_content_id, start_ms, end_ms, duration_ms, highlight_type, score, risk_level, status, created_at, updated_at) VALUES ('seg1','t','1',0,5000,5000,'reversal',0.9,'low','candidate',?,?)`).run(now, now)
  db.prepare(`INSERT INTO ai_clip_assets (id, task_id, segment_id, source_content_id, scenario, duration, aspect_ratio, language, video_url, status, tags, created_at, updated_at) VALUES ('asset1','t','seg1','1','feed',15,'9:16','zh-CN','/v.mp4','approved','[]',?,?)`).run(now, now)
  const storage = mkdtempSync(join(tmpdir(), 'agcs-st-'))
  return buildServer(db, storage)
}

describe('metrics api', () => {
  it('POST metrics increments and GET returns it', async () => {
    const app = setup()
    const p = await app.inject({ method: 'POST', url: '/api/ai-growth-clip/assets/asset1/metrics', payload: { impressions: 10, clicks: 3 } })
    expect(p.statusCode).toBe(200)
    expect(JSON.parse(p.body).clicks).toBe(3)
    const g = await app.inject({ method: 'GET', url: '/api/ai-growth-clip/assets/asset1/metrics' })
    expect(JSON.parse(g.body).impressions).toBe(10)
  })

  it('POST metrics unknown asset 404', async () => {
    const app = setup()
    const r = await app.inject({ method: 'POST', url: '/api/ai-growth-clip/assets/nope/metrics', payload: { clicks: 1 } })
    expect(r.statusCode).toBe(404)
  })

  it('POST metrics invalid body 400', async () => {
    const app = setup()
    const r = await app.inject({ method: 'POST', url: '/api/ai-growth-clip/assets/asset1/metrics', payload: { clicks: -1 } })
    expect(r.statusCode).toBe(400)
  })

  it('GET analytics/summary returns shape', async () => {
    const app = setup()
    await app.inject({ method: 'POST', url: '/api/ai-growth-clip/assets/asset1/metrics', payload: { impressions: 100, clicks: 20, plays: 80, completions: 50 } })
    const r = await app.inject({ method: 'GET', url: '/api/ai-growth-clip/analytics/summary' })
    expect(r.statusCode).toBe(200)
    const s = JSON.parse(r.body)
    expect(s).toHaveProperty('totals')
    expect(s).toHaveProperty('byScenario')
    expect(s).toHaveProperty('suggestions')
    expect(s.totals.impressions).toBe(100)
  })
})
```

- [ ] **Step 2: 运行确认失败**

Run: `cd apps/api && npx vitest run test/metrics.test.ts` → FAIL（404 路由不存在）。

- [ ] **Step 3: 改 `apps/api/src/server.ts`** —— import 加 `MetricsBody`，在现有 review 路由之后新增 3 个路由：
```ts
import { CreateTaskBody, ReviewBody, MetricsBody } from './schemas.js'
```
```ts
  app.post('/api/ai-growth-clip/assets/:id/metrics', async (req, reply) => {
    const { id } = req.params as { id: string }
    const parsed = MetricsBody.safeParse(req.body)
    if (!parsed.success) {
      return reply.code(400).send({ error: 'invalid_body', issues: parsed.error.issues })
    }
    const m = repo.recordMetrics(db, id, parsed.data)
    if (!m) return reply.code(404).send({ error: 'not_found' })
    return m
  })

  app.get('/api/ai-growth-clip/assets/:id/metrics', async (req) => {
    const { id } = req.params as { id: string }
    return repo.getMetrics(db, id)
  })

  app.get('/api/ai-growth-clip/analytics/summary', async () => repo.analyticsSummary(db))
```

- [ ] **Step 4: 运行确认通过 + 全量**

Run: `npx vitest run test/metrics.test.ts` → 4 passed。`npx vitest run` → 全量 API 套件绿（含 console/repository/api/schemas/metrics）。

- [ ] **Step 5: Commit**

```bash
cd /Users/jc/codesOther/AIGrowthClipStudio && git add -A && git commit -m "feat(m5/api): metrics ingest + asset metrics + analytics/summary endpoints

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: 审核台「效果分析」+ 模拟埋点 + README

**Files:** Modify `apps/api/web/index.html`, `README.md`

- [ ] **Step 1: 改 `apps/api/web/index.html`** —— 三处增量（不动既有逻辑）：

(a) 在 `<main>` 的「素材」section 之后追加效果分析 section：
```html
  <section><div class="row"><h2>效果分析</h2><button class="ghost" id="btn-analytics">刷新</button></div>
    <div class="card" id="analytics"><span class="muted">点刷新查看（先在素材卡点「模拟埋点」造数据）</span></div></section>
```

(b) 在 `<script>` 末尾（`loadTasks();` 之前）追加效果分析逻辑：
```javascript
function fmtPct(x){return (x*100).toFixed(1)+'%';}
function aggTable(title,rows){if(!rows||!rows.length)return '';let h='<h3 style="font-size:13px;margin:10px 0 4px">'+esc(title)+'</h3><table><thead><tr><th>维度</th><th>曝光</th><th>点击</th><th>CTR</th><th>播放</th><th>完播率</th></tr></thead><tbody>';rows.forEach(r=>{h+='<tr><td>'+esc(r.key)+'</td><td>'+r.impressions+'</td><td>'+r.clicks+'</td><td>'+fmtPct(r.ctr)+'</td><td>'+r.plays+'</td><td>'+fmtPct(r.completionRate)+'</td></tr>';});return h+'</tbody></table>';}
async function loadAnalytics(){const box=$('analytics');box.innerHTML='<span class="muted">载入中…</span>';try{const s=await api('/analytics/summary');let h='<div class="meta">总曝光 '+s.totals.impressions+' · CTR '+fmtPct(s.totals.ctr)+' · 完播率 '+fmtPct(s.totals.completionRate)+'</div>';h+=aggTable('按场景',s.byScenario);h+=aggTable('按高光类型',s.byHighlightType);h+='<h3 style="font-size:13px;margin:12px 0 4px">优化建议</h3><ul style="margin:0;padding-left:18px">'+s.suggestions.map(x=>'<li>'+esc(x)+'</li>').join('')+'</ul>';box.innerHTML=h;}catch(e){box.innerHTML='';toast('载入分析失败：'+e.message,true);}}
$('btn-analytics').onclick=loadAnalytics;
```

(c) 在 `card(a)` 的按钮行里，给「驳回」按钮后追加一个「模拟埋点」按钮，并在 `card` 里加上报逻辑。把按钮行 HTML 改为：
```javascript
'<div class="row" style="justify-content:flex-start;gap:8px"><button class="ok" data-testid="approve">通过</button><button class="bad">驳回</button><button class="ghost sim">模拟埋点</button></div>';
```
并在 `c.querySelector('.bad').onclick=...` 之后追加：
```javascript
c.querySelector('.sim').onclick=async()=>{try{const imp=50,clk=Math.floor(Math.random()*12),ply=Math.floor(Math.random()*40),cmp=Math.floor(Math.random()*(ply+1));await api('/assets/'+a.id+'/metrics',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({impressions:imp,clicks:clk,plays:ply,completions:cmp})});toast('已模拟埋点（曝光+'+imp+' 点击+'+clk+' 播放+'+ply+' 完播+'+cmp+'）');}catch(e){toast('模拟失败：'+e.message,true);}};
```

- [ ] **Step 2: 验证控制台仍服务**

Run: `cd apps/api && npx vitest run test/console.test.ts` → 3 passed（index.html 仍含「审核台」）。`npx vitest run` → 全量 API 套件绿。

- [ ] **Step 3: 改 `README.md`** —— 在「审核台（M4）」一节之后追加：
```markdown
## 效果回流（M5）

审核台底部「效果分析」聚合素材的曝光/点击/CTR/完播率（按场景、按高光类型）并给出规则版优化建议。每张素材卡的「模拟埋点」按钮可造数据演示；生产中由前台埋点调 `POST /api/ai-growth-clip/assets/:id/metrics` 上报。
```
（确认 README ``` 数为偶数、未破坏其它小节。）

- [ ] **Step 4: Commit**

```bash
cd /Users/jc/codesOther/AIGrowthClipStudio && git add -A && git commit -m "feat(m5/web): analytics panel + simulate-metrics button; docs

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

- **Spec coverage：** 1（表+record/get）→ Task 1；2（聚合+建议）→ Task 2；3（3 端点）→ Task 3；4（效果分析+模拟埋点）→ Task 4；5（浏览器 QA）→ 控制器合并前验证；6（套件绿）→ 各 Task 回归。§7 错误处理（负数 floor、404、除零、空数据建议）→ Task 1（nn floor）+ Task 2（buildSuggestions 空）+ Task 3（404/400）。无缺口。
- **Placeholder scan：** 无 TBD；每步含完整代码/命令/期望；README 围栏注明。
- **Type consistency：** `recordMetrics(db, assetId, deltas)->MetricsRow|undefined`、`getMetrics(db, assetId)->MetricsRow`、`analyticsSummary(db)->{totals, byScenario:AggRow[], byHighlightType:AggRow[], suggestions:string[]}`、`MetricsBody`、控制台 fetch 字段（impressions/clicks/ctr/plays/completionRate、suggestions）与 repository/server 一致。`ai_asset_metrics` 列名与 schema 一致。

---

## Execution: subagent-driven，每 Task 实现→规格评审→质量评审→修复；Task 全完后控制器浏览器 QA（模拟埋点→效果分析非零+建议），再合并 main + 推送 + 通知。
