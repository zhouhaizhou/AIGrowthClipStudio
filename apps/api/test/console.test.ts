import { describe, it, expect } from 'vitest'
import { mkdtempSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { openDb } from '../src/db.js'
import { buildServer } from '../src/server.js'

function setup() {
  const db = openDb(':memory:')
  const storage = mkdtempSync(join(tmpdir(), 'agcs-st-'))
  const web = mkdtempSync(join(tmpdir(), 'agcs-web-'))
  writeFileSync(join(web, 'index.html'), '<!doctype html><title>AGCS 审核台</title><body>console</body>')
  return buildServer(db, storage, web)
}

describe('console serving', () => {
  it('GET / serves the console HTML', async () => {
    const app = setup()
    const res = await app.inject({ method: 'GET', url: '/' })
    expect(res.statusCode).toBe(200)
    expect(res.body).toContain('审核台')
  })

  it('static root does not shadow the API', async () => {
    const app = setup()
    const res = await app.inject({ method: 'GET', url: '/api/ai-growth-clip/tasks' })
    expect(res.statusCode).toBe(200)
    expect(JSON.parse(res.body)).toHaveProperty('list')
  })

  it('GET /storage/missing.mp4 returns 404 (storage static still active)', async () => {
    const app = setup()
    const res = await app.inject({ method: 'GET', url: '/storage/missing.mp4' })
    expect(res.statusCode).toBe(404)
  })
})
