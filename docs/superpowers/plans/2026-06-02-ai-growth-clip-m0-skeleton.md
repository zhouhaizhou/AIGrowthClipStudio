# AI Growth Clip Studio — M0 可运行骨架 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 搭出端到端可跑通的 M0 骨架：Node BFF 建任务 → Python worker 轮询消费 → mock 流水线 + 真实 ffmpeg 切片/封面 → 写产物与 DB 行 → API 查询/审核。

**Architecture:** SQLite（WAL）同时作状态库与任务队列；Node API 写任务行、读状态/产物；Python worker 原子认领 `queued` 任务、跑流水线、写产物文件与 `segments`/`assets` 行。重服务（ASR/高光/文案）走 mock 适配器，`render_clips`/`select_cover` 走真实 ffmpeg。

**Tech Stack:** Node 24 + TypeScript + Fastify + `node:sqlite`(内置) + zod + vitest；Python 3.9 stdlib(sqlite3 + subprocess) + ffmpeg + pytest。

**已在本机验证的前提：** ffmpeg 8.1/ffprobe、Node v24.14、Python 3.9.6、`node:sqlite` 无需编译可用（仅有 ExperimentalWarning）。无 Redis/Docker/LLM key（M0 不需要）。

**对应文档：** spec [docs/superpowers/specs/2026-06-02-ai-growth-clip-m0-skeleton-design.md](../specs/2026-06-02-ai-growth-clip-m0-skeleton-design.md)。

---

## File Structure

```text
AIGrowthClipStudio/
  db/schema.sql                         # 唯一 DDL（两端共用）
  .env.example
  apps/api/                             # Node BFF
    package.json  tsconfig.json  vitest.config.ts
    src/db.ts          # node:sqlite 连接 + schema 初始化
    src/ids.ts         # id 生成
    src/schemas.ts     # zod 请求校验
    src/repository.ts  # 任务/素材数据访问
    src/server.ts      # Fastify 应用工厂 buildServer()
    src/index.ts       # 进程入口
    test/repository.test.ts
    test/api.test.ts
  apps/worker/                          # Python worker
    pyproject.toml
    agcs_worker/__init__.py
    agcs_worker/config.py     # env 加载
    agcs_worker/db.py         # sqlite 认领/更新/插入
    agcs_worker/ffmpeg.py     # ffprobe/ffmpeg 子进程封装
    agcs_worker/providers/__init__.py
    agcs_worker/providers/base.py   # dataclass + Protocol
    agcs_worker/providers/mock.py   # mock 适配器
    agcs_worker/pipeline.py   # 流水线编排 run_task()
    agcs_worker/main.py       # 轮询循环 / --once
    tests/conftest.py
    tests/test_db.py
    tests/test_ffmpeg.py
    tests/test_providers.py
    tests/test_pipeline.py
    tests/test_main.py
  scripts/smoke.sh                      # 端到端冒烟
```

---

## Task 1: 仓库骨架与共用 schema

**Files:**
- Create: `db/schema.sql`
- Create: `.env.example`
- Create: `apps/api/package.json`, `apps/api/tsconfig.json`, `apps/api/vitest.config.ts`
- Create: `apps/worker/pyproject.toml`, `apps/worker/agcs_worker/__init__.py`, `apps/worker/agcs_worker/providers/__init__.py`

- [ ] **Step 1: 写 `db/schema.sql`**

```sql
CREATE TABLE IF NOT EXISTS ai_clip_tasks (
  id TEXT PRIMARY KEY,
  source_content_id TEXT NOT NULL,
  source_content_type TEXT NOT NULL,
  source_video_url TEXT NOT NULL,
  title TEXT,
  description TEXT,
  category TEXT,
  tags TEXT NOT NULL DEFAULT '[]',
  target_scenarios TEXT NOT NULL DEFAULT '[]',
  target_durations TEXT NOT NULL DEFAULT '[]',
  target_aspect_ratios TEXT NOT NULL DEFAULT '["9:16"]',
  target_languages TEXT NOT NULL DEFAULT '["zh-CN"]',
  clip_count INTEGER NOT NULL DEFAULT 3,
  status TEXT NOT NULL DEFAULT 'queued',
  progress INTEGER NOT NULL DEFAULT 0,
  current_step TEXT,
  error_message TEXT,
  created_by TEXT,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON ai_clip_tasks(status, created_at);

CREATE TABLE IF NOT EXISTS ai_clip_segments (
  id TEXT PRIMARY KEY,
  task_id TEXT NOT NULL,
  source_content_id TEXT NOT NULL,
  start_ms INTEGER NOT NULL,
  end_ms INTEGER NOT NULL,
  duration_ms INTEGER NOT NULL,
  highlight_type TEXT NOT NULL,
  score REAL NOT NULL DEFAULT 0,
  reason TEXT,
  summary TEXT,
  transcript_text TEXT,
  risk_level TEXT NOT NULL DEFAULT 'low',
  risk_reason TEXT,
  packaging_draft TEXT,
  status TEXT NOT NULL DEFAULT 'candidate',
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_segments_task ON ai_clip_segments(task_id);

CREATE TABLE IF NOT EXISTS ai_clip_assets (
  id TEXT PRIMARY KEY,
  task_id TEXT NOT NULL,
  segment_id TEXT NOT NULL,
  source_content_id TEXT NOT NULL,
  scenario TEXT NOT NULL,
  duration INTEGER NOT NULL,
  aspect_ratio TEXT NOT NULL,
  language TEXT NOT NULL,
  video_url TEXT NOT NULL,
  cover_url TEXT,
  subtitle_url TEXT,
  title TEXT,
  cover_text TEXT,
  recommendation_text TEXT,
  tags TEXT NOT NULL DEFAULT '[]',
  status TEXT NOT NULL DEFAULT 'pending_review',
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_assets_task ON ai_clip_assets(task_id);
```

- [ ] **Step 2: 写 `.env.example`**

```bash
DB_PATH=./data/agcs.db
STORAGE_DIR=./storage
API_PORT=8787
WORKER_POLL_INTERVAL_MS=1000
ASR_PROVIDER=mock
HIGHLIGHT_PROVIDER=mock
PACKAGING_PROVIDER=mock
```

- [ ] **Step 3: 写 `apps/api/package.json`**

```json
{
  "name": "@agcs/api",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "tsx watch src/index.ts",
    "start": "tsx src/index.ts",
    "test": "vitest run",
    "typecheck": "tsc --noEmit"
  },
  "dependencies": {
    "@fastify/static": "^8.1.0",
    "fastify": "^5.2.0",
    "zod": "^3.24.0"
  },
  "devDependencies": {
    "@types/node": "^22.13.0",
    "tsx": "^4.19.2",
    "typescript": "^5.7.0",
    "vitest": "^2.1.8"
  }
}
```

- [ ] **Step 4: 写 `apps/api/tsconfig.json`**

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "ES2022",
    "moduleResolution": "bundler",
    "strict": true,
    "esModuleInterop": true,
    "skipLibCheck": true,
    "resolveJsonModule": true,
    "types": ["node"],
    "noEmit": true
  },
  "include": ["src", "test"]
}
```

- [ ] **Step 5: 写 `apps/api/vitest.config.ts`**

```ts
import { defineConfig } from 'vitest/config'

export default defineConfig({
  test: { include: ['test/**/*.test.ts'] },
})
```

- [ ] **Step 6: 写 Python 包占位文件**

`apps/worker/pyproject.toml`:
```toml
[tool.pytest.ini_options]
pythonpath = ["."]
testpaths = ["tests"]
```

`apps/worker/agcs_worker/__init__.py`: （空文件）
```python
```

`apps/worker/agcs_worker/providers/__init__.py`: （空文件）
```python
```

- [ ] **Step 7: 安装 API 依赖并验证 schema 可加载**

Run:
```bash
cd apps/api && npm install
node --disable-warning=ExperimentalWarning -e "const {DatabaseSync}=require('node:sqlite');const fs=require('fs');const d=new DatabaseSync(':memory:');d.exec(fs.readFileSync('../../db/schema.sql','utf8'));console.log('tables:', d.prepare(\"select name from sqlite_master where type='table' order by name\").all().map(r=>r.name).join(','))"
```
Expected: `tables: ai_clip_assets,ai_clip_segments,ai_clip_tasks`，npm install 成功。

- [ ] **Step 8: Commit**

```bash
cd ../.. && git add -A && git commit -m "feat(m0): repo scaffold, shared sqlite schema, api/worker skeletons"
```

---

## Task 2: API DB 层与 ID 生成

**Files:**
- Create: `apps/api/src/db.ts`
- Create: `apps/api/src/ids.ts`
- Test: `apps/api/test/repository.test.ts`（本任务先建文件，仅测 db/ids）

- [ ] **Step 1: 写失败测试 `apps/api/test/repository.test.ts`**

```ts
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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd apps/api && npx vitest run test/repository.test.ts`
Expected: FAIL（`Cannot find module '../src/db.js'`）。

- [ ] **Step 3: 写 `apps/api/src/db.ts`**

```ts
import { DatabaseSync } from 'node:sqlite'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const here = dirname(fileURLToPath(import.meta.url))
const SCHEMA_PATH = join(here, '../../../db/schema.sql')

export type DB = DatabaseSync

export function openDb(path: string): DB {
  const db = new DatabaseSync(path)
  db.exec('PRAGMA journal_mode = WAL')
  db.exec('PRAGMA foreign_keys = ON')
  db.exec(readFileSync(SCHEMA_PATH, 'utf8'))
  return db
}
```

- [ ] **Step 4: 写 `apps/api/src/ids.ts`**

```ts
import { randomBytes } from 'node:crypto'

export function newId(prefix: string): string {
  return `${prefix}_${randomBytes(8).toString('hex')}`
}
```

- [ ] **Step 5: 运行测试确认通过**

Run: `npx vitest run test/repository.test.ts`
Expected: PASS（2 passed）。

- [ ] **Step 6: Commit**

```bash
cd ../.. && git add -A && git commit -m "feat(m0/api): node:sqlite db init + id generator"
```

---

## Task 3: 请求校验 schema（zod）

**Files:**
- Create: `apps/api/src/schemas.ts`
- Test: `apps/api/test/schemas.test.ts`

- [ ] **Step 1: 写失败测试 `apps/api/test/schemas.test.ts`**

```ts
import { describe, it, expect } from 'vitest'
import { CreateTaskBody, ReviewBody } from '../src/schemas.js'

describe('schemas', () => {
  it('accepts a valid create-task body and applies defaults', () => {
    const parsed = CreateTaskBody.parse({
      sourceContentId: '12345',
      sourceContentType: 'episode',
      sourceVideoUrl: 'file:///tmp/x.mp4',
      targetScenarios: ['feed'],
      targetDurations: [15, 30],
    })
    expect(parsed.targetAspectRatios).toEqual(['9:16'])
    expect(parsed.targetLanguages).toEqual(['zh-CN'])
    expect(parsed.clipCount).toBe(3)
    expect(parsed.tags).toEqual([])
  })

  it('rejects empty sourceContentId', () => {
    const r = CreateTaskBody.safeParse({ sourceContentId: '' })
    expect(r.success).toBe(false)
  })

  it('parses a review body', () => {
    expect(ReviewBody.parse({ status: 'approved', title: 'x' }).status).toBe('approved')
  })
})
```

- [ ] **Step 2: 运行测试确认失败**

Run: `npx vitest run test/schemas.test.ts`
Expected: FAIL（找不到 `../src/schemas.js`）。

- [ ] **Step 3: 写 `apps/api/src/schemas.ts`**

```ts
import { z } from 'zod'

export const ScenarioEnum = z.enum(['feed', 'detail', 'ad', 'membership', 'social'])
export const AspectRatioEnum = z.enum(['9:16', '16:9', '1:1', '4:5'])

export const CreateTaskBody = z.object({
  sourceContentId: z.string().min(1),
  sourceContentType: z.enum(['video', 'episode']),
  sourceVideoUrl: z.string().min(1),
  title: z.string().optional(),
  description: z.string().optional(),
  category: z.string().optional(),
  tags: z.array(z.string()).default([]),
  targetScenarios: z.array(ScenarioEnum).min(1),
  targetDurations: z.array(z.number().int().positive()).min(1),
  targetAspectRatios: z.array(AspectRatioEnum).min(1).default(['9:16']),
  targetLanguages: z.array(z.string()).min(1).default(['zh-CN']),
  clipCount: z.number().int().positive().default(3),
})
export type CreateTaskInput = z.infer<typeof CreateTaskBody>

export const ReviewBody = z.object({
  status: z.enum(['approved', 'rejected']),
  title: z.string().optional(),
  coverText: z.string().optional(),
  recommendationText: z.string().optional(),
})
export type ReviewInput = z.infer<typeof ReviewBody>
```

- [ ] **Step 4: 运行测试确认通过**

Run: `npx vitest run test/schemas.test.ts`
Expected: PASS（3 passed）。

- [ ] **Step 5: Commit**

```bash
cd ../.. && git add -A && git commit -m "feat(m0/api): zod request schemas with defaults"
```

---

## Task 4: Repository（任务/素材数据访问）

**Files:**
- Create: `apps/api/src/repository.ts`
- Modify: `apps/api/test/repository.test.ts`（追加用例）

- [ ] **Step 1: 追加失败测试到 `apps/api/test/repository.test.ts`**

在文件末尾追加：
```ts
import * as repo from '../src/repository.js'

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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd apps/api && npx vitest run test/repository.test.ts`
Expected: FAIL（找不到 `../src/repository.js`）。

- [ ] **Step 3: 写 `apps/api/src/repository.ts`**

```ts
import type { DB } from './db.js'
import { newId } from './ids.js'
import type { CreateTaskInput, ReviewInput } from './schemas.js'

export interface TaskSummary {
  id: string
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
    tags: JSON.parse(row.tags ?? '[]'),
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
  const existing = db.prepare('SELECT id FROM ai_clip_assets WHERE id = ?').get(id)
  if (!existing) return undefined
  db.prepare(
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
  return toAssetDto(db.prepare('SELECT * FROM ai_clip_assets WHERE id = ?').get(id))
}
```

- [ ] **Step 4: 运行测试确认通过**

Run: `npx vitest run test/repository.test.ts`
Expected: PASS（全部用例通过）。

- [ ] **Step 5: Commit**

```bash
cd ../.. && git add -A && git commit -m "feat(m0/api): task/asset repository (create/get/list/review)"
```

---

## Task 5: Fastify 服务与入口

**Files:**
- Create: `apps/api/src/server.ts`
- Create: `apps/api/src/index.ts`
- Test: `apps/api/test/api.test.ts`

- [ ] **Step 1: 写失败测试 `apps/api/test/api.test.ts`**

```ts
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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd apps/api && npx vitest run test/api.test.ts`
Expected: FAIL（找不到 `../src/server.js`）。

- [ ] **Step 3: 写 `apps/api/src/server.ts`**

```ts
import Fastify, { type FastifyInstance } from 'fastify'
import fastifyStatic from '@fastify/static'
import { resolve } from 'node:path'
import type { DB } from './db.js'
import { CreateTaskBody, ReviewBody } from './schemas.js'
import * as repo from './repository.js'

export function buildServer(db: DB, storageDir: string): FastifyInstance {
  const app = Fastify({ logger: false })

  app.register(fastifyStatic, { root: resolve(storageDir), prefix: '/storage/' })

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
```

- [ ] **Step 4: 写 `apps/api/src/index.ts`**

```ts
import { mkdirSync } from 'node:fs'
import { dirname } from 'node:path'
import { openDb } from './db.js'
import { buildServer } from './server.js'

const DB_PATH = process.env.DB_PATH ?? './data/agcs.db'
const STORAGE_DIR = process.env.STORAGE_DIR ?? './storage'
const PORT = Number(process.env.API_PORT ?? 8787)

mkdirSync(dirname(DB_PATH), { recursive: true })
mkdirSync(STORAGE_DIR, { recursive: true })

const db = openDb(DB_PATH)
const app = buildServer(db, STORAGE_DIR)

app
  .listen({ port: PORT, host: '0.0.0.0' })
  .then(() => console.log(`AGCS API listening on :${PORT}`))
  .catch((err) => {
    console.error(err)
    process.exit(1)
  })
```

- [ ] **Step 5: 运行测试确认通过**

Run: `npx vitest run`
Expected: PASS（repository / schemas / api 全部通过）。

- [ ] **Step 6: 手动冒烟（可选但建议）**

Run:
```bash
DB_PATH=./data/agcs.db STORAGE_DIR=./storage API_PORT=8787 npm start &
sleep 1
curl -s -X POST localhost:8787/api/ai-growth-clip/tasks -H 'content-type: application/json' \
  -d '{"sourceContentId":"1","sourceContentType":"episode","sourceVideoUrl":"file:///tmp/x.mp4","targetScenarios":["feed"],"targetDurations":[15],"targetAspectRatios":["9:16"],"targetLanguages":["zh-CN"]}'
kill %1
```
Expected: 返回 `{"taskId":"task_..."}`。

- [ ] **Step 7: Commit**

```bash
cd ../.. && git add -A && git commit -m "feat(m0/api): fastify server + routes + entrypoint"
```

---

## Task 6: Worker 配置与 DB 层

**Files:**
- Create: `apps/worker/agcs_worker/config.py`
- Create: `apps/worker/agcs_worker/db.py`
- Test: `apps/worker/tests/conftest.py`, `apps/worker/tests/test_db.py`

- [ ] **Step 1: 写 `apps/worker/tests/conftest.py`**

```python
import os
import sqlite3
import subprocess

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))           # apps/worker/tests
ROOT = os.path.normpath(os.path.join(HERE, "..", "..", "..")) # repo root
SCHEMA = os.path.join(ROOT, "db", "schema.sql")


@pytest.fixture
def conn(tmp_path):
    db_path = str(tmp_path / "t.db")
    c = sqlite3.connect(db_path)
    c.row_factory = sqlite3.Row
    with open(SCHEMA, "r", encoding="utf-8") as f:
        c.executescript(f.read())
    c.commit()
    yield c
    c.close()


@pytest.fixture(scope="session")
def sample_video(tmp_path_factory):
    out = str(tmp_path_factory.mktemp("media") / "sample.mp4")
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=duration=20:size=1280x720:rate=25",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=20",
         "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest", out],
        check=True, capture_output=True,
    )
    return out


def insert_queued_task(conn, source_video_url=""):
    conn.execute(
        "INSERT INTO ai_clip_tasks (id, source_content_id, source_content_type, source_video_url, "
        "tags, target_scenarios, target_durations, target_aspect_ratios, target_languages, clip_count, "
        "status, progress, created_at, updated_at) VALUES "
        "(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("task_t", "12345", "episode", source_video_url, "[]", '["feed"]', "[15]",
         '["9:16"]', '["zh-CN"]', 3, "queued", 0, 1, 1),
    )
    conn.commit()
```

- [ ] **Step 2: 写失败测试 `apps/worker/tests/test_db.py`**

```python
from agcs_worker import db as dbm
from conftest import insert_queued_task  # pytest prepend 模式下 tests/ 在 sys.path，可直接 import conftest


def test_claim_next_task_is_atomic(conn):
    insert_queued_task(conn)
    t = dbm.claim_next_task(conn, "w1")
    assert t is not None
    assert t["status"] == "running"
    # second claim finds nothing queued
    assert dbm.claim_next_task(conn, "w1") is None


def test_mark_failed(conn):
    insert_queued_task(conn)
    t = dbm.claim_next_task(conn, "w1")
    dbm.mark_failed(conn, t["id"], "boom")
    row = conn.execute(
        "SELECT status, error_message FROM ai_clip_tasks WHERE id=?", (t["id"],)
    ).fetchone()
    assert row["status"] == "failed"
    assert row["error_message"] == "boom"


def test_insert_segment_and_asset(conn):
    insert_queued_task(conn)
    dbm.insert_segment(conn, {
        "id": "seg_1", "task_id": "task_t", "source_content_id": "12345",
        "start_ms": 0, "end_ms": 5000, "duration_ms": 5000, "highlight_type": "reversal",
        "score": 0.9, "reason": "r", "summary": "s", "transcript_text": "t",
        "risk_level": "low", "risk_reason": None, "packaging_draft": {"title": "x"},
    })
    dbm.insert_asset(conn, {
        "id": "asset_1", "task_id": "task_t", "segment_id": "seg_1", "source_content_id": "12345",
        "scenario": "feed", "duration": 15, "aspect_ratio": "9:16", "language": "zh-CN",
        "video_url": "/storage/x.mp4", "title": "x", "cover_text": "c",
        "recommendation_text": "rec", "tags": ["a"],
    })
    assert conn.execute("SELECT COUNT(*) c FROM ai_clip_segments").fetchone()["c"] == 1
    assert conn.execute("SELECT COUNT(*) c FROM ai_clip_assets").fetchone()["c"] == 1
```

- [ ] **Step 3: 运行测试确认失败**

Run: `cd apps/worker && python3 -m pytest tests/test_db.py -q`
Expected: FAIL（`ModuleNotFoundError: No module named 'agcs_worker.db'` 或 import 错误）。
（若提示缺 pytest：`python3 -m pip install pytest`。）

- [ ] **Step 4: 写 `apps/worker/agcs_worker/config.py`**

```python
import os
from dataclasses import dataclass


def _load_env_file(path: str = ".env") -> None:
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


@dataclass
class Config:
    db_path: str
    storage_dir: str
    poll_interval_ms: int
    asr_provider: str
    highlight_provider: str
    packaging_provider: str


def load_config() -> Config:
    _load_env_file()
    return Config(
        db_path=os.environ.get("DB_PATH", "./data/agcs.db"),
        storage_dir=os.environ.get("STORAGE_DIR", "./storage"),
        poll_interval_ms=int(os.environ.get("WORKER_POLL_INTERVAL_MS", "1000")),
        asr_provider=os.environ.get("ASR_PROVIDER", "mock"),
        highlight_provider=os.environ.get("HIGHLIGHT_PROVIDER", "mock"),
        packaging_provider=os.environ.get("PACKAGING_PROVIDER", "mock"),
    )
```

- [ ] **Step 5: 写 `apps/worker/agcs_worker/db.py`**

```python
import json
import sqlite3
import time
import uuid


def now_ms() -> int:
    return int(time.time() * 1000)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def claim_next_task(conn: sqlite3.Connection, worker_id: str):
    row = conn.execute(
        "SELECT id FROM ai_clip_tasks WHERE status='queued' ORDER BY created_at ASC LIMIT 1"
    ).fetchone()
    if row is None:
        return None
    cur = conn.execute(
        "UPDATE ai_clip_tasks SET status='running', progress=1, current_step='claimed', updated_at=? "
        "WHERE id=? AND status='queued'",
        (now_ms(), row["id"]),
    )
    conn.commit()
    if cur.rowcount != 1:
        return None  # lost the race to another worker
    return dict(conn.execute("SELECT * FROM ai_clip_tasks WHERE id=?", (row["id"],)).fetchone())


def update_progress(conn, task_id: str, progress: int, current_step: str) -> None:
    conn.execute(
        "UPDATE ai_clip_tasks SET progress=?, current_step=?, updated_at=? WHERE id=?",
        (progress, current_step, now_ms(), task_id),
    )
    conn.commit()


def mark_succeeded(conn, task_id: str) -> None:
    conn.execute(
        "UPDATE ai_clip_tasks SET status='succeeded', progress=100, current_step='done', updated_at=? "
        "WHERE id=?",
        (now_ms(), task_id),
    )
    conn.commit()


def mark_failed(conn, task_id: str, error_message: str) -> None:
    conn.execute(
        "UPDATE ai_clip_tasks SET status='failed', error_message=?, updated_at=? WHERE id=?",
        (error_message[:1000], now_ms(), task_id),
    )
    conn.commit()


def insert_segment(conn, seg: dict) -> None:
    conn.execute(
        "INSERT INTO ai_clip_segments (id, task_id, source_content_id, start_ms, end_ms, duration_ms, "
        "highlight_type, score, reason, summary, transcript_text, risk_level, risk_reason, "
        "packaging_draft, status, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (seg["id"], seg["task_id"], seg["source_content_id"], seg["start_ms"], seg["end_ms"],
         seg["duration_ms"], seg["highlight_type"], seg["score"], seg.get("reason"), seg.get("summary"),
         seg.get("transcript_text"), seg["risk_level"], seg.get("risk_reason"),
         json.dumps(seg.get("packaging_draft"), ensure_ascii=False),
         seg.get("status", "candidate"), now_ms(), now_ms()),
    )
    conn.commit()


def insert_asset(conn, a: dict) -> None:
    conn.execute(
        "INSERT INTO ai_clip_assets (id, task_id, segment_id, source_content_id, scenario, duration, "
        "aspect_ratio, language, video_url, cover_url, subtitle_url, title, cover_text, "
        "recommendation_text, tags, status, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (a["id"], a["task_id"], a["segment_id"], a["source_content_id"], a["scenario"], a["duration"],
         a["aspect_ratio"], a["language"], a["video_url"], a.get("cover_url"), a.get("subtitle_url"),
         a.get("title"), a.get("cover_text"), a.get("recommendation_text"),
         json.dumps(a.get("tags", []), ensure_ascii=False), a.get("status", "pending_review"),
         now_ms(), now_ms()),
    )
    conn.commit()
```

- [ ] **Step 6: 运行测试确认通过**

Run: `python3 -m pytest tests/test_db.py -q`
Expected: PASS（3 passed）。

- [ ] **Step 7: Commit**

```bash
cd ../.. && git add -A && git commit -m "feat(m0/worker): config loader + sqlite db layer (claim/update/insert)"
```

---

## Task 7: ffmpeg 子进程封装

**Files:**
- Create: `apps/worker/agcs_worker/ffmpeg.py`
- Test: `apps/worker/tests/test_ffmpeg.py`

- [ ] **Step 1: 写失败测试 `apps/worker/tests/test_ffmpeg.py`**

```python
import os

from agcs_worker import ffmpeg


def test_probe_duration(sample_video):
    ms = ffmpeg.probe_duration_ms(sample_video)
    assert ms is not None and ms > 15000


def test_probe_missing_returns_none():
    assert ffmpeg.probe_duration_ms("/no/such/file.mp4") is None


def test_cut_clip_vertical(sample_video, tmp_path):
    out = str(tmp_path / "clip.mp4")
    ffmpeg.cut_clip(sample_video, 1000, 5000, "9:16", out)
    assert os.path.exists(out) and os.path.getsize(out) > 0


def test_extract_frame(sample_video, tmp_path):
    out = str(tmp_path / "frame.jpg")
    ffmpeg.extract_frame(sample_video, 1000, out)
    assert os.path.exists(out) and os.path.getsize(out) > 0
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd apps/worker && python3 -m pytest tests/test_ffmpeg.py -q`
Expected: FAIL（`No module named 'agcs_worker.ffmpeg'`）。

- [ ] **Step 3: 写 `apps/worker/agcs_worker/ffmpeg.py`**

```python
import subprocess


class FfmpegError(RuntimeError):
    pass


# 注意：crop 表达式假设输入为横屏（宽 >= 目标比例所需）。M0 样例为 1280x720 横屏，满足。
# 竖屏源后续在真实路径里再补主体检测，详见 02 设计 §4.5。
ASPECT_FILTERS = {
    "9:16": "crop=ih*9/16:ih,scale=720:1280,setsar=1",
    "16:9": "scale=1280:720,setsar=1",
    "1:1": "crop=ih:ih,scale=720:720,setsar=1",
    "4:5": "crop=ih*4/5:ih,scale=720:900,setsar=1",
}


def _run(cmd: list) -> str:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise FfmpegError(f"{cmd[0]} failed ({proc.returncode}): {proc.stderr[-500:]}")
    return proc.stdout


def probe_duration_ms(path: str):
    try:
        out = _run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                    "-of", "default=nw=1:nk=1", path]).strip()
    except FfmpegError:
        return None
    if not out:
        return None
    try:
        return int(float(out) * 1000)
    except ValueError:
        return None


def cut_clip(src: str, start_ms: int, dur_ms: int, aspect_ratio: str, out_path: str) -> None:
    vf = ASPECT_FILTERS.get(aspect_ratio, ASPECT_FILTERS["9:16"])
    _run(["ffmpeg", "-y", "-ss", f"{start_ms / 1000:.3f}", "-i", src,
          "-t", f"{dur_ms / 1000:.3f}", "-vf", vf,
          "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac",
          "-movflags", "+faststart", out_path])


def extract_frame(src: str, at_ms: int, out_path: str) -> None:
    _run(["ffmpeg", "-y", "-ss", f"{at_ms / 1000:.3f}", "-i", src,
          "-frames:v", "1", "-q:v", "3", out_path])
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python3 -m pytest tests/test_ffmpeg.py -q`
Expected: PASS（4 passed；首次会用 ffmpeg 生成样例视频，约几秒）。

- [ ] **Step 5: Commit**

```bash
cd ../.. && git add -A && git commit -m "feat(m0/worker): ffmpeg/ffprobe wrappers (probe/cut/cover, 9:16 reframe)"
```

---

## Task 8: 适配器（base 协议 + mock 实现）

**Files:**
- Create: `apps/worker/agcs_worker/providers/base.py`
- Create: `apps/worker/agcs_worker/providers/mock.py`
- Test: `apps/worker/tests/test_providers.py`

- [ ] **Step 1: 写失败测试 `apps/worker/tests/test_providers.py`**

```python
from agcs_worker.providers.mock import (
    MockAsrProvider, MockHighlightProvider, MockPackagingProvider,
)


def test_mock_asr_returns_segments_and_vtt():
    t = MockAsrProvider().transcribe("", 10000)
    assert len(t.segments) >= 1
    assert t.vtt.startswith("WEBVTT")


def test_mock_highlight_respects_clip_count():
    segs = MockHighlightProvider().analyze(
        {"duration_ms": 20000, "clip_count": 3, "target_scenarios": ["feed", "membership"]}
    )
    assert len(segs) == 3
    assert all(s.end_ms > s.start_ms for s in segs)
    assert all(s.recommended_scenario in ("feed", "membership") for s in segs)


def test_mock_packaging_builds_copy():
    p = MockPackagingProvider().generate({"index": 0, "tags": ["逆袭"]})
    assert p.title
    assert "逆袭" in p.tags
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd apps/worker && python3 -m pytest tests/test_providers.py -q`
Expected: FAIL（`No module named 'agcs_worker.providers.mock'`）。

- [ ] **Step 3: 写 `apps/worker/agcs_worker/providers/base.py`**

```python
from dataclasses import dataclass, field
from typing import List, Optional, Protocol


@dataclass
class TranscriptSegment:
    start_ms: int
    end_ms: int
    text: str


@dataclass
class Transcript:
    segments: List[TranscriptSegment]
    vtt: str


@dataclass
class HighlightSegment:
    start_ms: int
    end_ms: int
    highlight_type: str
    score: float
    reason: str
    summary: str
    transcript_text: str
    risk_level: str
    recommended_scenario: str
    risk_reason: Optional[str] = None


@dataclass
class Packaging:
    title: str
    cover_text: str
    recommendation_text: str
    tags: List[str] = field(default_factory=list)


class AsrProvider(Protocol):
    def transcribe(self, audio_path: str, duration_ms: int) -> Transcript: ...


class HighlightProvider(Protocol):
    def analyze(self, ctx: dict) -> List[HighlightSegment]: ...


class PackagingProvider(Protocol):
    def generate(self, ctx: dict) -> Packaging: ...
```

- [ ] **Step 4: 写 `apps/worker/agcs_worker/providers/mock.py`**

```python
from typing import List

from .base import (
    Transcript, TranscriptSegment, HighlightSegment, Packaging,
)


class MockAsrProvider:
    LINES = [
        "你不过是个没人要的女人。",
        "等等，她竟然是董事长的女儿。",
        "全场瞬间安静了。",
        "这一次，轮到你后悔了。",
        "故事才刚刚开始。",
    ]

    def transcribe(self, audio_path: str, duration_ms: int) -> Transcript:
        total = duration_ms or 10000
        step = max(2000, total // 5)
        segs: List[TranscriptSegment] = []
        t = 0
        i = 0
        while t < total and i < len(self.LINES):
            segs.append(TranscriptSegment(start_ms=t, end_ms=min(t + step, total), text=self.LINES[i]))
            t += step
            i += 1
        vtt = "WEBVTT\n\n" + "\n\n".join(f"{s.start_ms} --> {s.end_ms}\n{s.text}" for s in segs)
        return Transcript(segments=segs, vtt=vtt)


class MockHighlightProvider:
    TYPES = ["reversal", "conflict", "emotion", "suspense", "funny"]

    def analyze(self, ctx: dict) -> List[HighlightSegment]:
        duration_ms = ctx.get("duration_ms") or 10000
        clip_count = ctx.get("clip_count", 3)
        scenarios = ctx.get("target_scenarios") or ["feed"]
        win = max(3000, duration_ms // (clip_count + 1))
        out: List[HighlightSegment] = []
        for i in range(clip_count):
            start = min(i * win, max(0, duration_ms - win))
            end = min(start + win, duration_ms)
            out.append(HighlightSegment(
                start_ms=start, end_ms=end, highlight_type=self.TYPES[i % len(self.TYPES)],
                score=round(0.9 - i * 0.05, 2),
                reason="mock：信号缺失，基于占位规则选取（详见 02 设计的多信号方案）",
                summary=f"高光片段 {i + 1}", transcript_text="（mock 字幕摘要）",
                risk_level="low", recommended_scenario=scenarios[i % len(scenarios)],
            ))
        return out


class MockPackagingProvider:
    TITLES = ["退婚当天，她身份曝光", "全场后悔的一刻", "她的反击开始了"]

    def generate(self, ctx: dict) -> Packaging:
        idx = ctx.get("index", 0)
        tags = ctx.get("tags") or ["逆袭", "反转"]
        return Packaging(
            title=self.TITLES[idx % len(self.TITLES)],
            cover_text="全场后悔",
            recommendation_text="强反转开局，适合推荐流首屏测试。",
            tags=tags,
        )
```

- [ ] **Step 5: 运行测试确认通过**

Run: `python3 -m pytest tests/test_providers.py -q`
Expected: PASS（3 passed）。

- [ ] **Step 6: Commit**

```bash
cd ../.. && git add -A && git commit -m "feat(m0/worker): provider protocols + mock asr/highlight/packaging"
```

---

## Task 9: 流水线编排

**Files:**
- Create: `apps/worker/agcs_worker/pipeline.py`
- Test: `apps/worker/tests/test_pipeline.py`

- [ ] **Step 1: 写失败测试 `apps/worker/tests/test_pipeline.py`**

```python
from agcs_worker import db as dbm
from agcs_worker.config import Config
from agcs_worker.pipeline import run_task


def _cfg(tmp_path):
    return Config(db_path="", storage_dir=str(tmp_path / "storage"),
                  poll_interval_ms=1000, asr_provider="mock",
                  highlight_provider="mock", packaging_provider="mock")


def _insert_running_task(conn, source_video_url):
    conn.execute(
        "INSERT INTO ai_clip_tasks (id, source_content_id, source_content_type, source_video_url, "
        "tags, target_scenarios, target_durations, target_aspect_ratios, target_languages, clip_count, "
        "status, progress, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("task_p", "12345", "episode", source_video_url, "[]", '["feed"]', "[15]",
         '["9:16"]', '["zh-CN"]', 3, "running", 1, 1, 1),
    )
    conn.commit()
    return dict(conn.execute("SELECT * FROM ai_clip_tasks WHERE id='task_p'").fetchone())


def test_run_task_with_real_video(conn, sample_video, tmp_path):
    task = _insert_running_task(conn, f"file://{sample_video}")
    run_task(conn, _cfg(tmp_path), task)
    segs = conn.execute("SELECT * FROM ai_clip_segments WHERE task_id='task_p'").fetchall()
    assets = conn.execute("SELECT * FROM ai_clip_assets WHERE task_id='task_p'").fetchall()
    assert len(segs) == 3
    assert len(assets) == 3  # 3 segments × 1 duration × 1 aspect_ratio
    status = conn.execute("SELECT status FROM ai_clip_tasks WHERE id='task_p'").fetchone()["status"]
    assert status == "succeeded"
    # 真实 ffmpeg 产出非空 mp4：video_url 形如 /storage/<taskId>/clips/<assetId>.mp4
    import os
    rel = assets[0]["video_url"].replace("/storage/", "", 1)
    clip_path = os.path.join(str(tmp_path / "storage"), rel)
    assert os.path.exists(clip_path) and os.path.getsize(clip_path) > 0


def test_run_task_stub_without_video(conn, tmp_path):
    task = _insert_running_task(conn, "")
    run_task(conn, _cfg(tmp_path), task)
    status = conn.execute("SELECT status FROM ai_clip_tasks WHERE id='task_p'").fetchone()["status"]
    assert status == "succeeded"
    assert conn.execute("SELECT COUNT(*) c FROM ai_clip_assets").fetchone()["c"] == 3
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd apps/worker && python3 -m pytest tests/test_pipeline.py -q`
Expected: FAIL（`No module named 'agcs_worker.pipeline'`）。

- [ ] **Step 3: 写 `apps/worker/agcs_worker/pipeline.py`**

```python
import json
import os

from . import db as dbm
from . import ffmpeg
from .config import Config
from .providers.mock import (
    MockAsrProvider, MockHighlightProvider, MockPackagingProvider,
)


def get_providers(config: Config):
    # M0 仅支持 mock；真实 provider 在后续里程碑接入
    return MockAsrProvider(), MockHighlightProvider(), MockPackagingProvider()


def _local_path_from_url(url: str):
    if not url:
        return None
    if url.startswith("file://"):
        return url[len("file://"):]
    if os.path.exists(url):
        return url
    return None


def run_task(conn, config: Config, task: dict) -> None:
    task_id = task["id"]
    asr, highlight, packaging = get_providers(config)

    task_dir = os.path.join(config.storage_dir, task_id)
    os.makedirs(os.path.join(task_dir, "clips"), exist_ok=True)
    os.makedirs(os.path.join(task_dir, "covers"), exist_ok=True)

    src = _local_path_from_url(task.get("source_video_url", ""))

    # prepare_video
    dbm.update_progress(conn, task_id, 5, "prepare_video")
    duration_ms = ffmpeg.probe_duration_ms(src) if src else None
    if not duration_ms:
        duration_ms = 20000

    # transcribe_audio (mock)
    dbm.update_progress(conn, task_id, 20, "transcribe_audio")
    transcript = asr.transcribe(src or "", duration_ms)
    with open(os.path.join(task_dir, "transcript.json"), "w", encoding="utf-8") as f:
        json.dump([s.__dict__ for s in transcript.segments], f, ensure_ascii=False)
    with open(os.path.join(task_dir, "zh-CN.vtt"), "w", encoding="utf-8") as f:
        f.write(transcript.vtt)

    # detect_scenes (mock; uniform from transcript)
    dbm.update_progress(conn, task_id, 35, "detect_scenes")
    scenes = [{"start_ms": s.start_ms, "end_ms": s.end_ms} for s in transcript.segments]
    with open(os.path.join(task_dir, "scenes.json"), "w", encoding="utf-8") as f:
        json.dump(scenes, f, ensure_ascii=False)

    # analyze_highlights (mock)
    dbm.update_progress(conn, task_id, 50, "analyze_highlights")
    target_scenarios = json.loads(task.get("target_scenarios") or '["feed"]')
    target_durations = json.loads(task.get("target_durations") or "[15]")
    target_aspect_ratios = json.loads(task.get("target_aspect_ratios") or '["9:16"]')
    target_languages = json.loads(task.get("target_languages") or '["zh-CN"]')
    tags = json.loads(task.get("tags") or "[]")
    highlights = highlight.analyze({
        "duration_ms": duration_ms,
        "clip_count": task.get("clip_count", 3),
        "target_scenarios": target_scenarios,
    })

    # render + cover + packaging + persist
    dbm.update_progress(conn, task_id, 70, "render_clips")
    for idx, seg in enumerate(highlights):
        seg_id = dbm.new_id("segment")
        pack = packaging.generate({"index": idx, "tags": tags})
        dbm.insert_segment(conn, {
            "id": seg_id, "task_id": task_id, "source_content_id": task["source_content_id"],
            "start_ms": seg.start_ms, "end_ms": seg.end_ms,
            "duration_ms": seg.end_ms - seg.start_ms, "highlight_type": seg.highlight_type,
            "score": seg.score, "reason": seg.reason, "summary": seg.summary,
            "transcript_text": seg.transcript_text, "risk_level": seg.risk_level,
            "risk_reason": seg.risk_reason,
            "packaging_draft": {
                "title": pack.title, "cover_text": pack.cover_text,
                "recommendation_text": pack.recommendation_text, "tags": pack.tags,
            },
            "status": "candidate",
        })

        cover_url = None
        if src:
            cover_path = os.path.join(task_dir, "covers", f"{seg_id}.jpg")
            try:
                ffmpeg.extract_frame(src, seg.start_ms + 500, cover_path)
                cover_url = f"/storage/{task_id}/covers/{seg_id}.jpg"
            except ffmpeg.FfmpegError:
                cover_url = None

        for duration in target_durations:
            for ar in target_aspect_ratios:
                asset_id = dbm.new_id("asset")
                rel_video = f"/storage/{task_id}/clips/{asset_id}.mp4"
                out_path = os.path.join(task_dir, "clips", f"{asset_id}.mp4")
                if src:
                    ffmpeg.cut_clip(src, seg.start_ms, duration * 1000, ar, out_path)
                else:
                    with open(out_path, "wb") as f:  # stub: 占位空文件
                        f.write(b"")
                dbm.insert_asset(conn, {
                    "id": asset_id, "task_id": task_id, "segment_id": seg_id,
                    "source_content_id": task["source_content_id"],
                    "scenario": seg.recommended_scenario, "duration": duration, "aspect_ratio": ar,
                    "language": target_languages[0], "video_url": rel_video, "cover_url": cover_url,
                    "subtitle_url": f"/storage/{task_id}/zh-CN.vtt",
                    "title": pack.title, "cover_text": pack.cover_text,
                    "recommendation_text": pack.recommendation_text, "tags": pack.tags,
                    "status": "pending_review",
                })

    # quality_check (basic; M0 仅占位推进)
    dbm.update_progress(conn, task_id, 95, "quality_check")

    dbm.mark_succeeded(conn, task_id)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python3 -m pytest tests/test_pipeline.py -q`
Expected: PASS（2 passed）。

- [ ] **Step 5: Commit**

```bash
cd ../.. && git add -A && git commit -m "feat(m0/worker): pipeline orchestration (mock + real ffmpeg render/cover)"
```

---

## Task 10: Worker 主循环

**Files:**
- Create: `apps/worker/agcs_worker/main.py`
- Test: `apps/worker/tests/test_main.py`

- [ ] **Step 1: 写失败测试 `apps/worker/tests/test_main.py`**

```python
from agcs_worker.config import Config
from agcs_worker.main import process_once
from conftest import insert_queued_task  # pytest prepend 模式下 tests/ 在 sys.path


def _cfg(tmp_path):
    return Config(db_path="", storage_dir=str(tmp_path / "storage"),
                  poll_interval_ms=1000, asr_provider="mock",
                  highlight_provider="mock", packaging_provider="mock")


def test_process_once_handles_one_then_empty(conn, tmp_path):
    insert_queued_task(conn, source_video_url="")  # stub 路径，无需视频
    assert process_once(conn, _cfg(tmp_path)) is True
    status = conn.execute("SELECT status FROM ai_clip_tasks WHERE id='task_t'").fetchone()["status"]
    assert status == "succeeded"
    # 没有更多 queued 任务
    assert process_once(conn, _cfg(tmp_path)) is False


def test_process_once_marks_failed_on_error(conn, tmp_path, monkeypatch):
    insert_queued_task(conn, source_video_url="")
    import agcs_worker.main as m
    monkeypatch.setattr(m, "run_task", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    assert process_once(conn, _cfg(tmp_path)) is True
    row = conn.execute("SELECT status, error_message FROM ai_clip_tasks WHERE id='task_t'").fetchone()
    assert row["status"] == "failed"
    assert "boom" in row["error_message"]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd apps/worker && python3 -m pytest tests/test_main.py -q`
Expected: FAIL（`No module named 'agcs_worker.main'`）。

- [ ] **Step 3: 写 `apps/worker/agcs_worker/main.py`**

```python
import argparse
import sys
import time

from . import db as dbm
from .config import load_config
from .pipeline import run_task


def process_once(conn, config) -> bool:
    task = dbm.claim_next_task(conn, worker_id="worker-1")
    if task is None:
        return False
    try:
        run_task(conn, config, task)
    except Exception as e:  # noqa: BLE001 - 顶层兜底，任务级失败不应中断 worker
        dbm.mark_failed(conn, task["id"], f"{type(e).__name__}: {e}")
    return True


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="AGCS worker")
    parser.add_argument("--once", action="store_true", help="process one task then exit")
    args = parser.parse_args(argv)

    config = load_config()
    conn = dbm.connect(config.db_path)

    if args.once:
        return 0 if process_once(conn, config) else 1

    while True:
        if not process_once(conn, config):
            time.sleep(config.poll_interval_ms / 1000)


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python3 -m pytest tests/test_main.py -q`
Expected: PASS（2 passed）。

- [ ] **Step 5: 运行 worker 全量测试**

Run: `python3 -m pytest -q`
Expected: PASS（db/ffmpeg/providers/pipeline/main 全部通过）。

- [ ] **Step 6: Commit**

```bash
cd ../.. && git add -A && git commit -m "feat(m0/worker): poll loop + --once entrypoint"
```

---

## Task 11: 端到端冒烟与运行文档

**Files:**
- Create: `scripts/smoke.sh`
- Modify: `README.md`

- [ ] **Step 1: 写 `scripts/smoke.sh`**

```bash
#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export DB_PATH="$ROOT/data/agcs.db"
export STORAGE_DIR="$ROOT/storage"
export API_PORT="${API_PORT:-8787}"
mkdir -p "$ROOT/data" "$ROOT/storage"

# 1) 生成一个本地样例视频
SAMPLE="$ROOT/storage/sample.mp4"
if [ ! -f "$SAMPLE" ]; then
  ffmpeg -y -f lavfi -i testsrc=duration=20:size=1280x720:rate=25 \
    -f lavfi -i sine=frequency=440:duration=20 \
    -c:v libx264 -preset ultrafast -c:a aac -shortest "$SAMPLE" >/dev/null 2>&1
fi

# 2) 起 API
( cd "$ROOT/apps/api" && npm start >/tmp/agcs-api.log 2>&1 & echo $! > /tmp/agcs-api.pid )
sleep 1.5

# 3) 建任务
RESP=$(curl -s -X POST "localhost:$API_PORT/api/ai-growth-clip/tasks" \
  -H 'content-type: application/json' \
  -d "{\"sourceContentId\":\"1\",\"sourceContentType\":\"episode\",\"sourceVideoUrl\":\"file://$SAMPLE\",\"title\":\"样例\",\"targetScenarios\":[\"feed\"],\"targetDurations\":[15,30],\"targetAspectRatios\":[\"9:16\"],\"targetLanguages\":[\"zh-CN\"],\"clipCount\":3}")
echo "create: $RESP"
TASK_ID=$(echo "$RESP" | sed -E 's/.*"taskId":"([^"]+)".*/\1/')

# 4) 跑一轮 worker
( cd "$ROOT/apps/worker" && DB_PATH="$DB_PATH" STORAGE_DIR="$STORAGE_DIR" python3 -m agcs_worker.main --once )

# 5) 查状态与产物
echo "task: $(curl -s localhost:$API_PORT/api/ai-growth-clip/tasks/$TASK_ID)"
echo "assets: $(curl -s localhost:$API_PORT/api/ai-growth-clip/tasks/$TASK_ID/assets)"

# 6) 收尾
kill "$(cat /tmp/agcs-api.pid)" 2>/dev/null || true
```

- [ ] **Step 2: 赋可执行并运行冒烟**

Run:
```bash
chmod +x scripts/smoke.sh && ./scripts/smoke.sh
```
Expected: `create:` 行返回 taskId；`task:` 行 status 为 `succeeded`、progress 100；`assets:` 行包含 6 个素材（3 segments × 2 durations × 1 aspect_ratio），`video_url` 指向 `/storage/<taskId>/clips/*.mp4`。

- [ ] **Step 3: 写运行文档到 `README.md`**

```markdown
# AIGrowthClipStudio

AI Growth Clip Studio — 把已有视频内容自动拆成推荐流/广告/会员/社媒的多版本短视频素材。
设计文档见 [docs/](docs/)。当前已实现 **M0 可运行骨架**。

## 运行环境

- Node ≥ 22（用内置 `node:sqlite`，本仓库用 24）
- Python ≥ 3.9
- ffmpeg / ffprobe 在 PATH 中

## 快速开始

```bash
# 1) 安装 API 依赖
cd apps/api && npm install && cd ../..

# 2) 一键端到端冒烟（建任务 → 跑 worker → 查产物）
./scripts/smoke.sh
```

## 分开运行

```bash
# API（终端 A）
cd apps/api && npm start            # 监听 :8787

# Worker（终端 B，轮询模式）
cd apps/worker && python3 -m agcs_worker.main
# 或处理一条后退出：python3 -m agcs_worker.main --once
```

## 测试

```bash
cd apps/api && npm test                 # vitest
cd apps/worker && python3 -m pytest -q   # pytest
```

## M0 范围与后续

M0 为骨架：流水线中 ASR/高光/文案为 mock 适配器，`render_clips`/`select_cover` 为真实 ffmpeg。
后续 M1（faster-whisper）、M2（LLM + 多信号高光 + 评测集）、M3（LLM 文案 + 视觉封面）、M4（admin 审核台）见
[docs/03-mvp-implementation-plan.md](docs/03-mvp-implementation-plan.md)。
```

- [ ] **Step 4: Commit**

```bash
git add -A && git commit -m "feat(m0): end-to-end smoke script + run docs"
```

---

## Self-Review（计划自检结论）

- **Spec coverage：** 目标 1–5（建任务/查状态/worker 消费/产物与审核/克隆即跑）→ Task 5/6/9/11；数据层与 schema → Task 1/2/4；流水线 8 步与适配器 → Task 7/8/9；竖屏与素材基数 → Task 7（filter）+ Task 9（duration×aspectRatio 循环，测试断言 3 个素材）；错误处理 → Task 6（mark_failed）+ Task 10（顶层兜底测试）。无未覆盖项。
- **Placeholder scan：** 无 TBD/“稍后实现”；每个代码步骤含完整代码与确切命令、期望输出。
- **Type consistency：** `openDb`/`newId`/`createTask`/`getTask`/`listTasks`/`getAssetsByTask`/`reviewAsset`（TS）与 `connect`/`claim_next_task`/`update_progress`/`mark_succeeded`/`mark_failed`/`insert_segment`/`insert_asset`/`run_task`/`process_once`（Py）在各任务间签名一致；DB 列名与 `db/schema.sql` 一致；mock provider 的 `recommended_scenario`/`packaging_draft` 字段在 pipeline 与 db 层一致。

---

## Execution Handoff

计划已保存。两种执行方式：

1. **Subagent-Driven（推荐）** — 每个 Task 派一个全新 subagent 实现、任务间审查、迭代快。
2. **Inline Execution** — 在当前会话内用 executing-plans 批量执行、带检查点审查。
