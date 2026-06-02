# AI 流水线 Prompt 设计

## 1. 输出原则

所有 LLM 输出必须满足：

- JSON 结构化输出。
- 不输出 markdown。
- 不编造不存在的剧情。
- 时间范围必须落在输入字幕范围内。
- 文案必须适合运营审核，不直接发布。
- 高风险内容必须标注 riskLevel。

关于高光识别的定位（与 02 的多信号方案对齐）：

- 高光不是让 LLM 仅凭字幕“猜”。节奏、音频、行为信号在 LLM 之前已经圈出候选时间窗（`candidateWindows`）。
- LLM 的职责是**语义解释和归类**：在候选窗内判断高光类型、评分、给理由、微调边界，并说明依据了哪些信号（`signalEvidence`）。
- LLM 可以拒绝某个候选窗（判定为非高光），也可以在候选窗附近微调边界，但不应凭空提出远离所有信号的片段。

## 2. 高光识别 Prompt

## 2.1 输入结构

```json
{
  "content": {
    "id": "12345",
    "title": "她被退婚后身份曝光",
    "description": "短剧第 1 集",
    "category": "短剧",
    "tags": ["逆袭", "豪门", "复仇"]
  },
  "transcriptSegments": [
    {
      "startMs": 1000,
      "endMs": 8000,
      "text": "你不过是个没人要的女人。"
    }
  ],
  "sceneSegments": [
    {
      "startMs": 0,
      "endMs": 9000,
      "keyframeUrl": "https://example.com/keyframe.jpg",
      "keyframeScore": 0.82
    }
  ],
  "audioFeatures": [
    {
      "startMs": 6000,
      "endMs": 9000,
      "energy": 0.91,
      "silenceRatio": 0.05
    }
  ],
  "analytics": [
    {
      "startMs": 6000,
      "endMs": 9000,
      "completionRate": 0.88,
      "replayHeat": 0.74,
      "dropOff": 0.12
    }
  ],
  "candidateWindows": [
    {
      "startMs": 6000,
      "endMs": 9000,
      "source": "rhythm | audio | analytics | mixed",
      "signalScore": 0.86
    }
  ],
  "targetScenarios": ["feed", "membership"],
  "targetDurations": [15, 30],
  "targetAspectRatios": ["9:16"],
  "clipCount": 3
}
```

## 2.2 Prompt 模板

```text
你是短剧增长素材导演。系统已经用节奏、音频、行为等信号圈出了若干候选时间窗（candidateWindows）。你的任务是结合字幕、镜头、音频和行为信号，对这些候选窗做语义解释和归类，挑出最适合推荐流、广告、会员转化的高光片段。

请遵守：
1. 优先在 candidateWindows 内判断和细化边界；可以在候选窗附近微调，但不要凭空提出远离所有信号的片段。
2. 判断不要只看字幕：结合 audioFeatures（情绪/BGM 高潮）、analytics（完播/回看热点）、keyframeScore（画面强度）综合判断。
3. 若某信号缺失（audioFeatures/analytics/candidateWindows 为空），退化为基于字幕和镜头判断，但要在 signalEvidence 里如实标注依据较弱。
4. 不要编造剧情；片段必须有明确 hook、冲突、反转、悬念或情绪价值。
5. 片段起止时间必须落在输入时间范围内。
6. 优先选择开头 3 秒能吸引用户继续看的片段。
7. 如果片段适合作为会员转化素材，请说明原因。
8. 输出 JSON，不要输出 markdown。

请输出：
{
  "segments": [
    {
      "startMs": number,
      "endMs": number,
      "highlightType": "conflict | reversal | emotion | funny | suspense | membership_conversion | ad_hook",
      "score": number,
      "summary": string,
      "reason": string,
      "signalEvidence": {
        "fromCandidateWindow": boolean,
        "signals": ["transcript" | "rhythm" | "audio" | "analytics" | "keyframe"],
        "note": string
      },
      "recommendedScenarios": ["feed" | "detail" | "ad" | "membership" | "social"],
      "transcriptText": string,
      "riskLevel": "low | medium | high",
      "riskReason": string
    }
  ]
}
```

## 3. 运营包装 Prompt

## 3.1 输入结构

```json
{
  "content": {
    "title": "她被退婚后身份曝光",
    "category": "短剧",
    "tags": ["逆袭", "豪门", "复仇"]
  },
  "clip": {
    "summary": "女主被当众退婚后，真实身份曝光。",
    "transcriptText": "你不过是个没人要的女人。等等，她竟然是董事长的女儿。",
    "highlightType": "reversal",
    "scenario": "feed",
    "duration": 15,
    "aspectRatio": "9:16"
  }
}
```

## 3.2 Prompt 模板

```text
你是视频平台增长运营。请为一个短剧高光片段生成运营包装文案。

要求：
1. 标题适合推荐流点击，但不能夸大到与剧情不符。
2. 封面文案短、有冲突，最多 12 个中文字符。
3. 推荐语说明这个片段适合什么场景。
4. 标签必须从剧情真实信息中提炼。
5. 避免低俗、违法、歧视和明显标题党。
6. 输出 JSON，不要输出 markdown。

输出格式：
{
  "titles": [
    {
      "text": string,
      "style": "conflict | reversal | suspense | emotion",
      "riskLevel": "low | medium | high",
      "reason": string
    }
  ],
  "coverTexts": [
    {
      "text": string,
      "reason": string
    }
  ],
  "recommendationText": string,
  "tags": string[],
  "searchKeywords": string[],
  "membershipCopy": string
}
```

## 4. 质量检查 Prompt

## 4.1 Prompt 模板

```text
你是视频平台内容质检。请检查下面的 AI 生成素材是否适合进入人工审核。

检查维度：
1. 标题是否与片段内容一致。
2. 封面文案是否过度夸张。
3. 推荐语是否准确。
4. 是否存在敏感、低俗、歧视、违法、诱导性表达。
5. 是否适合作为指定场景素材。

输出 JSON：
{
  "passed": boolean,
  "riskLevel": "low | medium | high",
  "issues": [
    {
      "type": "mismatch | exaggeration | sensitive | low_quality | scenario_mismatch",
      "message": string,
      "suggestion": string
    }
  ],
  "overallSuggestion": string
}
```

## 5. 多语言包装 Prompt

## 5.1 Prompt 模板

```text
你是视频平台本地化编辑。请把中文短剧素材文案翻译成目标语言，并保持短视频推荐流的点击吸引力。

要求：
1. 不逐字硬翻，要符合目标语言用户习惯。
2. 人名、地名、作品名保持一致。
3. 封面文案必须短，适合放在图片上。
4. 不新增原剧情不存在的信息。
5. 输出 JSON。

输出：
{
  "language": string,
  "title": string,
  "coverText": string,
  "recommendationText": string,
  "searchKeywords": string[]
}
```

## 6. Prompt 版本管理

建议每个 prompt 都带版本号：

```text
highlight_detection_v2   # v2 起改为多信号两段式（候选窗 + 语义解释），v1 为纯字幕版
packaging_generation_v1
quality_check_v1
localization_v1
```

每次生成素材时记录：

- promptVersion
- model
- inputHash
- outputJson
- latencyMs
- tokenUsage
- cost

这样后续可以分析：

- 哪个 prompt 版本采纳率更高
- 哪个模型成本更低
- 哪类内容高光识别最不稳定

