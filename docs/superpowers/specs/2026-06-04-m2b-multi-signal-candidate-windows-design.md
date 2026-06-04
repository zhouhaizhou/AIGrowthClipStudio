# M2b — 多信号候选窗 设计 Spec

- 日期：2026-06-04
- 范围：M2 第二个增量（M2b）。从视频抽取**音频能量 + 场景切换**信号，融合成**候选高光时间窗**，喂给高光 provider，让 LLM 在“信号已圈定的窗内做语义解释”，而非纯字幕猜测。这是设计评审强调的核心价值（[02 §4.4]）。
- 依赖前置：M2a 已合并到 main（HEAD 549ae1c）。`HighlightProvider` 接缝与 `ClaudeHighlightProvider` 已就绪；pipeline 的 prepare_video 已抽 `audio.wav`。
- 自主执行：本增量由我自行定稿设计/spec/plan（无人工审批门），按 subagent-driven + 两阶段评审实现，完成后合并并通知。

## 1. 目标

新增**纯信号**的候选窗定位（零外部依赖、零 API key、本机可跑），并把候选窗 + 音频特征传入高光 provider：

成功标准（M2b 验收）：

1. `signals.audio_energy_profile(wav)` 用 stdlib（wave+audioop）算出每窗 RMS 能量曲线；合成"中段高能"wav 上能定位到高能窗（单测，零网络）。
2. `signals.scene_change_times(video)` 用 ffmpeg 场景检测解析切点时间；解析器对罐头 ffmpeg 输出有单测；真实视频上返回列表（可空）。
3. `signals.candidate_windows(...)` 融合能量+场景密度，产出按分数排序的候选窗；合成信号上确定性命中高能区（单测）。
4. pipeline 在有真实源时计算候选窗，并把 `candidate_windows` + `audio_features` 传入 `highlight.analyze(ctx)`；mock 高光忽略（向后兼容），现有全部测试仍绿。
5. `ClaudeHighlightProvider` 在 prompt 中带上候选窗，指示"优先在候选窗内判断/细化边界"；fake-client 单测断言候选窗进了 create() 调用。
6. 提供一个可跑的演示：对一个"中段高能"样例视频打印候选窗（本会话可见，无需 key）。

## 2. 关键架构决策

### 2.1 信号在 LLM 之前，纯本地

- `signals.py` 只用 stdlib（`wave`/`audioop`/`subprocess`/`re`）+ ffmpeg，无新依赖、无网络。
- 与 provider 解耦：signals 产出普通数据（list/tuple），pipeline 负责把它塞进 ctx；mock/LLM provider 各自决定用不用。

### 2.2 候选窗融合（确定性、可测）

- 能量：每 `window_ms`（默认 500ms）一个 RMS，归一化到 [0,1]（除以 max）。
- 场景密度：每窗内的场景切点计数。
- 窗分数 = `energy_norm + scene_weight * scene_count`（`scene_weight` 默认 1.0）。
- 取分数最高的若干窗中心，扩展成 `clip_ms`（默认 8000ms）宽的候选窗，裁剪到 `[0, duration_ms]`，按重叠去重，返回前 `top_k`（默认 6）个，每个带 `score` 与 `sources`（命中的信号集合）。
- 全空信号（无能量/无场景）→ 返回 `[]`（pipeline 仍继续，LLM 退化为纯字幕，与 M2a 一致）。

### 2.3 喂给 provider，但不改 DB 模型

- ctx 增补 `candidate_windows`（`[{start_ms,end_ms,score}]`）与 `audio_features`（如 `{window_ms, energy: [...]}` 摘要）。
- `ClaudeHighlightProvider` 把候选窗写进 user prompt（"以下是信号定位的候选窗，优先在窗内判断、可微调边界"）。
- **不新增 HighlightSegment 字段、不动 DB/schema**：`signalEvidence` 等输出字段留到后续（需要 schema 变更，超出 M2b 范围）。M2b 只做"信号定位 → 进 prompt"。

## 3. signals.py 行为

```python
# apps/worker/agcs_worker/signals.py（示意）
def audio_energy_profile(wav_path: str, window_ms: int = 500) -> list:
    # 读 16-bit PCM wav；多声道转单声道；每 window_ms 一个 audioop.rms → list[int]

def scene_change_times(video_path: str, threshold: float = 0.3) -> list:
    # ffmpeg -vf "select='gt(scene,T)',showinfo" -f null - ；解析 stderr 的 pts_time → list[float] 秒
    # 异常/失败 → []

def candidate_windows(duration_ms, energy_profile, scene_times,
                      window_ms=500, scene_weight=1.0, clip_ms=8000, top_k=6) -> list:
    # 融合 → [{"start_ms","end_ms","score","sources"}]，按 score 降序，重叠去重，截 top_k
```

- 解析器对 ffmpeg `showinfo` 输出（含 `pts_time:1.234`）用正则提取，便于罐头输入单测。

## 4. pipeline 接入

- 在 `prepare_video`/`detect_scenes` 步骤：当有真实 `src` 且已抽出 `audio.wav` 时：
  - `energy = signals.audio_energy_profile(audio_path)`
  - `scene_times = signals.scene_change_times(src)`
  - `cands = signals.candidate_windows(duration_ms, energy, scene_times)`
  - 写一份 `signals.json` 工件（candidate_windows + 能量摘要），便于调试/演示。
- `highlight.analyze(ctx)` 增补 `"candidate_windows": cands` 与 `"audio_features": {"window_ms":500, "energy_len":len(energy)}`。
- 无真实源（stub 路径）→ 不算信号，ctx 不含候选窗（或空列表），行为同 M2a。
- mock 高光忽略新 key（向后兼容）。

## 5. ClaudeHighlightProvider 变更

- `_build_user` 增加候选窗段落（若 ctx 提供）：列出 `[start-end] score`，并加一句"优先在这些信号候选窗内选择/细化高光边界；可微调但不要远离所有候选窗"。
- 无候选窗时 prompt 不变（纯字幕，M2a 行为）。
- 不改输出 schema / 校验（沿用 M2a 的 `_to_segments`）。

## 6. 测试策略

- `tests/test_signals.py`：
  - `audio_energy_profile`：用 stdlib 合成"中段高能"wav（前后低、2–3s 高），断言峰值窗落在高能区。
  - `scene_change_times`：把 ffmpeg `showinfo` 罐头文本喂给解析器（把解析逻辑抽成可单测的 `_parse_scene_times(stderr)`），断言提取出正确 pts_time 列表；并对一个真实样例 run 一次断言"返回 list"。
  - `candidate_windows`：合成能量（中段高）+ 无场景 → 断言 top1 窗与高能区重叠；空信号 → `[]`。
- `tests/test_llm_highlight_provider.py`（追加）：ctx 带 `candidate_windows` 时，断言 fake client 的 `create()` 调用的 user 文本里包含候选窗信息；不带时不含。
- pipeline 回归：mock 路径不受影响；`run_task` 真实视频用例仍 3 segments/3 assets/succeeded，并新增产出 `signals.json`（断言文件存在、含 candidate_windows）。
- 全量 worker 套件保持绿。

## 7. 错误处理与降级

- wav 不可读 / 为空 → `audio_energy_profile` 返回 `[]`；`candidate_windows` 用空能量。
- ffmpeg 场景检测失败/超时 → `scene_change_times` 返回 `[]`（不抛、不中断任务）。
- 全空信号 → 候选窗 `[]` → LLM 退化纯字幕（M2a 行为），任务仍 succeeded。
- 候选窗只进 prompt，不写 DB；不影响 render/persist。

## 8. 本会话演示（实现后）

- 合成一个"中段高能"短视频（ffmpeg 音量包络），跑 `python3 -c` 调 `signals.candidate_windows(...)` 打印候选窗，证明信号定位真实工作（无需 key）。
- 跑既有 smoke：仍产 6 个切片素材，且 `storage/<task>/signals.json` 出现。

## 9. 不做（M2b 范围外）

- `signalEvidence` 输出字段 + HighlightSegment/DB schema 变更（后续）。
- PySceneDetect（用 ffmpeg 内置 scene 检测即可，免依赖）。
- 行为/互动数据信号（完播热力等，需前台埋点，远期）。
- 真实标注评测集（M2c）、LLM 文案（M3）。

## 10. 受影响文件

- 增：`apps/worker/agcs_worker/signals.py`、`tests/test_signals.py`。
- 改：`apps/worker/agcs_worker/pipeline.py`（算信号 + 写 signals.json + ctx 增补）、`apps/worker/agcs_worker/providers/llm_highlight.py`（`_build_user` 候选窗段落）、`tests/test_llm_highlight_provider.py`（追加候选窗 prompt 断言）、`tests/test_pipeline.py`（signals.json 断言）、`README.md`（多信号说明，简短）。
