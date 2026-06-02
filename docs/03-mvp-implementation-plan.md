# MVP 实施计划

## 1. MVP 目标

第一版目标：

> 在 admin 中选择一个视频，自动生成 3 个高光片段，并产出 15s/30s 视频素材、标题、封面文案和推荐语。

MVP 不做：

- 完整视频编辑器
- 自动发布
- 多供应商视频生成
- 复杂 A/B 实验
- 全量数据回流

## 2. MVP 功能范围

## 2.1 创建任务

入口：

- admin 视频列表或视频详情弹窗

表单字段：

- 视频 ID
- 视频 URL
- 视频标题
- 视频简介
- 分类
- 标签
- 目标场景：feed/detail/ad/membership
- 目标时长：15s/30s
- 生成数量：默认 3

## 2.2 任务进度

展示：

- queued
- running
- succeeded
- failed

步骤：

- 准备视频
- 生成字幕
- 分析高光
- 渲染切片
- 生成文案
- 质检

## 2.3 结果审核

每个结果展示：

- 视频预览
- 起止时间
- 高光类型
- 选择理由
- 标题
- 封面文案
- 推荐语
- 标签
- 质量报告

操作：

- 通过
- 驳回
- 修改文案
- 下载视频
- 保存素材

## 3. 里程碑

## 3.1 M0：项目骨架

产出：

- API Server 项目骨架
- Worker 项目骨架
- 数据库表结构
- 本地对象存储或 S3 配置
- 任务队列配置

验收：

- 可以创建一个 mock 任务
- 可以查询任务状态
- worker 可以消费任务并更新进度

## 3.2 M1：字幕和镜头切分

产出：

- FFmpeg 抽音频
- WhisperX/faster-whisper 生成字幕
- PySceneDetect 镜头切分
- 关键帧抽取

验收：

- 输入视频 URL，生成 transcript.json、zh-CN.vtt、scenes.json

## 3.3 M2：高光识别

产出：

- LLM prompt
- 字幕分段逻辑
- 高光候选 JSON
- 基础风险检查

验收：

- 每个视频输出 3-6 个候选片段
- 每个候选包含 startMs、endMs、highlightType、score、reason、summary

## 3.4 M3：视频渲染和文案生成

产出：

- FFmpeg 裁剪
- 15s/30s 输出
- 标题/封面文案/推荐语生成
- 字幕文件关联

验收：

- 每个候选片段可以生成可播放 mp4
- 每个素材有完整运营文案

## 3.5 M4：admin 审核台

产出：

- 任务列表
- 任务详情
- 素材预览
- 通过/驳回
- 文案编辑

验收：

- 运营可以从创建任务走到审核保存

## 4. 接口草案

## 4.1 创建任务

```http
POST /api/ai-growth-clip/tasks
Content-Type: application/json
```

```json
{
  "sourceContentId": "12345",
  "sourceContentType": "episode",
  "sourceVideoUrl": "https://cdn.example.com/video.mp4",
  "title": "她被退婚后身份曝光",
  "description": "短剧第 1 集",
  "category": "短剧",
  "tags": ["逆袭", "豪门", "复仇"],
  "targetScenarios": ["feed", "membership"],
  "targetDurations": [15, 30],
  "targetLanguages": ["zh-CN"],
  "clipCount": 3
}
```

响应：

```json
{
  "taskId": "task_001"
}
```

## 4.2 查询任务

```http
GET /api/ai-growth-clip/tasks/:taskId
```

响应：

```json
{
  "id": "task_001",
  "status": "running",
  "progress": 60,
  "currentStep": "render_clips",
  "errorMessage": ""
}
```

## 4.3 查询任务结果

```http
GET /api/ai-growth-clip/tasks/:taskId/assets
```

响应：

```json
{
  "list": [
    {
      "id": "asset_001",
      "segmentId": "segment_001",
      "scenario": "feed",
      "duration": 15,
      "videoUrl": "https://cdn.example.com/clips/asset_001.mp4",
      "coverUrl": "https://cdn.example.com/covers/asset_001.jpg",
      "title": "退婚当天，她身份曝光",
      "coverText": "全场后悔",
      "recommendationText": "强反转开局，适合推荐流首屏测试。",
      "status": "pending_review"
    }
  ]
}
```

## 4.4 审核素材

```http
POST /api/ai-growth-clip/assets/:assetId/review
Content-Type: application/json
```

```json
{
  "status": "approved",
  "title": "退婚当天，她身份曝光",
  "coverText": "全场后悔",
  "recommendationText": "强反转开局，适合推荐流首屏测试。"
}
```

## 5. 数据库表草案

## 5.1 ai_clip_tasks

```sql
CREATE TABLE ai_clip_tasks (
  id VARCHAR(64) PRIMARY KEY,
  source_content_id VARCHAR(64) NOT NULL,
  source_content_type VARCHAR(32) NOT NULL,
  source_video_url TEXT NOT NULL,
  title VARCHAR(255),
  description TEXT,
  target_scenarios JSON NOT NULL,
  target_durations JSON NOT NULL,
  target_languages JSON NOT NULL,
  status VARCHAR(32) NOT NULL,
  progress INT NOT NULL DEFAULT 0,
  current_step VARCHAR(64),
  error_message TEXT,
  created_by VARCHAR(64),
  created_at BIGINT NOT NULL,
  updated_at BIGINT NOT NULL
);
```

## 5.2 ai_clip_segments

```sql
CREATE TABLE ai_clip_segments (
  id VARCHAR(64) PRIMARY KEY,
  task_id VARCHAR(64) NOT NULL,
  source_content_id VARCHAR(64) NOT NULL,
  start_ms BIGINT NOT NULL,
  end_ms BIGINT NOT NULL,
  duration_ms BIGINT NOT NULL,
  highlight_type VARCHAR(64) NOT NULL,
  score DECIMAL(5, 2) NOT NULL,
  reason TEXT,
  summary TEXT,
  transcript_text TEXT,
  risk_level VARCHAR(16) NOT NULL,
  risk_reason TEXT,
  status VARCHAR(32) NOT NULL,
  created_at BIGINT NOT NULL,
  updated_at BIGINT NOT NULL
);
```

## 5.3 ai_clip_assets

```sql
CREATE TABLE ai_clip_assets (
  id VARCHAR(64) PRIMARY KEY,
  task_id VARCHAR(64) NOT NULL,
  segment_id VARCHAR(64) NOT NULL,
  source_content_id VARCHAR(64) NOT NULL,
  scenario VARCHAR(32) NOT NULL,
  duration INT NOT NULL,
  language VARCHAR(16) NOT NULL,
  video_url TEXT NOT NULL,
  cover_url TEXT,
  subtitle_url TEXT,
  title VARCHAR(255),
  cover_text VARCHAR(255),
  recommendation_text TEXT,
  tags JSON,
  status VARCHAR(32) NOT NULL,
  created_at BIGINT NOT NULL,
  updated_at BIGINT NOT NULL
);
```

## 6. Worker 伪代码

```ts
async function runClipTask(task: AiClipTask) {
  await updateProgress(task.id, 5, 'prepare_video');
  const prepared = await prepareVideo(task.sourceVideoUrl);

  await updateProgress(task.id, 20, 'transcribe_audio');
  const transcript = await transcribeAudio(prepared.audioPath);

  await updateProgress(task.id, 35, 'detect_scenes');
  const scenes = await detectScenes(prepared.videoPath);

  await updateProgress(task.id, 50, 'analyze_highlights');
  const segments = await analyzeHighlights({
    transcript,
    scenes,
    metadata: task,
  });

  await updateProgress(task.id, 70, 'render_clips');
  const rendered = await renderClips({
    videoPath: prepared.videoPath,
    segments,
    durations: task.targetDurations,
  });

  await updateProgress(task.id, 85, 'generate_packaging');
  const assets = await generatePackaging(rendered, task);

  await updateProgress(task.id, 95, 'quality_check');
  await qualityCheck(assets);

  await persistAssets(task.id, assets);
  await updateTaskSucceeded(task.id);
}
```

## 7. 风险和降级方案

| 风险 | 影响 | 降级 |
|---|---|---|
| ASR 慢 | 任务耗时长 | 先支持短视频/单集，限制时长 |
| 高光判断不准 | 采纳率低 | 输出更多候选，运营人工挑选 |
| FFmpeg 渲染失败 | 无法产出视频 | 保留片段时间码，让运营手动剪 |
| LLM 文案不稳定 | 审核成本增加 | 使用结构化输出和 prompt 测试 |
| 视频 URL 权限问题 | worker 无法读取 | 使用短期签名 URL |
| 成本不可控 | 难以上线 | 限制任务额度，记录模型成本 |

