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

> ⚠️ API 与 worker 必须指向**同一套** `DB_PATH` / `STORAGE_DIR`。二者默认都是相对各自目录的
> `./data`、`./storage`，分目录启动会读写**不同**的库而互相看不到数据。下面统一指到仓库根的
> `data/` 与 `storage/`。

```bash
# API（终端 A）—— 监听 :8787，根路径即审核台
cd apps/api && DB_PATH=../../data/agcs.db STORAGE_DIR=../../storage API_PORT=8787 npm start

# Worker（终端 B，轮询模式；--once 处理一条后退出）
cd apps/worker && DB_PATH=../../data/agcs.db STORAGE_DIR=../../storage python3 -m agcs_worker.main
```

浏览器打开 <http://localhost:8787/>（顶部内置「使用指南 / 功能说明」）。

### 智能档位（worker 选其一，环境变量加在终端 B 命令前）

| 档位 | 追加环境变量 | 产出 |
|------|--------------|------|
| 骨架（默认 · 最快 · 免依赖） | 无 | 真实 ffmpeg 切片/封面 + mock 字幕/文案 |
| 真转写 | `ASR_PROVIDER=whisper WHISPER_LANGUAGE=zh` | 真实中文转写（首次下 ~150MB 模型；见 M1）|
| 全真 · reclaude（无需 API key） | 再加 `HIGHLIGHT_PROVIDER=claude-cli PACKAGING_PROVIDER=claude-cli` | 真实高光+文案，走本机 `claude` CLI（见 M3b）|
| 全真 · API key | `HIGHLIGHT_PROVIDER=llm PACKAGING_PROVIDER=llm ANTHROPIC_API_KEY=sk-ant-...` | 真实高光+文案，走 Anthropic SDK |

> 用真转写/真 LLM 前先装依赖：`cd apps/worker && python3 -m pip install -r requirements.txt`。
> 国内访问 huggingface.co 受限时，真转写再加 `HF_ENDPOINT=https://hf-mirror.com` 走镜像下模型。
> 各档位细节见下方 M1 / M2 / M3 / M3b 小节。

## 审核台（M4）

API 在根路径托管一个零依赖的 Web 审核台：起 API + worker 后打开浏览器即可建任务、预览切片、审核通过/驳回。起法见上方 [分开运行](#分开运行)（注意 API 与 worker 要共用同一套 `DB_PATH`/`STORAGE_DIR`）：

```bash
# 终端 A：API（首次需 npm install）
cd apps/api && npm install && DB_PATH=../../data/agcs.db STORAGE_DIR=../../storage npm start
# 终端 B：worker
cd apps/worker && DB_PATH=../../data/agcs.db STORAGE_DIR=../../storage python3 -m agcs_worker.main
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

## 通过 Claude Code CLI 调用（无需 API key，M3b）

没有 `sk-ant-...` API key、但本机已装好 Claude Code（含订阅/中转，如 reclaude）时，可用
`claude-cli` provider：worker 不调用 Anthropic SDK，而是 `claude -p ... --output-format json`
让 Claude Code 用它自己的登录态完成高光选段与文案，无需任何 API key。

```bash
# 需要 `claude` 在 PATH 上（CLAUDE_CLI_BIN 可覆盖二进制名）
HIGHLIGHT_PROVIDER=claude-cli PACKAGING_PROVIDER=claude-cli \
  LLM_MODEL=claude-sonnet-4-6 python3 -m agcs_worker.main --once
```

实现要点（见 [providers/claude_cli.py](apps/worker/agcs_worker/providers/claude_cli.py)）：
复用 `llm_highlight`/`llm_packaging` 的 prompt 与校验逻辑；以 `--strict-mcp-config --setting-sources ""`
跑一次干净的一问一答（不加载 MCP/hooks/skills，否则会拖慢并跑偏）；CLI 让模型手写 JSON，没有
tool_use 的结构保证，因此 prompt 里禁用内嵌英文引号、解析端再做容错修复 + 重试一次。

> 代价：每次调用带 Claude Code 自身约 1 万+ token 的系统提示开销，且消耗你的订阅额度；
> 一条任务 = 1 次高光 + N 次（每高光一次）文案调用。中转订阅（如 reclaude）用于批量自动化前，
> 请自行确认其使用条款是否允许。

## 效果回流 / 效果分析（M5）

审核台内置「效果分析」面板，对接三条 API：

| 端点 | 说明 |
|------|------|
| `POST /api/ai-growth-clip/assets/:id/metrics` | 上报单条素材指标（impressions/clicks/plays/completions/shares，均可选非负整数） |
| `GET  /api/ai-growth-clip/analytics/summary` | 聚合汇总 → `{ totals, byScenario, byHighlightType, suggestions }` |

**Demo 演示步骤：**

1. 起 API + worker，浏览器打开 `http://localhost:8787/`
2. 创建一个任务并等待 worker 处理完成（点「刷新」直到状态 succeeded）
3. 选中任务，在每张素材卡上点几次**「模拟埋点」**（随机上报：固定曝光 50，随机点击/播放/完播/分享）
4. 点「效果分析」区块的**「刷新」**，即可看到非零聚合数据（总览 + 按场景 + 按高光类型表格）以及优化建议

## 测试

```bash
cd apps/api && npm test                 # vitest
cd apps/worker && python3 -m pytest -q   # pytest
```

## M0 范围与后续

M0 为骨架：流水线中 ASR/高光/文案为 mock 适配器，`render_clips`/`select_cover` 为真实 ffmpeg。
后续 M1（faster-whisper）、M2（LLM + 多信号高光 + 评测集）、M3（LLM 文案 + 视觉封面）、M4（admin 审核台）见
[docs/03-mvp-implementation-plan.md](docs/03-mvp-implementation-plan.md)。
