import type { DB } from './db.js'
import { newId } from './ids.js'
import type { CreateTaskInput, ReviewInput } from './schemas.js'

function parseTags(value: unknown): string[] {
  if (typeof value !== 'string') return []
  try {
    const parsed = JSON.parse(value)
    return Array.isArray(parsed) ? parsed : []
  } catch {
    return []
  }
}

export interface TaskSummary {
  id: string
  sourceContentId: string
  title: string | null
  status: string
  progress: number
  currentStep: string | null
  errorMessage: string | null
}

export interface AssetDto {
  id: string
  taskId: string
  segmentId: string
  scenario: string
  duration: number
  aspectRatio: string
  language: string
  videoUrl: string
  coverUrl: string | null
  subtitleUrl: string | null
  title: string | null
  coverText: string | null
  recommendationText: string | null
  tags: string[]
  status: string
}

function toTaskSummary(row: any): TaskSummary {
  return {
    id: row.id,
    sourceContentId: row.source_content_id,
    title: row.title ?? null,
    status: row.status,
    progress: row.progress,
    currentStep: row.current_step ?? null,
    errorMessage: row.error_message ?? null,
  }
}

function toAssetDto(row: any): AssetDto {
  return {
    id: row.id,
    taskId: row.task_id,
    segmentId: row.segment_id,
    scenario: row.scenario,
    duration: row.duration,
    aspectRatio: row.aspect_ratio,
    language: row.language,
    videoUrl: row.video_url,
    coverUrl: row.cover_url ?? null,
    subtitleUrl: row.subtitle_url ?? null,
    title: row.title ?? null,
    coverText: row.cover_text ?? null,
    recommendationText: row.recommendation_text ?? null,
    tags: parseTags(row.tags),
    status: row.status,
  }
}

export function createTask(db: DB, input: CreateTaskInput): string {
  const id = newId('task')
  const now = Date.now()
  db.prepare(
    `INSERT INTO ai_clip_tasks
      (id, source_content_id, source_content_type, source_video_url, title, description, category,
       tags, target_scenarios, target_durations, target_aspect_ratios, target_languages, clip_count,
       status, progress, current_step, error_message, created_by, created_at, updated_at)
     VALUES
      (@id, @sourceContentId, @sourceContentType, @sourceVideoUrl, @title, @description, @category,
       @tags, @targetScenarios, @targetDurations, @targetAspectRatios, @targetLanguages, @clipCount,
       'queued', 0, NULL, NULL, @createdBy, @now, @now)`,
  ).run({
    id,
    sourceContentId: input.sourceContentId,
    sourceContentType: input.sourceContentType,
    sourceVideoUrl: input.sourceVideoUrl,
    title: input.title ?? null,
    description: input.description ?? null,
    category: input.category ?? null,
    tags: JSON.stringify(input.tags ?? []),
    targetScenarios: JSON.stringify(input.targetScenarios),
    targetDurations: JSON.stringify(input.targetDurations),
    targetAspectRatios: JSON.stringify(input.targetAspectRatios),
    targetLanguages: JSON.stringify(input.targetLanguages),
    clipCount: input.clipCount,
    createdBy: 'system',
    now,
  })
  return id
}

export function getTask(db: DB, id: string): TaskSummary | undefined {
  const row = db.prepare('SELECT * FROM ai_clip_tasks WHERE id = ?').get(id)
  return row ? toTaskSummary(row) : undefined
}

export function listTasks(
  db: DB,
  opts: { status?: string; limit?: number; offset?: number },
): TaskSummary[] {
  const limit = opts.limit ?? 20
  const offset = opts.offset ?? 0
  const rows = opts.status
    ? db
        .prepare(
          'SELECT * FROM ai_clip_tasks WHERE status = ? ORDER BY created_at DESC LIMIT ? OFFSET ?',
        )
        .all(opts.status, limit, offset)
    : db
        .prepare('SELECT * FROM ai_clip_tasks ORDER BY created_at DESC LIMIT ? OFFSET ?')
        .all(limit, offset)
  return (rows as any[]).map(toTaskSummary)
}

export function getAssetsByTask(db: DB, taskId: string): AssetDto[] {
  const rows = db
    .prepare('SELECT * FROM ai_clip_assets WHERE task_id = ? ORDER BY created_at ASC')
    .all(taskId)
  return (rows as any[]).map(toAssetDto)
}

export function reviewAsset(db: DB, id: string, patch: ReviewInput): AssetDto | undefined {
  const result = db.prepare(
    `UPDATE ai_clip_assets SET
       status = @status,
       title = COALESCE(@title, title),
       cover_text = COALESCE(@coverText, cover_text),
       recommendation_text = COALESCE(@recommendationText, recommendation_text),
       updated_at = @now
     WHERE id = @id`,
  ).run({
    id,
    status: patch.status,
    title: patch.title ?? null,
    coverText: patch.coverText ?? null,
    recommendationText: patch.recommendationText ?? null,
    now: Date.now(),
  })
  if (Number(result.changes) === 0) return undefined
  return toAssetDto(db.prepare('SELECT * FROM ai_clip_assets WHERE id = ?').get(id))
}

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
  const nn = (v: number | undefined) => (Number.isFinite(v) ? Math.max(0, Math.floor(v as number)) : 0)
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

export interface Totals {
  impressions: number
  clicks: number
  plays: number
  completions: number
  shares: number
  ctr: number
  completionRate: number
}

export interface AnalyticsSummary {
  totals: Totals
  byScenario: AggRow[]
  byHighlightType: AggRow[]
  suggestions: string[]
}

function aggregate(rows: any[], keyField: string): AggRow[] {
  const map = new Map<string, AggRow>()
  // shares is reported only in totals, not per-group (no per-group consumer needs it)
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
    // count = number of clips in this group (available for UI display)
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

function buildSuggestions(totals: Totals, byScenario: AggRow[], byHighlightType: AggRow[]): string[] {
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

// INNER JOIN on segment (every asset has a segment); LEFT JOIN metrics (asset may have none yet).
export function analyticsSummary(db: DB): AnalyticsSummary {
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
  const totals: Totals = { impressions: 0, clicks: 0, plays: 0, completions: 0, shares: 0, ctr: 0, completionRate: 0 }
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
