# AIGrowthClipStudio

AI Growth Clip Studio — 把已有视频内容自动拆成推荐流/广告/会员/社媒的多版本短视频素材。
设计文档见 [docs/](docs/)。当前已实现 **M0 可运行骨架**。

## 运行环境

- Node ≥ 22（用内置 `node:sqlite`，本仓库用 24）
- Python ≥ 3.9
- ffmpeg / ffprobe 在 PATH 中

## 快速开始

```bash
# 1) 安装 API 依赖
cd apps/api && npm install && cd ../..

# 2) 一键端到端冒烟（建任务 → 跑 worker → 查产物）
./scripts/smoke.sh
```

## 分开运行

```bash
# API（终端 A）
cd apps/api && npm start            # 监听 :8787

# Worker（终端 B，轮询模式）
cd apps/worker && python3 -m agcs_worker.main
# 或处理一条后退出：python3 -m agcs_worker.main --once
```

## 审核台（M4）

API 在根路径托管一个零依赖的 Web 审核台：起 API + worker 后打开浏览器即可建任务、预览切片、审核通过/驳回。

```bash
cd apps/api && npm install && npm start          # http://localhost:8787/  ← 审核台
cd apps/worker && python3 -m agcs_worker.main      # 另一终端，处理任务
```

## 真实 ASR（可选，M1）

默认 `ASR_PROVIDER=mock`，无需额外依赖。启用 faster-whisper（CPU）：

```bash
cd apps/worker && python3 -m pip install -r requirements.txt   # 装 faster-whisper（首次运行会联网下载模型，base 约 150MB）
ASR_PROVIDER=whisper WHISPER_MODEL=base python3 -m agcs_worker.main --once
```

可配置：`WHISPER_MODEL`（tiny/base/small…，默认 base）、`WHISPER_DEVICE`（默认 cpu）、`WHISPER_COMPUTE_TYPE`（默认 int8）、`WHISPER_LANGUAGE`（留空=自动检测，强制中文填 `zh`）。

> 默认 CPU；如需 GPU（WHISPER_DEVICE=cuda），需另行安装 CUDA 版 CTranslate2，requirements.txt 不含。

## LLM 高光（可选，M2a）

默认 `HIGHLIGHT_PROVIDER=mock`。启用 Claude 高光识别：

```bash
cd apps/worker && python3 -m pip install -r requirements.txt   # 装 anthropic
export ANTHROPIC_API_KEY=sk-...                                # 需要 key
HIGHLIGHT_PROVIDER=llm LLM_MODEL=claude-sonnet-4-6 python3 -m agcs_worker.main --once
```

评测高光质量（对任意 provider 打 Top-3 命中率）：

```bash
cd apps/worker && python3 -m evals.run_eval --provider mock     # 或 --provider llm（需 key）
```

`HIGHLIGHT_PROVIDER` 可取 `mock`（默认）/`llm`（等价 `claude`）。`LLM_MODEL` 默认 `claude-sonnet-4-6`，要更强换 `claude-opus-4-8`。真实标注评测集为后续工作，当前仅含 1 个示例 fixture。

## 多信号候选窗（M2b）

高光识别不只看字幕：worker 会从视频抽**音频能量**（RMS）和**场景切换**信号，融合成候选时间窗，写入 `storage/<task>/signals.json`，并在 `HIGHLIGHT_PROVIDER=llm` 时把候选窗带进 Claude 的 prompt（"优先在信号窗内选高光"）。纯本地、无需 key。

## LLM 文案（M3）

`PACKAGING_PROVIDER=llm` 时用 Claude 为每个高光片段生成标题/封面文案（≤12字）/推荐语/标签（默认 mock）。复用 `LLM_MODEL` 与 `ANTHROPIC_API_KEY`：

```bash
cd apps/worker && python3 -m pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-...
HIGHLIGHT_PROVIDER=llm PACKAGING_PROVIDER=llm python3 -m agcs_worker.main --once
```

## 测试

```bash
cd apps/api && npm test                 # vitest
cd apps/worker && python3 -m pytest -q   # pytest
```

## M0 范围与后续

M0 为骨架：流水线中 ASR/高光/文案为 mock 适配器，`render_clips`/`select_cover` 为真实 ffmpeg。
后续 M1（faster-whisper）、M2（LLM + 多信号高光 + 评测集）、M3（LLM 文案 + 视觉封面）、M4（admin 审核台）见
[docs/03-mvp-implementation-plan.md](docs/03-mvp-implementation-plan.md)。
