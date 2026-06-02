# AI Growth Clip Studio — M0 可运行骨架 设计 Spec

- 日期：2026-06-02
- 范围：M0（可运行骨架），对应 [03-mvp-implementation-plan.md](../../03-mvp-implementation-plan.md) §3.1 的 M0，并含其定义的“mock 流水线 + 假/真产物”闭环。
- 状态：已与用户对齐，待写实现计划。

## 1. 目标

在本仓库内搭出一个**端到端能跑通**的骨架：通过 Node BFF 创建任务 → Python worker 轮询消费 → 跑一条以 mock 为主、ffmpeg 为真的流水线 → 产出文件与数据库记录 → 通过 API 查询进度/产物并审核。

成功标准（M0 验收）：

1. 调 `POST /api/ai-growth-clip/tasks` 能创建任务并返回 `taskId`。
2. 调 `GET /api/ai-growth-clip/tasks/:id` 能查到状态从 `queued` → `running` → `succeeded` 的推进与 `progress`/`currentStep`。
3. worker 自动认领任务、按流水线步骤推进、写出产物文件与 `ai_clip_segments` / `ai_clip_assets` 行。
4. `GET /api/ai-growth-clip/tasks/:id/assets` 返回产物列表；`POST /api/ai-growth-clip/assets/:id/review` 能改状态/文案。
5. 克隆仓库后无需外部素材、无需 Redis/Docker/LLM key 即可跑通（内置 ffmpeg 生成的测试视频）。

## 2. 关键架构决策

### 2.1 SQLite 同时作“状态库 + 任务队列”

- 不引入 Redis/消息队列。任务行即队列：`ai_clip_tasks.status='queued'` 的行就是待处理队列。
- Node API 负责写入任务（`queued`）与读取状态/产物；Python worker 轮询认领。
- 认领用原子 UPDATE 防重复领取：
  - `UPDATE ai_clip_tasks SET status='running', ... WHERE id=? AND status='queued'`，受影响行数为 1 才算认领成功。
- SQLite 开 **WAL 模式**，允许“API 读 + worker 写”跨进程并发；M0 单 worker，竞争极小。

### 2.2 render/cover 用真实 ffmpeg，其余重服务 mock

- `render_clips`、`select_cover` 调真实 ffmpeg（本机已有 8.1），产出真实 mp4 与封面 jpg，验证最有价值的一环。
- `transcribe_audio`、`detect_scenes`、`analyze_highlights`、`generate_packaging` 走 **mock 适配器**，接口预留，后续替换真实 ASR/LLM 零返工。

## 3. 目录结构（monorepo）

```text
AIGrowthClipStudio/
  apps/
    api/        # Node + TypeScript BFF (Fastify + better-sqlite3 + zod)
    worker/     # Python worker (stdlib sqlite3 + ffmpeg 子进程)
  db/
    schema.sql  # 唯一建表源，两端共用
  storage/      # 本地产物（mp4/jpg/json），gitignored
  data/         # sqlite 文件，gitignored
  docs/         # 已有设计文档
```

## 4. 数据层

- SQLite（WAL），三张表，DDL 以 `db/schema.sql` 为唯一来源。
- 表结构对齐 [03 §5 建表草案](../../03-mvp-implementation-plan.md)，含本轮评审新增字段：
  - `ai_clip_tasks`：`target_scenarios` / `target_durations` / `target_aspect_ratios` / `target_languages`（JSON 文本）、`status` / `progress` / `current_step` / `error_message` / `created_by` / 时间戳。
  - `ai_clip_segments`：起止时间、`highlight_type` / `score` / `reason` / `summary` / `transcript_text` / `risk_level` / `risk_reason` / `packaging_draft`（JSON）/ `status`。
  - `ai_clip_assets`：`scenario` / `duration` / `aspect_ratio` / `language` / `video_url` / `cover_url` / `subtitle_url` / `title` / `cover_text` / `recommendation_text` / `tags`（JSON）/ `status`。
- 时间戳用毫秒整数。JSON 字段在 SQLite 里存 TEXT。
- API 启动时执行 `schema.sql`（`CREATE TABLE IF NOT EXISTS`）；worker 假定表已存在。
- 观测/回流表（`ai_prompt_runs` / `ai_asset_metrics`）M0 不建。

## 5. API（Node / TypeScript，Fastify）

技术：Fastify + better-sqlite3（同步、轻量）+ zod（请求校验）+ TypeScript，dev 用 `tsx`，测试用 vitest。

端点（对齐 [03 §4](../../03-mvp-implementation-plan.md)；独立服务用 `/api` 前缀，接 admin 时再加 `/truss` 代理）：

| 方法 | 路径 | 作用 |
|---|---|---|
| POST | `/api/ai-growth-clip/tasks` | 建任务（插入 `queued` 行）→ `{ taskId }` |
| GET | `/api/ai-growth-clip/tasks` | 任务中心列表（分页/状态筛选） |
| GET | `/api/ai-growth-clip/tasks/:id` | 状态/进度/currentStep/errorMessage |
| GET | `/api/ai-growth-clip/tasks/:id/assets` | 产物列表 |
| POST | `/api/ai-growth-clip/assets/:id/review` | 审核改状态/文案 |
| GET | `/storage/*` | 静态托管产物，便于本地预览 |

请求/响应示例：

- `POST /tasks` body（zod 校验）：
  ```json
  {
    "sourceContentId": "12345",
    "sourceContentType": "episode",
    "sourceVideoUrl": "file:///abs/path/sample.mp4",
    "title": "她被退婚后身份曝光",
    "description": "短剧第 1 集",
    "category": "短剧",
    "tags": ["逆袭", "豪门", "复仇"],
    "targetScenarios": ["feed", "membership"],
    "targetDurations": [15, 30],
    "targetAspectRatios": ["9:16"],
    "targetLanguages": ["zh-CN"],
    "clipCount": 3
  }
  ```
  - `sourceVideoUrl` 支持 `file://` 本地路径（M0 用），缺省/不可达时走 stub 渲染。
- `POST /tasks` 响应：`{ "taskId": "task_xxx" }`，行 status=`queued`、progress=0。
- `GET /tasks/:id` 响应：`{ id, status, progress, currentStep, errorMessage }`。
- `POST /assets/:id/review` body：`{ status: "approved"|"rejected", title?, coverText?, recommendationText? }`。

ID 生成：服务端生成 `task_` / `segment_` / `asset_` 前缀的短 ID（基于计数器/随机，避免 Date 依赖问题，用 crypto 随机）。

## 6. Worker（Python）

- 入口：长轮询循环（间隔可配，默认 1s），认领一条 `queued` 任务后顺序跑流水线，更新 `progress`/`current_step`；跑完置 `succeeded`，异常置 `failed` + `error_message`。
- 也提供一次性模式 `--once`（认领并处理一条后退出），供测试/冒烟脚本使用。

流水线步骤（对齐 [02 §4](../../02-technical-architecture.md) 与 worker 伪代码）：

| 步骤 | M0 实现 | 后续真实 |
|---|---|---|
| prepare_video | 有本地文件→`ffprobe` 取真实元信息；否则 mock 元信息 | — |
| transcribe_audio | MOCK：罐头 transcript segments + 写 `transcript.json`/`zh-CN.vtt` | faster-whisper |
| detect_scenes | MOCK：按时长均匀切分，写 `scenes.json` | PySceneDetect |
| analyze_highlights | MOCK：产出 `clipCount` 个罐头高光（含 startMs/endMs/type/score/reason/summary） | LLM |
| render_clips | 真实 ffmpeg：按 segment 切片，按 `targetAspectRatios` 做画幅重排（9:16 用 crop/scale）；每 duration×aspectRatio 一份；无视频→写 stub 文件 | — |
| select_cover | 真实 ffmpeg：抽一帧作封面；无视频→stub jpg | 视觉模型评分 |
| generate_packaging | MOCK：罐头标题/封面文案/推荐语/标签，写入 segment 的 `packaging_draft` 并落 asset | LLM |
| quality_check | 真实基础校验（文件存在、时长非空）+ mock 风险标记 | 渠道规则 |
| persist_assets | 写 `ai_clip_segments` + `ai_clip_assets`，任务置 `succeeded` | — |

素材基数（钉死，避免组合爆炸）：M0 一个高光 segment 产出的 asset 数 = `targetDurations × targetAspectRatios`。`scenario` 取该 segment 的推荐场景（mock 挑一个 targetScenario），`language` 取 `targetLanguages[0]`。例：clipCount=3、durations=[15,30]、aspectRatios=[9:16] → 3 segments × 2 × 1 = 6 个 asset。

适配器接口（Python 抽象基类 / Protocol），靠 env 选 provider：

```python
class AsrProvider(Protocol):
    def transcribe(self, audio_path: str) -> Transcript: ...

class HighlightProvider(Protocol):
    def analyze(self, ctx: HighlightContext) -> list[Segment]: ...

class PackagingProvider(Protocol):
    def generate(self, ctx: PackagingContext) -> Packaging: ...
```

- 默认 `MockAsrProvider` / `MockHighlightProvider` / `MockPackagingProvider`。
- env：`ASR_PROVIDER=mock` / `HIGHLIGHT_PROVIDER=mock` / `PACKAGING_PROVIDER=mock`。

## 7. 配置

- 两端共用一份 `.env`（仓库提供 `.env.example`）：
  - `DB_PATH=./data/agcs.db`
  - `STORAGE_DIR=./storage`
  - `API_PORT=8787`
  - `WORKER_POLL_INTERVAL_MS=1000`
  - `ASR_PROVIDER=mock` / `HIGHLIGHT_PROVIDER=mock` / `PACKAGING_PROVIDER=mock`
- API 用 TS 读 env；worker 用 stdlib 读 env（轻量 .env 加载，避免重依赖）。

## 8. 数据流

```text
POST /tasks (Node) → 插入 queued 行 (SQLite, WAL)
  → worker 轮询 → 原子认领 queued→running
  → prepare→transcribe(mock)→scenes(mock)→highlights(mock)
    →render(ffmpeg)→cover(ffmpeg)→packaging(mock)→quality→persist
  → 写 storage/<taskId>/... 产物 + segments/assets 行
  → 任务 succeeded
GET /tasks/:id → 进度；GET /assets → 产物；POST /review → 改状态
```

产物目录约定：`storage/<taskId>/transcript.json`、`scenes.json`、`clips/<assetId>.mp4`、`covers/<assetId>.jpg`。`video_url`/`cover_url` 存为 `/storage/...` 相对路径，便于静态托管预览。

## 9. 错误处理

- worker 单任务 try/catch：失败置 `status='failed'`、写 `error_message`、保留 `progress`/`current_step` 现场。
- ffmpeg 调用失败：捕获非零退出码与 stderr，归类为该步骤失败（对齐 [03 §7 降级]——保留时间码供后续手动处理）。
- 认领竞争：原子 UPDATE 保证不重复领取；M0 单 worker。
- API 输入校验失败返回 400 + 校验信息；未知 taskId/assetId 返回 404。

## 10. 测试策略（实现走 TDD，先测后码）

- **API（vitest）**：内存 SQLite。
  - 建任务返回 taskId、行为 queued；
  - 查任务返回状态字段；
  - 审核改 asset 状态/文案；
  - body 校验失败返回 400；未知 id 返回 404。
- **Worker（pytest）**：内置极小样例 mp4（仓库放一个，或测试 setup 用 ffmpeg 生成几秒纯色+静音视频）。
  - 全流水线在样例视频上跑通，断言产物文件存在、segments/assets 行写入、任务 succeeded；
  - 每个 mock 适配器单测输出结构；
  - 无视频（stub 分支）也能跑通并置 succeeded；
  - ffmpeg 失败时任务置 failed。
- **端到端冒烟（脚本）**：起 API（或直接用 DB 层）插一条任务 → `worker --once` → 断言 assets 存在、状态 succeeded。

## 11. 明确不做（M0 范围外）

真实 ASR / LLM / 场景检测、Redis / Docker、admin UI 与前台接入、多语言与烧录字幕、权限鉴权（`created_by` 写死占位）、效果回流与 `ai_prompt_runs` / `ai_asset_metrics`、任务重试/取消接口（可留 TODO）、对象存储/CDN（用本地 `storage/`）。

## 12. 后续衔接（非本期实现，仅记录方向）

- M1：`transcribe_audio` 接 faster-whisper、`detect_scenes` 接 PySceneDetect。
- M2：`analyze_highlights` 接 LLM + 多信号（[02 §4.4]），引入离线评测集。
- M3：`generate_packaging` 接 LLM、封面接视觉模型评分。
- M4：admin 审核台（接 [04 接入方案]）。
- 队列：负载上来后由 SQLite 轮询迁移到 Redis/BullMQ + Celery。
