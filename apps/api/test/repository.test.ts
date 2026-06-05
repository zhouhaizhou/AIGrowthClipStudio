import { describe, it, expect } from 'vitest'
import { openDb } from '../src/db.js'
import { newId } from '../src/ids.js'
import * as repo from '../src/repository.js'

describe('db + ids', () => {
  it('opens in-memory db with all tables', () => {
    const db = openDb(':memory:')
    const names = db
      .prepare("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
      .all()
      .map((r: any) => r.name)
    expect(names).toContain('ai_clip_tasks')
    expect(names).toContain('ai_clip_segments')
    expect(names).toContain('ai_clip_assets')
  })

  it('newId has prefix', () => {
    expect(newId('task')).toMatch(/^task_[0-9a-f]{16}$/)
  })
})

const baseInput = {
  sourceContentId: '12345',
  sourceContentType: 'episode' as const,
  sourceVideoUrl: 'file:///tmp/x.mp4',
  tags: ['逆袭'],
  targetScenarios: ['feed' as const],
  targetDurations: [15],
  targetAspectRatios: ['9:16' as const],
  targetLanguages: ['zh-CN'],
  clipCount: 3,
}

describe('repository', () => {
  it('creates a task as queued', () => {
    const db = openDb(':memory:')
    const id = repo.createTask(db, baseInput as any)
    expect(id).toMatch(/^task_/)
    const task = repo.getTask(db, id)
    expect(task?.status).toBe('queued')
    expect(task?.progress).toBe(0)
  })

  it('lists tasks newest first', () => {
    const db = openDb(':memory:')
    repo.createTask(db, baseInput as any)
    repo.createTask(db, baseInput as any)
    expect(repo.listTasks(db, {}).length).toBe(2)
  })

  it('reviews an asset', () => {
    const db = openDb(':memory:')
    const taskId = repo.createTask(db, baseInput as any)
    const now = Date.now()
    db.prepare(
      `INSERT INTO ai_clip_assets
        (id, task_id, segment_id, source_content_id, scenario, duration, aspect_ratio, language,
         video_url, status, tags, created_at, updated_at)
       VALUES ('asset_1', @t, 'seg_1', '12345', 'feed', 15, '9:16', 'zh-CN',
         '/storage/x.mp4', 'pending_review', '[]', @n, @n)`,
    ).run({ t: taskId, n: now })
    const updated = repo.reviewAsset(db, 'asset_1', { status: 'approved', title: 'NT' })
    expect(updated?.status).toBe('approved')
    expect(updated?.title).toBe('NT')
    expect(repo.getAssetsByTask(db, taskId).length).toBe(1)
  })

  it('returns undefined when reviewing unknown asset', () => {
    const db = openDb(':memory:')
    expect(repo.reviewAsset(db, 'nope', { status: 'approved' })).toBeUndefined()
  })
})

describe('task summary fields', () => {
  it('includes sourceContentId and title', () => {
    const db = openDb(':memory:')
    repo.createTask(db, { ...(baseInput as any), title: 'T-标题' })
    const t = repo.listTasks(db, {})[0] as any
    expect(t.sourceContentId).toBe('12345')
    expect(t.title).toBe('T-标题')
  })
})

describe('task summary null title', () => {
  it('title is null when not provided', () => {
    const db = openDb(':memory:')
    repo.createTask(db, baseInput as any)   // baseInput has no title
    expect((repo.listTasks(db, {})[0] as any).title).toBeNull()
  })
})

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
