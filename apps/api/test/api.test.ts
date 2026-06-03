import { describe, it, expect } from 'vitest'
import { mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { openDb } from '../src/db.js'
import { buildServer } from '../src/server.js'

function setup() {
  const db = openDb(':memory:')
  const storage = mkdtempSync(join(tmpdir(), 'agcs-'))
  return buildServer(db, storage)
}

const validBody = {
  sourceContentId: '12345',
  sourceContentType: 'episode',
  sourceVideoUrl: 'file:///tmp/x.mp4',
  targetScenarios: ['feed'],
  targetDurations: [15],
  targetAspectRatios: ['9:16'],
  targetLanguages: ['zh-CN'],
  clipCount: 3,
}

describe('api', () => {
  it('POST /tasks creates a task', async () => {
    const app = setup()
    const res = await app.inject({
      method: 'POST',
      url: '/api/ai-growth-clip/tasks',
      payload: validBody,
    })
    expect(res.statusCode).toBe(201)
    expect(JSON.parse(res.body).taskId).toMatch(/^task_/)
  })

  it('POST /tasks rejects invalid body with 400', async () => {
    const app = setup()
    const res = await app.inject({
      method: 'POST',
      url: '/api/ai-growth-clip/tasks',
      payload: { sourceContentId: '' },
    })
    expect(res.statusCode).toBe(400)
  })

  it('GET unknown task returns 404', async () => {
    const app = setup()
    const res = await app.inject({ method: 'GET', url: '/api/ai-growth-clip/tasks/nope' })
    expect(res.statusCode).toBe(404)
  })

  it('GET task after create returns queued', async () => {
    const app = setup()
    const created = await app.inject({
      method: 'POST',
      url: '/api/ai-growth-clip/tasks',
      payload: validBody,
    })
    const { taskId } = JSON.parse(created.body)
    const res = await app.inject({ method: 'GET', url: `/api/ai-growth-clip/tasks/${taskId}` })
    expect(res.statusCode).toBe(200)
    expect(JSON.parse(res.body).status).toBe('queued')
  })
})
