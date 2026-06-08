# AI Growth Clip Studio

AI Growth Clip Studio 是一个面向视频内容供给侧和增长分发侧的 AI 创作工具。

它的目标不是替代完整剪辑软件，而是把公司已有视频内容自动转化为可投放、可推荐、可转化的短视频增长素材，包括高光切片、预告片、广告素材、封面标题、多语言字幕和会员转化物料。

## 项目定位

一句话定位：

> 把已有视频内容自动拆成适合推荐流、广告、会员转化和社媒分发的多版本短视频素材。

核心闭环：

```text
已有视频/剧集
  -> AI 理解内容
  -> 自动识别高光
  -> 自动剪辑多版本素材
  -> 生成封面/标题/字幕/推荐语
  -> admin 审核发布
  -> 前台推荐/广告/会员场景消费
  -> 数据回流优化下一轮素材
```

## 运行

本目录是产品/设计文档。**如何启动项目**（环境要求、一键冒烟、API+worker 分开运行、mock/真转写/全真等智能档位）见仓库根 [README.md](../README.md)。

## 文档目录

- [01-product-plan.md](./01-product-plan.md)：产品规划、用户场景、功能模块。
- [02-technical-architecture.md](./02-technical-architecture.md)：技术架构、服务拆分、核心数据模型。
- [03-mvp-implementation-plan.md](./03-mvp-implementation-plan.md)：MVP 范围、里程碑、接口草案。
- [04-company-integration.md](./04-company-integration.md)：与公司 admin 和前台视频平台的接入方案。
- [05-ai-pipeline-prompts.md](./05-ai-pipeline-prompts.md)：AI 流水线 prompt 设计与输出结构。

## 推荐先做的 MVP

第一版只做一个高价值闭环：

1. admin 选择一个视频或一集短剧。
2. 系统自动抽音频并生成字幕。
3. AI 多信号识别 3 个高光片段（不只靠字幕，详见 03 的 M2 质量验收）。
4. 自动剪出 15s/30s 两种版本，并做 9:16 竖屏画幅重排。
5. 自动选封面帧，生成标题、封面文案、推荐语。
6. 运营预览后保存为增长素材。
7. 后续可绑定推荐位、广告位或详情页推荐。

## 技术关键词

- 视频处理：FFmpeg、PySceneDetect
- ASR 字幕：WhisperX 或 faster-whisper
- AI 分析：LLM + 字幕 + 镜头切分 + 可选行为数据
- 视频剪辑：FFmpeg filter graph
- 任务队列：BullMQ / Celery / Temporal
- 存储：S3/OSS/CDN
- 观测：Langfuse
- 前台消费：xgplayer、推荐流、视频详情页、会员中心

