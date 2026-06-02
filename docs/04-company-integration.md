# 公司项目接入方案

## 1. 关联项目

Admin 项目：

```text
/Users/jc/codes/admin
```

前台视频平台：

```text
/Users/jc/codesNew/base-frontend
```

AI Growth Clip Studio 建议作为独立服务存在，再通过 API 接入 admin 和前台。

## 2. Admin 接入点

## 2.1 视频内容管理

路径：

```text
/Users/jc/codes/admin/src/admin-pages/contentManage/video
```

建议新增能力：

- 视频列表增加“AI 生成高光”操作。
- 视频详情弹窗增加“增长素材”Tab。
- 剧集信息里支持按单集生成高光。
- 批量选择多条视频生成素材。

入口示例：

```text
视频列表
  -> 操作列
  -> AI 高光
  -> 创建生成任务
```

## 2.2 推荐位管理

路径：

```text
/Users/jc/codes/admin/src/admin-pages/recommendManagement/slot
```

建议新增能力：

- 为某个 slot 选择 AI 素材。
- 根据 slot 类型筛选素材：feed/detail/ad/membership。
- 展示素材历史效果。
- AI 推荐适合当前 slot 的素材。

## 2.3 广告管理

路径：

```text
/Users/jc/codes/admin/src/admin-pages/operation/adManagement
```

建议新增能力：

- 从 AI 素材库选择广告视频。
- 生成广告标题、封面文案。
- 查看广告跳过率和点击率。

## 2.4 功能页面/低代码页面

路径：

```text
/Users/jc/codes/admin/src/admin-pages/operation/featurePage
```

建议新增能力：

- 在页面模块中插入 AI 高光素材。
- 为专题页生成预告片列表。
- AI 根据专题目标推荐素材组合。

## 2.5 数据管理

路径：

```text
/Users/jc/codes/admin/src/admin-pages/dataManagement
```

建议新增能力：

- 内容数据页展示 AI 素材效果。
- 广告数据页展示 AI 广告素材效果。
- 用户数据页分析不同人群对素材类型的偏好。

## 3. 前台接入点

## 3.1 首页推荐

路径：

```text
/Users/jc/codesNew/base-frontend/packages/platform/materials/home-recommend
```

消费方式：

- 推荐卡片可展示 AI 高光视频。
- 卡片封面和标题使用 AI 包装结果。
- 曝光、点击、播放数据回流素材效果表。

## 3.2 全屏 Feed

路径：

```text
/Users/jc/codesNew/base-frontend/packages/platform/pages/fullscreen-feed
/Users/jc/codesNew/base-frontend/packages/platform/materials/fullscreen-feed
```

消费方式：

- 直接播放 15s/30s 高光切片。
- 支持跳转原视频详情。
- 记录完播、滑走、点赞、收藏。

## 3.3 视频详情页

路径：

```text
/Users/jc/codesNew/base-frontend/packages/platform/materials/video-detail
```

消费方式：

- 展示“精彩片段”。
- 展示“本集看点”。
- 详情页推荐区域使用 AI 切片预览。

## 3.4 会员中心

路径：

```text
/Users/jc/codesNew/base-frontend/packages/platform/pages/membership-center
```

消费方式：

- 展示会员专属内容试看片段。
- 使用 AI 生成会员转化话术。
- 按内容类型测试不同素材版本。

## 4. 推荐的数据流

```text
Admin 创建 AI 任务
  -> AI Growth Clip API
  -> Worker 生成素材
  -> Admin 审核通过
  -> 写入素材库
  -> 推荐位/广告位/详情页绑定素材
  -> 前台展示素材
  -> 前台埋点回流
  -> Admin 数据页展示效果
  -> AI 给出下一轮优化建议
```

> ⚠️ 效果回流是跨团队依赖，是整条链路最容易卡住的一环，必须在依赖它（发布第三阶段）之前先确认两件事，否则“数据回流优化”会变成无法落地的 PPT 功能：
>
> 1. **前台埋点能否加自定义维度**：现有埋点系统能否携带并上报 `ai_asset_id` / `ai_segment_id` / `material_version` 等自定义字段。
> 2. **数据看板能否按素材维度聚合**：现有 `dataManagement` 看板能否新增“按 AI 素材 / 高光类型 / 标题模板”聚合的报表口径。
>
> 建议在 MVP 立项时就拉数据团队对齐这两点，把它列为前置条件而非后置优化。

## 5. 与现有接口风格对齐

Admin 当前是 Axios service 风格，建议新增：

```text
src/api/service/aiGrowthClip.ts
```

或并入现有：

```text
src/api/service.ts
```

服务函数示例：

```ts
export function createAiClipTask(data: CreateAiClipTaskBody) {
  return createAxios({
    url: '/truss/ai-growth-clip/tasks',
    method: 'post',
    data,
  });
}

export function getAiClipTask(taskId: string) {
  return createAxios({
    url: `/truss/ai-growth-clip/tasks/${taskId}`,
    method: 'get',
  });
}

export function getAiClipAssets(taskId: string) {
  return createAxios({
    url: `/truss/ai-growth-clip/tasks/${taskId}/assets`,
    method: 'get',
  });
}
```

## 6. 页面最小改造建议

## 6.1 admin 视频列表

新增按钮：

```text
AI 高光
```

点击后弹窗：

- 目标场景
- 目标时长
- 生成数量
- 是否烧录字幕
- 是否生成封面

提交后进入任务中心。

## 6.2 admin 新增菜单

推荐菜单：

```text
AI 创作
  -> 任务中心
  -> 增长素材库
  -> 效果分析
```

## 6.3 前台数据字段

推荐素材对象：

```ts
interface GrowthClipForFrontend {
  id: string;
  sourceContentId: string;
  title: string;
  coverText: string;
  recommendationText: string;
  videoUrl: string;
  coverUrl: string;
  duration: number;
  scenario: 'feed' | 'detail' | 'ad' | 'membership';
  tracking: {
    aiTaskId: string;
    aiAssetId: string;
    aiSegmentId: string;
    promptVersion: string;
  };
}
```

埋点必须带：

- ai_task_id
- ai_asset_id
- ai_segment_id
- source_content_id
- scenario
- material_version

## 7. 权限设计

Admin 权限建议：

- ai_growth_clip.task.view
- ai_growth_clip.task.create
- ai_growth_clip.task.cancel
- ai_growth_clip.asset.view
- ai_growth_clip.asset.review
- ai_growth_clip.asset.publish
- ai_growth_clip.analytics.view

## 8. 发布策略

第一阶段：

- admin 内部可用
- 不接前台自动展示
- 素材可下载

第二阶段：

- 素材可绑定推荐位
- 前台展示 AI 高光
- 埋点回流

第三阶段：

- 自动推荐素材给 slot
- 支持素材 A/B 测试
- AI 基于效果给优化建议

## 9. 与上游内容生产系统的集成钩子

本工具定位是“接住已有/新产出的视频内容继续放大价值”。如果公司另有小说改编/短剧生成平台，二者应在系统层面打通，而不只是选题层面的口头协同：

- **触发钩子**：上游短剧生成完成（视频入库）后，发一个事件/调一个内部接口，自动创建 AI 高光生成任务，省去运营手动发起。
- **接口形态**：复用本工具的创建任务接口即可，由上游带上 `sourceContentId`、`sourceVideoUrl`、`title`、`tags` 等。

```text
小说改编/短剧生成平台
  -> 视频生成完成事件
  -> POST /truss/ai-growth-clip/tasks（自动建任务）
  -> AI Growth Clip 走正常流水线
```

- MVP 阶段可先不接，但接口和字段要预留，避免后续返工。

