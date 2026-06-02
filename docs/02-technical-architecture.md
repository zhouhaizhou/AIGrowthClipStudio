# 技术架构

## 1. 总体架构

```text
Admin UI
  -> API Gateway / BFF
  -> Task Service
  -> AI Pipeline Worker
  -> Storage / CDN
  -> Metadata DB
  -> Frontend Video Platform
  -> Analytics Feedback
```

核心设计原则：

- 所有重任务异步化。
- 视频文件不经过前端直传 AI 服务，使用对象存储 URL。
- AI 产物先进入审核态，不直接发布。
- Prompt、模型、版本、成本必须可追踪。
- 视频模型、ASR、LLM 都通过适配器接入，避免绑定单一供应商。

## 2. 服务拆分

## 2.1 Web Admin

职责：

- 创建 AI 任务
- 查看任务进度
- 审核 AI 产物
- 编辑素材元数据
- 发布素材

建议技术：

- 复用公司 admin：Next.js + React + Ant Design

## 2.2 BFF / API Server

职责：

- 鉴权
- 参数校验
- 创建任务
- 查询任务
- 查询素材
- 写回公司内容系统

建议接口风格：

- REST 即可
- 内部任务事件可使用 message queue

## 2.3 Task Service

职责：

- 管理异步任务生命周期
- 任务排队
- 任务重试
- 任务取消
- 失败告警

可选技术：

- BullMQ + Redis
- Celery + Redis/RabbitMQ
- Temporal

MVP 主语言边界（直接拍板，避免 M0 含糊）：

- **BFF / API Server = Node.js**，贴合公司 admin（Next.js + React + Ant Design）现有栈和 `createAxios` 风格。
- **AI Pipeline Worker = Python**，贴合 FFmpeg / WhisperX / faster-whisper / PySceneDetect 生态。
- **队列用 Redis**，两边都能接：Node 侧用 BullMQ 入队/查询，Python 侧用 Celery 或 RQ 消费。
- 不要在 MVP 阶段纠结统一单语言；混合栈在这个场景是正常且更省力的选择。
- 跨语言只通过“队列消息 + 对象存储产物 + DB 状态”通信，不共享内存对象。

## 2.4 AI Pipeline Worker

职责：

- 音频抽取
- ASR 字幕
- 镜头切分
- 高光分析
- 视频裁剪
- 封面抽帧
- 文案生成
- 多语言翻译

建议拆成多个 pipeline step：

```text
prepare_video
  -> transcribe_audio
  -> detect_scenes
  -> analyze_highlights
  -> render_clips
  -> select_cover
  -> generate_packaging
  -> quality_check
  -> persist_assets
```

说明：`select_cover` 是独立一步——从切片里抽候选帧并用视觉模型/规则打分，选出封面帧。封面直接影响推荐流点击率，不应隐含在渲染里。

## 2.5 Storage

存储内容：

- 原视频引用
- 音频临时文件
- 字幕文件
- 镜头截图
- 切片视频
- 封面图
- AI 分析 JSON

建议：

- 临时文件设置生命周期自动删除。
- 审核通过的素材进入长期存储。
- 前台消费文件必须走 CDN。

## 2.6 Metadata DB

表分两批，避免“核心表”和建表草案不一致：

MVP 必建（见 03 建表草案）：

- ai_clip_tasks
- ai_clip_segments
- ai_clip_assets

观测/回流阶段补建：

- ai_prompt_runs（LLM 调用记录，随观测能力上）
- ai_asset_metrics（效果回流，随数据闭环上）

说明：

- 运营包装结果（标题/封面文案/推荐语/标签）**直接内嵌在 `ai_clip_assets`**，MVP 不单独建 `ai_clip_packaging` 表。
- 包装 prompt 会产出多个候选标题/封面（见 05），审核阶段需要的候选集放在 `ai_clip_segments` 的 `packaging_draft` JSON 字段里；审核通过后把选中的那条落到 `ai_clip_assets`。
- 真正需要“多版本包装做 A/B”时，再把候选拆成独立 `ai_clip_packaging` 表（后续阶段）。

## 3. 核心数据模型

## 3.1 AI 任务

```ts
type AiClipTaskStatus =
  | 'queued'
  | 'running'
  | 'succeeded'
  | 'failed'
  | 'cancelled';

interface AiClipTask {
  id: string;
  sourceContentId: string;
  sourceContentType: 'video' | 'episode';
  sourceVideoUrl: string;
  targetScenarios: Array<'feed' | 'detail' | 'ad' | 'membership' | 'social'>;
  // 用 number[] 而非 15|30|60 字面量，便于扩展 9s/45s 等时长
  targetDurations: number[];
  // 目标画幅；推荐流/全屏 feed 多为 9:16，MVP 必须支持竖屏重排
  targetAspectRatios: Array<'9:16' | '16:9' | '1:1' | '4:5'>;
  targetLanguages: string[];
  status: AiClipTaskStatus;
  progress: number;
  currentStep?: string;
  errorMessage?: string;
  createdBy: string;
  createdAt: number;
  updatedAt: number;
}
```

## 3.2 高光片段

```ts
interface AiClipSegment {
  id: string;
  taskId: string;
  sourceContentId: string;
  startMs: number;
  endMs: number;
  durationMs: number;
  highlightType:
    | 'conflict'
    | 'reversal'
    | 'emotion'
    | 'funny'
    | 'suspense'
    | 'membership_conversion'
    | 'ad_hook';
  score: number;
  reason: string;
  summary: string;
  transcriptText: string;
  riskLevel: 'low' | 'medium' | 'high';
  riskReason?: string;
  status: 'candidate' | 'approved' | 'rejected';
}
```

## 3.3 增长素材

```ts
interface AiClipAsset {
  id: string;
  taskId: string;
  segmentId: string;
  sourceContentId: string;
  scenario: 'feed' | 'detail' | 'ad' | 'membership' | 'social';
  duration: number;
  aspectRatio: '9:16' | '16:9' | '1:1' | '4:5';
  language: string;
  videoUrl: string;
  coverUrl?: string;
  subtitleUrl?: string;
  title: string;
  coverText: string;
  recommendationText: string;
  tags: string[];
  status: 'pending_review' | 'approved' | 'rejected' | 'published' | 'archived';
  createdAt: number;
  updatedAt: number;
}
```

## 3.4 Prompt 调用记录

```ts
interface AiPromptRun {
  id: string;
  taskId: string;
  step: string;
  provider: string;
  model: string;
  promptVersion: string;
  inputHash: string;
  // outputJson 可能很大，DB 里只存摘要/引用；完整输出建议落对象存储并设 TTL，
  // 这里改存 outputRef（对象存储 key）或截断后的 outputSummary，避免表膨胀
  outputJson: unknown;
  latencyMs: number;
  inputTokens?: number;
  outputTokens?: number;
  cost?: number;
  createdAt: number;
}
```

## 4. Pipeline 设计

## 4.1 prepare_video

输入：

- sourceVideoUrl

处理：

- 下载或读取视频元信息
- 获取 duration、width、height、fps、codec
- 抽取音频

工具：

- FFmpeg
- ffprobe

输出：

- videoMetadata
- audioPath

## 4.2 transcribe_audio

输入：

- audioPath

处理：

- ASR 转写
- 生成 word-level timestamp
- 生成 VTT/SRT

工具：

- WhisperX
- faster-whisper

输出：

- transcript.json
- zh-CN.vtt

## 4.3 detect_scenes

输入：

- videoPath

处理：

- 识别镜头切分
- 抽关键帧
- 记录每个镜头的时间范围

工具：

- PySceneDetect
- FFmpeg

输出：

- scenes.json
- keyframes

## 4.4 analyze_highlights

这是整个产品的价值锚点（“高光准不准”），不能只靠字幕文本。采用多信号融合定位 + LLM 语义解释的两段式：

输入：

- transcript（文本语义信号）
- scenes（镜头切分密度、剪辑节奏信号）
- audioFeatures（音量能量包络、静音比例、BGM 高潮——可由 FFmpeg/librosa 抽取）
- content metadata
- optional analytics（完播热力、拖拽/回看热点、跳出点——若前台有埋点）
- optional keyframe scores（关键帧视觉模型打分）

处理：

1. 信号融合定位：用节奏/音频/行为信号先圈出候选时间窗（不依赖 LLM）。
2. 语义解释归类：把候选窗对应的字幕 + 关键帧交给 LLM，做高光类型判断、评分、reason。
3. 边界对齐：把起止时间吸附到镜头边界，避免半句话/半个镜头。

模型：

- LLM（语义解释和归类）
- 可选视觉模型（关键帧打分）

输出：

- highlight_candidates.json

降级注意：纯“LLM + 字幕”可作为最初版本，但必须配离线评测集衡量采纳率（见 03 的 M2 验收），不能把“多出候选让运营挑”当成长期方案——那会把成本推回人工，削弱核心卖点。

## 4.5 render_clips

输入：

- highlight candidates
- target durations
- target aspect ratios
- render config

处理：

- 调整起止时间到合适镜头边界
- 裁剪视频
- 画幅重排（一等公民，非可选）：按 targetAspectRatios 输出 9:16 等版本，处理主体裁切、安全区避让、字幕重排
- 软字幕关联；烧录字幕作为可选项（MVP 默认软字幕，烧录放后续）

工具：

- FFmpeg（裁剪、crop/scale/pad 做画幅重排）
- 可选：主体检测（人脸/显著性）辅助竖屏裁切，避免主体被切掉

输出：

- clip video files（每个 duration × aspectRatio 一份）

## 4.6 select_cover

输入：

- clip video file
- scenes / keyframes

处理：

- 从切片抽候选帧
- 用视觉模型或规则（清晰度、人脸、表情强度、非黑屏）打分
- 选出封面帧，必要时叠加封面文案（封面文案由 generate_packaging 产出）

工具：

- FFmpeg 抽帧
- 可选视觉模型评分

输出：

- cover image（候选 + 选中）

## 4.7 generate_packaging

输入：

- clip transcript
- content metadata
- target scenario

处理：

- 生成标题
- 生成封面文案
- 生成推荐语
- 生成标签
- 生成多语言字幕和文案

输出：

- packaging.json
- subtitle files

## 4.8 quality_check

检查项：

- 视频是否可播放
- 时长是否符合要求
- 字幕是否过长
- 标题是否过长
- 文案是否包含风险词
- 片段是否黑屏/静音占比过高
- 是否包含明显违规内容

输出：

- quality_report.json

## 5. 视频模型适配器

MVP 主要使用 FFmpeg 剪辑已有视频，不依赖文生视频。

后续可以加视频生成模型：

```ts
interface VideoGenerationProvider {
  name: string;
  createTask(input: VideoGenerationInput): Promise<{ providerTaskId: string }>;
  getTask(providerTaskId: string): Promise<VideoGenerationResult>;
  cancelTask?(providerTaskId: string): Promise<void>;
}
```

适配对象：

- 即梦
- 可灵
- 海螺
- Vidu
- 其他内部供应商

## 6. 观测和质量

必须记录：

- 每一步耗时
- 每一步输入输出摘要
- 模型名称
- prompt 版本
- token 和成本
- 失败原因
- 人工采纳/驳回结果

建议工具：

- Langfuse：LLM 调用观测
- Promptfoo：prompt 回归测试
- Sentry 或内部日志：工程异常

## 7. 安全与版权

约束：

- 只处理公司拥有版权或已授权的视频。
- AI 生成文案必须经过审核再发布。
- 用户数据进入 LLM 前需要脱敏。
- 视频 URL 应使用短期签名 URL。
- 任务产物按权限隔离。

投放渠道侧合规（容易被漏，但直接决定素材能不能投出去）：

- 切片用于信息流广告时，需适配各渠道（抖音/快手/视频号/Meta 等）的素材审核规则：标题党、诱导性表达、版权 BGM、画面违规等。
- 质检（quality_check）应内置一份“渠道敏感词/诱导词”规则，并允许按目标渠道切换。
- 会员“试看片段 + 解锁话术”要平衡剧透与转化，且只能在内容授权的范围内生成；付费正片的切片对外投放需单独确认授权边界。

