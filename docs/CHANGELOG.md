# 变更记录 / 评审 Changelog

本文件记录方案文档在评审后的改动及其原因，作为立项评审材料与后续演进的对照基线。

---

## 2026-06-02 — 首轮方案评审落地

### 评审结论

方向合理、文档质量高，且接入方案经过真实代码核验（admin 与前台路径、技术栈、API 约定均属实）。本轮改动集中在补齐**最难、最决定成败、但原稿写得最轻**的几个点：高光质量、竖屏适配、效果回流的跨团队依赖、成本/时延量化，以及若干文档内部一致性问题。

### 核验结论（改动依据）

- admin 接入路径全部真实存在：`contentManage/video`、`recommendManagement/slot`、`operation/adManagement`、`operation/featurePage`、`dataManagement`。
- 前台接入路径全部真实存在：`home-recommend`、`fullscreen-feed`、`video-detail`、`membership-center`。
- 技术栈断言准确：admin 实为 Next.js 16 + React 19 + Ant Design 5；API 风格为 `createAxios`；`/truss/` 前缀真实在用（33 个文件，已有 ads/analytics 端点）。

---

### 改动明细

#### 高光识别从“纯字幕”升级为“多信号两段式”

- **为什么**：高光是整个产品的价值锚点。纯文本 LLM 看不到视觉/表情/打斗/BGM 爆点/镜头节奏，会系统性漏判。原 M2 验收只是“输出 N 个候选”的数量验收，没有质量门槛。
- **怎么改**：
  - [01-product-plan.md](./01-product-plan.md) §4.1：加入多信号融合说明（文本/节奏/音频/行为/视觉）。
  - [02-technical-architecture.md](./02-technical-architecture.md) §4.4：重写为“信号融合定位 + LLM 语义解释”两段式，并写明纯字幕版只作冷启动过渡。
  - [03-mvp-implementation-plan.md](./03-mvp-implementation-plan.md) §3.3 M2：改为**质量验收** —— 引入离线评测集（人工标注 20–30 集）+ Top-3 命中率门槛（起步 60%）。
  - [05-ai-pipeline-prompts.md](./05-ai-pipeline-prompts.md)：输入补 `audioFeatures`/`analytics`/`candidateWindows`/`keyframeScore`；prompt 改两段式 + 输出 `signalEvidence`；版本 bump 到 `highlight_detection_v2`。

#### 竖屏画幅适配从“可选项”提为“MVP 一等公民”

- **为什么**：推荐流/全屏 feed 基本是 9:16 竖屏，源片可能是横屏。画幅适配（主体裁切/字幕重排/安全区）决定素材能不能直接投，是硬约束。
- **怎么改**：
  - [01-product-plan.md](./01-product-plan.md) §4.2：写成硬约束，标注 MVP 必做。
  - [02-technical-architecture.md](./02-technical-architecture.md) §4.5：画幅重排升为一等公民；数据模型新增 `targetAspectRatios` / `aspectRatio`，`targetDurations` 放宽为 `number[]`。
  - [03-mvp-implementation-plan.md](./03-mvp-implementation-plan.md) §1/§2.1/§3.4：MVP 目标与 M3 加入 9:16 重排及验收；接口体/建表加 `aspectRatio`。

#### 封面选择补成独立流水线步骤

- **为什么**：README 提了“封面抽帧 + 视觉模型评分”，但 pipeline 步骤里没有，封面在哪一步产出不清楚；封面直接影响点击率，不应隐含在渲染里。
- **怎么改**：[02-technical-architecture.md](./02-technical-architecture.md) §2.4/§4.6 新增 `select_cover` 步骤；[03-mvp-implementation-plan.md](./03-mvp-implementation-plan.md) M3 与 worker 伪代码同步加入。

#### 效果回流标注为跨团队前置依赖

- **为什么**：第三阶段“AI 基于效果优化”依赖前台埋点透传 `ai_asset_id` + 看板按素材聚合，这是最容易卡住的跨团队依赖，不前置确认会变成 PPT 功能。
- **怎么改**：[04-company-integration.md](./04-company-integration.md) §4：列为前置条件，要求 MVP 立项时即与数据团队对齐两点（埋点自定义维度、看板素材维度聚合）。

#### 新增量化目标（成本 / 时延 / 并发）

- **为什么**：原稿只有定性降级，没有任何数字；上线与否最终由这几个数字决定。
- **怎么改**：[03-mvp-implementation-plan.md](./03-mvp-implementation-plan.md) §8 新增目标表 + 算力资源前提 + 成本可观测。

#### 服务主语言边界拍板

- **为什么**：原稿在 Node/Python 间没拍板，会拖累 M0“项目骨架”。
- **怎么改**：[02-technical-architecture.md](./02-technical-architecture.md) §2.3：BFF=Node（贴 admin）、Worker=Python（贴 FFmpeg/Whisper/PySceneDetect）、Redis 队列；跨语言只走队列+对象存储+DB。

#### 投放渠道侧合规补充

- **为什么**：切片投信息流广告要过各渠道（抖音/快手/Meta）审核规则；会员试看涉及剧透与授权边界。原稿只覆盖内部审核。
- **怎么改**：[02-technical-architecture.md](./02-technical-architecture.md) §7 补充渠道侧合规与质检规则切换。

#### 上游内容平台集成钩子

- **为什么**：“接住短剧产物继续放大价值”是卖点，但原稿没有系统层集成设计。
- **怎么改**：[04-company-integration.md](./04-company-integration.md) §9 新增事件触发钩子（短剧生成完成 → 自动建任务），MVP 可不接但预留接口。

#### 文档内部一致性修复

- **数据表口径统一**：[02-technical-architecture.md](./02-technical-architecture.md) §2.6 改为“MVP 三张表 + 观测/回流两张表”，包装内嵌 `ai_clip_assets`，候选放 `ai_clip_segments.packaging_draft`，与 [03](./03-mvp-implementation-plan.md) 建表草案对齐。
- **类型放宽**：`targetDurations` 字面量联合 → `number[]`；`AiClipAsset.duration` 同步放宽。
- **大对象存储**：[02-technical-architecture.md](./02-technical-architecture.md) §3.4 注明 `AiPromptRun.outputJson` 大对象应存引用/对象存储 + TTL。
- **MVP 边界澄清**：[03-mvp-implementation-plan.md](./03-mvp-implementation-plan.md) §1 明确多语言只预留、不做烧录字幕和 AI 配音。
- **README 同步**：[README.md](./README.md) MVP 步骤同步多信号高光、竖屏重排、封面帧。

---

### 仍待决策的开放项（进 M0 前建议拍板）

1. **高光评测集与目标值**：谁来标、标多少集、Top-3 命中率与采纳率的初版目标数字。
2. **算力前提**：WhisperX / 视觉模型用自建 GPU 还是云上，决定成本模型与并发上限。
3. **回流可行性**：数据团队确认埋点自定义维度与看板素材维度聚合是否可加、排期如何。
4. **渠道合规规则源**：渠道敏感词/诱导词规则由谁维护、是否按目标渠道切换。
5. **多版本包装是否要 A/B**：决定 `packaging_draft` 是否要拆成独立 `ai_clip_packaging` 表。
