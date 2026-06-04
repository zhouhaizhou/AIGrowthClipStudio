import Fastify, { type FastifyInstance } from 'fastify'
import fastifyStatic from '@fastify/static'
import { resolve, dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import type { DB } from './db.js'
import { CreateTaskBody, ReviewBody } from './schemas.js'
import * as repo from './repository.js'

const here = dirname(fileURLToPath(import.meta.url))
// Relative to this source file; works under tsx (no build step). If a compiled dist/
// output is ever added, this path must be revisited (same caveat as db.ts schema path).
const DEFAULT_WEB_DIR = join(here, '../web')

export function buildServer(db: DB, storageDir: string, webDir: string = DEFAULT_WEB_DIR): FastifyInstance {
  const app = Fastify({ logger: false })

  app.register(fastifyStatic, { root: resolve(storageDir), prefix: '/storage/' })
  app.register(fastifyStatic, { root: resolve(webDir), prefix: '/', decorateReply: false, dotfiles: 'ignore' })

  app.post('/api/ai-growth-clip/tasks', async (req, reply) => {
    const parsed = CreateTaskBody.safeParse(req.body)
    if (!parsed.success) {
      return reply.code(400).send({ error: 'invalid_body', issues: parsed.error.issues })
    }
    const taskId = repo.createTask(db, parsed.data)
    return reply.code(201).send({ taskId })
  })

  app.get('/api/ai-growth-clip/tasks', async (req) => {
    const q = req.query as { status?: string; limit?: string; offset?: string }
    return {
      list: repo.listTasks(db, {
        status: q.status,
        limit: q.limit ? Number(q.limit) : undefined,
        offset: q.offset ? Number(q.offset) : undefined,
      }),
    }
  })

  app.get('/api/ai-growth-clip/tasks/:id', async (req, reply) => {
    const { id } = req.params as { id: string }
    const task = repo.getTask(db, id)
    if (!task) return reply.code(404).send({ error: 'not_found' })
    return task
  })

  app.get('/api/ai-growth-clip/tasks/:id/assets', async (req) => {
    const { id } = req.params as { id: string }
    return { list: repo.getAssetsByTask(db, id) }
  })

  app.post('/api/ai-growth-clip/assets/:id/review', async (req, reply) => {
    const { id } = req.params as { id: string }
    const parsed = ReviewBody.safeParse(req.body)
    if (!parsed.success) {
      return reply.code(400).send({ error: 'invalid_body', issues: parsed.error.issues })
    }
    const updated = repo.reviewAsset(db, id, parsed.data)
    if (!updated) return reply.code(404).send({ error: 'not_found' })
    return updated
  })

  return app
}
