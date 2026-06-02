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

MVP 推荐：

- Node.js 项目用 BullMQ
- Python 视频处理多时用 Celery

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
  -> generate_packaging
  -> quality_check
  -> persist_assets
```

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

核心表：

- ai_clip_tasks
- ai_clip_assets
- ai_clip_segments
- ai_clip_packaging
- ai_prompt_runs
- ai_asset_metrics

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
  targetDurations: Array<15 | 30 | 60>;
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
  duration: 15 | 30 | 60;
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

输入：

- transcript
- scenes
- content metadata
- optional analytics

处理：

- 把字幕按镜头和语义分段
- 识别候选高光
- 给每个候选片段评分
- 输出结构化片段

模型：

- LLM
- 可选视觉模型

输出：

- highlight_candidates.json

## 4.5 render_clips

输入：

- highlight candidates
- target durations
- render config

处理：

- 调整起止时间到合适镜头边界
- 裁剪视频
- 可选烧录字幕
- 可选生成竖屏版本

工具：

- FFmpeg

输出：

- clip video files

## 4.6 generate_packaging

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

## 4.7 quality_check

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

