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
