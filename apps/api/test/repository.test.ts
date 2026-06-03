import { describe, it, expect } from 'vitest'
import { openDb } from '../src/db.js'
import { newId } from '../src/ids.js'

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
