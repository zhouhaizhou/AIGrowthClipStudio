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
