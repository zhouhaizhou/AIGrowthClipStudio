# M4 — 增长素材审核台 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`).

**Goal:** 一个自包含 Web 审核台（由现有 Fastify API 托管单文件 `web/index.html`），浏览器里建任务、看切片视频、审核通过/驳回。复用既有 REST 接口，无需 key。

**Architecture:** `buildServer(db, storageDir, webDir?)` 用第二个 `@fastify/static`（root=webDir, prefix `/`, decorateReply:false）托管控制台；`/api/*` 显式路由优先，`/storage/*` 独立 prefix，互不遮蔽。控制台是零依赖单文件（内联 CSS+原生 JS fetch）。TaskSummary 增 sourceContentId/title 让列表有意义。

**对应 spec：** [docs/superpowers/specs/2026-06-04-m4-review-console-design.md](../specs/2026-06-04-m4-review-console-design.md)

**前置：** M0–M3 在 main（HEAD 882d864）。API 测试从 `apps/api` 跑 `npx vitest`。

---

## Task 1: TaskSummary 增 sourceContentId/title

**Files:** Modify `apps/api/src/repository.ts`; Test `apps/api/test/repository.test.ts`

- [ ] **Step 1: APPEND failing test to `apps/api/test/repository.test.ts`**（文件末尾，沿用已有 `openDb`/`repo`/`baseInput`）

```ts
describe('task summary fields', () => {
  it('includes sourceContentId and title', () => {
    const db = openDb(':memory:')
    repo.createTask(db, { ...(baseInput as any), title: 'T-标题' })
    const t = repo.listTasks(db, {})[0] as any
    expect(t.sourceContentId).toBe('12345')
    expect(t.title).toBe('T-标题')
  })
})
```

- [ ] **Step 2: 运行确认失败**

Run: `cd apps/api && npx vitest run test/repository.test.ts`
Expected: FAIL（`expect(t.sourceContentId)` undefined）。

- [ ] **Step 3: 改 `apps/api/src/repository.ts`** —— `TaskSummary` 接口加两字段，`toTaskSummary` 映射两列：
```ts
export interface TaskSummary {
  id: string
  sourceContentId: string
  title: string | null
  status: string
  progress: number
  currentStep: string | null
  errorMessage: string | null
}
```
```ts
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
```

- [ ] **Step 4: 运行确认通过 + 全量 API 套件**

Run: `npx vitest run` → 全绿（既有 status/progress 断言不受影响）。

- [ ] **Step 5: Commit**

```bash
cd /Users/jc/codesOther/AIGrowthClipStudio && git add -A && git commit -m "feat(m4/api): task summary includes sourceContentId + title

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: API 托管控制台静态页

**Files:** Modify `apps/api/src/server.ts`, `apps/api/src/index.ts`; Create `apps/api/web/index.html`（占位，Task 3 替换）; Test `apps/api/test/console.test.ts`

- [ ] **Step 1: 写失败测试 `apps/api/test/console.test.ts`**

```ts
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
})
```

- [ ] **Step 2: 运行确认失败**

Run: `cd apps/api && npx vitest run test/console.test.ts`
Expected: FAIL（`buildServer` 只接受 2 参 / GET / 非 200）。

- [ ] **Step 3: 改 `apps/api/src/server.ts`** —— 顶部 import 加路径解析，buildServer 增 webDir 参 + 第二个 static：
```ts
import Fastify, { type FastifyInstance } from 'fastify'
import fastifyStatic from '@fastify/static'
import { resolve, dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import type { DB } from './db.js'
import { CreateTaskBody, ReviewBody } from './schemas.js'
import * as repo from './repository.js'

const here = dirname(fileURLToPath(import.meta.url))
const DEFAULT_WEB_DIR = join(here, '../web')

export function buildServer(db: DB, storageDir: string, webDir: string = DEFAULT_WEB_DIR): FastifyInstance {
  const app = Fastify({ logger: false })

  app.register(fastifyStatic, { root: resolve(storageDir), prefix: '/storage/' })
  app.register(fastifyStatic, { root: resolve(webDir), prefix: '/', decorateReply: false })

  // ...（其余 5 个 /api 路由保持不变）...

  return app
}
```
（保留现有 5 个 `/api/ai-growth-clip/...` 路由原样；仅新增第二个 static 注册与 webDir 参数。）

- [ ] **Step 4: 改 `apps/api/src/index.ts`** —— 传 webDir（默认即 DEFAULT_WEB_DIR，无需改动 buildServer 调用即可，但显式传更清晰）。可保持 `buildServer(db, STORAGE_DIR)` 不变（webDir 走默认）。**无需改 index.ts**，跳过。

- [ ] **Step 5: 写占位 `apps/api/web/index.html`**
```html
<!doctype html>
<meta charset="utf-8">
<title>AI Growth Clip Studio — 审核台</title>
<body>审核台占位（Task 3 替换为完整控制台）</body>
```

- [ ] **Step 6: 运行确认通过 + 全量**

Run: `npx vitest run test/console.test.ts` → 2 passed。
Run: `npx vitest run` → 全量 API 套件绿（含 console + repository + api + schemas）。

- [ ] **Step 7: Commit**

```bash
cd /Users/jc/codesOther/AIGrowthClipStudio && git add -A && git commit -m "feat(m4/api): serve review console static page at / (alongside /api and /storage)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: 完整控制台 index.html

**Files:** Modify `apps/api/web/index.html`（替换占位为完整控制台）

- [ ] **Step 1: 用以下完整内容替换 `apps/api/web/index.html`**

```html
<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AI Growth Clip Studio — 审核台</title>
<style>
  :root { --bg:#0f1115; --card:#1a1d24; --line:#2a2f3a; --fg:#e6e8ee; --mut:#9aa3b2; --acc:#4f8cff; --ok:#2ecc71; --bad:#e74c3c; }
  * { box-sizing:border-box; } body { margin:0; font:14px/1.5 system-ui,-apple-system,"PingFang SC",sans-serif; background:var(--bg); color:var(--fg); }
  header { padding:16px 20px; border-bottom:1px solid var(--line); display:flex; align-items:baseline; gap:12px; }
  header h1 { font-size:18px; margin:0; } header span { color:var(--mut); font-size:12px; }
  main { padding:20px; max-width:1200px; margin:0 auto; } section { margin-bottom:24px; }
  h2 { font-size:13px; color:var(--mut); text-transform:uppercase; letter-spacing:.05em; margin:0 0 10px; }
  .row { display:flex; flex-wrap:wrap; gap:10px; align-items:center; justify-content:space-between; }
  .card { background:var(--card); border:1px solid var(--line); border-radius:10px; padding:14px; }
  label { display:block; font-size:12px; color:var(--mut); margin:8px 0 4px; }
  input,textarea { width:100%; background:#0c0e12; border:1px solid var(--line); color:var(--fg); border-radius:6px; padding:7px 9px; font:inherit; }
  textarea { resize:vertical; min-height:38px; }
  button { background:var(--acc); color:#fff; border:0; border-radius:6px; padding:8px 14px; cursor:pointer; font-weight:600; }
  button.ghost { background:transparent; border:1px solid var(--line); color:var(--fg); }
  button.ok { background:var(--ok); } button.bad { background:var(--bad); }
  .grid3 { display:grid; grid-template-columns:repeat(auto-fill,minmax(180px,1fr)); gap:8px; }
  .checks { display:flex; flex-wrap:wrap; gap:12px; } .checks label { display:flex; align-items:center; gap:5px; margin:0; color:var(--fg); }
  table { width:100%; border-collapse:collapse; } th,td { text-align:left; padding:7px 8px; border-bottom:1px solid var(--line); font-size:13px; }
  tr.task { cursor:pointer; } tr.sel { background:#222838; }
  .badge { display:inline-block; padding:2px 8px; border-radius:99px; font-size:11px; font-weight:600; }
  .b-queued{background:#33405a;color:#cbd6ee}.b-running{background:#3a3357;color:#d8cbf0}.b-succeeded{background:#1f4a35;color:#9ff0c2}.b-failed{background:#4a2222;color:#f0a0a0}
  .b-pending_review{background:#4a4322;color:#f0e0a0}.b-approved{background:#1f4a35;color:#9ff0c2}.b-rejected{background:#4a2222;color:#f0a0a0}
  .assets { display:grid; grid-template-columns:repeat(auto-fill,minmax(280px,1fr)); gap:14px; }
  .asset video { width:100%; border-radius:8px; background:#000; aspect-ratio:9/16; max-height:420px; }
  .asset .meta { color:var(--mut); font-size:12px; margin:6px 0; } .tag { display:inline-block; background:#222838; border-radius:99px; padding:1px 8px; margin:2px 4px 0 0; font-size:11px; }
  #toast { position:fixed; top:14px; right:14px; max-width:360px; z-index:9; } .toast { background:var(--card); border:1px solid var(--line); border-left:3px solid var(--acc); border-radius:8px; padding:10px 12px; margin-bottom:8px; font-size:13px; } .toast.err { border-left-color:var(--bad); }
  details summary { cursor:pointer; color:var(--mut); } .muted { color:var(--mut); }
</style>
</head>
<body>
<header><h1>AI Growth Clip Studio</h1><span>增长素材审核台</span></header>
<main>
  <section class="card"><details><summary>＋ 创建任务</summary><div style="margin-top:12px">
    <div class="grid3">
      <div><label>sourceContentId</label><input id="f-cid" value="demo-1"></div>
      <div><label>sourceVideoUrl（支持 file://）</label><input id="f-url" placeholder="file:///abs/sample.mp4"></div>
      <div><label>title</label><input id="f-title" value="她被退婚后身份曝光"></div>
      <div><label>category</label><input id="f-cat" value="短剧"></div>
      <div><label>tags（逗号分隔）</label><input id="f-tags" value="逆袭,豪门,复仇"></div>
      <div><label>clipCount</label><input id="f-count" type="number" value="3" min="1"></div>
    </div>
    <label>targetScenarios</label><div class="checks" id="f-scen"></div>
    <label>targetDurations</label><div class="checks" id="f-dur"></div>
    <label>targetAspectRatios</label><div class="checks" id="f-ar"></div>
    <div style="margin-top:12px"><button id="btn-create">创建任务</button></div>
  </div></details></section>

  <section><div class="row"><h2>任务</h2><button class="ghost" id="btn-refresh">刷新</button></div>
    <div class="card"><table><thead><tr><th>id</th><th>title</th><th>状态</th><th>进度</th></tr></thead><tbody id="tasks"></tbody></table></div></section>

  <section><h2 id="assets-h">素材</h2><div class="assets" id="assets"><span class="muted">选择左侧任务查看素材</span></div></section>
</main>
<div id="toast"></div>
<script>
const API='/api/ai-growth-clip', SCEN=['feed','detail','ad','membership','social'], DUR=['15','30','60'], AR=['9:16','16:9','1:1','4:5'];
let selectedTask=null;
const $=id=>document.getElementById(id);
function esc(s){return String(s==null?'':s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));}
function toast(m,err){const d=document.createElement('div');d.className='toast'+(err?' err':'');d.textContent=m;$('toast').appendChild(d);setTimeout(()=>d.remove(),4000);}
async function api(path,opts){const r=await fetch(API+path,opts);const t=await r.text();const d=t?JSON.parse(t):null;if(!r.ok)throw new Error((d&&(d.error||JSON.stringify(d)))||('HTTP '+r.status));return d;}
function checks(el,vals,preset){el.innerHTML='';vals.forEach(v=>{const l=document.createElement('label');l.innerHTML='<input type="checkbox" value="'+v+'"'+(preset.includes(v)?' checked':'')+'> '+v;el.appendChild(l);});}
function picked(el){return [...el.querySelectorAll('input:checked')].map(i=>i.value);}
function badge(s){return '<span class="badge b-'+esc(s)+'">'+esc(s)+'</span>';}
checks($('f-scen'),SCEN,['feed']);checks($('f-dur'),DUR,['15','30']);checks($('f-ar'),AR,['9:16']);
$('btn-create').onclick=async()=>{try{const body={sourceContentId:$('f-cid').value.trim(),sourceContentType:'episode',sourceVideoUrl:$('f-url').value.trim(),title:$('f-title').value.trim(),category:$('f-cat').value.trim(),tags:$('f-tags').value.split(',').map(s=>s.trim()).filter(Boolean),targetScenarios:picked($('f-scen')),targetDurations:picked($('f-dur')).map(Number),targetAspectRatios:picked($('f-ar')),clipCount:Number($('f-count').value)};const r=await api('/tasks',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(body)});toast('已创建任务 '+r.taskId+'（worker 处理后点刷新）');loadTasks();}catch(e){toast('创建失败：'+e.message,true);}};
$('btn-refresh').onclick=loadTasks;
async function loadTasks(){try{const r=await api('/tasks');const tb=$('tasks');tb.innerHTML='';if(!r.list.length){tb.innerHTML='<tr><td colspan="4" class="muted">暂无任务</td></tr>';return;}r.list.forEach(t=>{const tr=document.createElement('tr');tr.className='task'+(selectedTask===t.id?' sel':'');tr.innerHTML='<td>'+esc(t.id.slice(0,16))+'…</td><td>'+(t.title?esc(t.title):'<span class=muted>—</span>')+'</td><td>'+badge(t.status)+'</td><td>'+(t.progress||0)+'%</td>';tr.onclick=()=>loadAssets(t.id);tb.appendChild(tr);});}catch(e){toast('载入任务失败：'+e.message,true);}}
async function loadAssets(id){selectedTask=id;loadTasks();$('assets-h').textContent='素材 · '+id.slice(0,16)+'…';const box=$('assets');box.innerHTML='<span class="muted">载入中…</span>';try{const r=await api('/tasks/'+id+'/assets');box.innerHTML='';if(!r.list.length){box.innerHTML='<span class="muted">暂无素材（确认 worker 已运行并处理完成）</span>';return;}r.list.forEach(a=>box.appendChild(card(a)));}catch(e){box.innerHTML='';toast('载入素材失败：'+e.message,true);}}
function card(a){const c=document.createElement('div');c.className='asset card';c.innerHTML='<video controls preload="metadata" src="'+esc(a.videoUrl)+'"'+(a.coverUrl?' poster="'+esc(a.coverUrl)+'"':'')+'></video><div class="meta">'+esc(a.scenario)+' · '+esc(a.duration)+'s · '+esc(a.aspectRatio)+' · '+badge(a.status)+'</div><label>标题</label><input class="i-title" value="'+esc(a.title)+'"><label>封面文案</label><input class="i-cover" value="'+esc(a.coverText)+'"><label>推荐语</label><textarea class="i-rec">'+esc(a.recommendationText)+'</textarea><div style="margin:6px 0">'+(a.tags||[]).map(t=>'<span class="tag">'+esc(t)+'</span>').join('')+'</div><div class="row" style="justify-content:flex-start;gap:8px"><button class="ok" data-testid="approve">通过</button><button class="bad">驳回</button></div>';
const review=async status=>{try{const body={status,title:c.querySelector('.i-title').value,coverText:c.querySelector('.i-cover').value,recommendationText:c.querySelector('.i-rec').value};const u=await api('/assets/'+a.id+'/review',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(body)});c.replaceWith(card(u));toast('已'+(status==='approved'?'通过':'驳回'));}catch(e){toast('审核失败：'+e.message,true);}};
c.querySelector('.ok').onclick=()=>review('approved');c.querySelector('.bad').onclick=()=>review('rejected');return c;}
loadTasks();
</script>
</body>
</html>
```

- [ ] **Step 2: 验证静态托管仍通过**

Run: `cd apps/api && npx vitest run test/console.test.ts` → 2 passed（真实 index.html 含 "审核台"）。
Run: `npx vitest run` → 全量 API 套件绿。

- [ ] **Step 3: Commit**

```bash
cd /Users/jc/codesOther/AIGrowthClipStudio && git add -A && git commit -m "feat(m4/web): full review console (create task, asset grid with video preview, approve/reject)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: README 审核台说明

**Files:** Modify `README.md`

- [ ] **Step 1: 在 README「快速开始」附近（或「分开运行」之后）追加一小节**（真正三反引号）

```markdown
## 审核台（M4）

API 在根路径托管一个零依赖的 Web 审核台：起 API + worker 后打开浏览器即可建任务、预览切片、审核通过/驳回。

​```bash
cd apps/api && npm install && npm start        # http://localhost:8787/  ← 审核台
cd apps/worker && python3 -m agcs_worker.main   # 另一终端，处理任务
​```
```

确认 README ``` 数为偶数、未破坏其它小节。

- [ ] **Step 2: Commit**

```bash
cd /Users/jc/codesOther/AIGrowthClipStudio && git add -A && git commit -m "docs(m4): review console run docs

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

- **Spec coverage：** 成功标准 1/4（托管 + 不遮蔽 API/storage）→ Task 2（console.test）；2（建/列/看/审核）→ Task 3 完整控制台；3（TaskSummary 字段）→ Task 1；5（浏览器 QA）→ 控制器在合并前用 gstack browse 验证（计划外的最终演示步）。§3 错误处理（toast/空素材/校验失败）→ Task 3 JS。无缺口。
- **Placeholder scan：** 无 TBD；每步含完整代码/命令/期望；占位 index.html 在 Task 3 被完整替换。
- **Type consistency：** `buildServer(db, storageDir, webDir?)`、`TaskSummary{ id, sourceContentId, title, status, progress, currentStep, errorMessage }`、控制台 fetch 的字段名（taskId、list、videoUrl/coverUrl/title/coverText/recommendationText/tags/status、review body {status,title,coverText,recommendationText}）与 server.ts/repository.ts/schemas.ts 实际一致。

---

## Execution: subagent-driven，每 Task 实现→规格评审→质量评审→修复；Task 全完后控制器用浏览器 QA 端到端验证（建任务→worker→看切片→通过），再合并 main + 推送 + 通知。
