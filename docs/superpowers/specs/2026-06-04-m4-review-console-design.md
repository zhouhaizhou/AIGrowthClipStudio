# M4 — 增长素材审核台（standalone review console）设计 Spec

- 日期：2026-06-04
- 范围：一个**自包含的 Web 审核台**，由现有 Fastify API 托管。运营在浏览器里创建任务、查看 worker 产出的切片（视频预览）、审核（通过/驳回 + 改文案）。纯前端 + 复用既有 REST 接口，**无需 API key**，端到端可在浏览器演示。
- 依赖前置：M0–M3 已在 main（HEAD 882d864）。API 端点已就绪：POST/GET tasks、GET tasks/:id/assets、POST assets/:id/review；切片走 `/storage/`。
- 自主执行：我自行定稿设计/spec/plan，subagent-driven + 评审，浏览器 QA 验证，完成后合并并通知。
- 备注：这是设计文档"admin 审核台"的**独立简化版**（不接公司 admin 仓库 /Users/jc/codes/admin，那是 Next.js 跨仓库集成，远期）。本期做一个能跑能看的自有控制台。

## 1. 目标

让整条流水线**可视、可交互**：一个页面完成 建任务 → 看产物 → 审核 的闭环。

成功标准（M4 验收）：

1. API 在 `/`（根）托管审核台静态页 `web/index.html`；`GET /` 返回 200 HTML；既有 `/api/*` 与 `/storage/*` 不受影响。
2. 页面能：建任务（POST /tasks）、列任务（GET /tasks，含 title）、看某任务素材（GET /tasks/:id/assets，含视频预览）、审核（POST /assets/:id/review，可改 title/coverText/recommendationText）。
3. 任务列表 DTO 增加 `sourceContentId`/`title`（让列表有意义）；不破坏现有 task 接口测试。
4. vitest：`GET /` 返回 HTML、`GET /storage/*` 仍静态、`GET /api/...` 仍工作（静态根不遮蔽 API 路由）。
5. 浏览器 QA：起 API+worker，开控制台，建任务→worker 处理→刷新看到 6 个素材（真实切片可播放）→通过一个，状态变 approved。截图为证。

## 2. 架构

### 2.1 托管方式
- 新增 `apps/api/web/index.html`（自包含：内联 CSS + 原生 JS fetch，无构建步、无框架依赖）。
- `buildServer(db, storageDir, webDir?)` 增一个 `webDir` 参数（默认指向 `apps/api/web`）。再注册一个 `@fastify/static`（已是依赖）以 `webDir` 为 root、prefix `/`、`decorateReply: false`（避免与 `/storage` 的 sendFile 装饰冲突）。显式 `/api/*` 路由优先于静态通配，互不遮蔽。
- 同源：页面从 API 同源加载，fetch `/api/...` 无 CORS 问题；视频 `<video src="/storage/...">` 同源直放。

### 2.2 页面结构（单文件）
- 顶栏：标题 + 简介。
- 「创建任务」表单（可折叠）：sourceContentId、sourceVideoUrl(支持 file://)、title、category、tags(逗号)、targetScenarios(复选 feed/detail/ad/membership/social)、targetDurations(复选 15/30/60)、targetAspectRatios(复选 9:16/16:9/1:1/4:5)、clipCount → POST /tasks → toast 显示 taskId。
- 「任务」区：刷新按钮 → GET /tasks → 列表（短 id、title、status 徽章、progress%）→ 点选加载素材。
- 「素材」区：选中任务 → GET /tasks/:id/assets → 卡片网格：`<video controls>` 预览切片、可编辑 title/coverText/recommendationText、显示 tags/scenario/duration/aspectRatio/status 徽章、「通过」「驳回」按钮 → POST /assets/:id/review（带编辑后的字段）→ 局部刷新卡片。
- 徽章配色：任务 queued/running/succeeded/failed；素材 pending_review/approved/rejected。
- 极简自适应布局；无第三方 CSS/JS。

### 2.3 API 增强（最小）
- `repository.toTaskSummary` 增 `sourceContentId`、`title`（读 row 既有列）。`TaskSummary` 接口加这两字段。listTasks/getTask 自动带上。现有断言（status/progress）不受影响。

## 3. 错误处理
- fetch 失败 → 页面顶部红色 toast 显示错误，不白屏。
- 建任务校验失败（400）→ 显示后端 issues 概要。
- 素材为空 → 显示"暂无素材（确认 worker 已运行并处理完成）"。
- 审核 404 → toast 提示。
- 静态根 `/` 不能遮蔽 `/api/*`、`/storage/*`：靠 Fastify 路由优先级 + 独立 prefix 保证；测试覆盖。

## 4. 测试策略
- `apps/api/test/console.test.ts`（vitest + inject）：`GET /` → 200 且 body 含审核台标记（如 `<title>` 或某 data-testid）；`GET /api/ai-growth-clip/tasks` 仍返回 `{list:[...]}`（静态根不遮蔽 API）；建任务后 `GET /` 仍 200。
- `repository.test.ts`（追加）：createTask 后 listTasks[0] 含 `sourceContentId`、`title`。
- 浏览器 QA（gstack browse）：端到端开页 → 建任务 → 跑 worker（脚本/手动）→ 看素材视频 → 通过 → 断言状态 approved + 截图。
- 全量 API/worker 套件保持绿。

## 5. 本会话演示
- 起 API + worker，`open http://localhost:8787/`，建任务（用内置 sample.mp4 的 file:// 路径），worker 处理后刷新 → 6 个素材卡片，视频可播；点「通过」→ 徽章变 approved。截图存档。

## 6. 不做（M4 范围外）
- 接公司 Next.js admin（跨仓库，远期）；鉴权/登录；推荐位/广告位绑定；分页/筛选器高级 UI；前端构建链（保持零依赖单文件）；多语言切换；效果回流图表。

## 7. 受影响文件
- 增：`apps/api/web/index.html`、`apps/api/test/console.test.ts`。
- 改：`apps/api/src/server.ts`（webDir 静态托管）、`apps/api/src/index.ts`（传 webDir）、`apps/api/src/repository.ts`（TaskSummary +sourceContentId/title）、`apps/api/test/repository.test.ts`（断言新字段）、`README.md`（审核台说明）。
