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

## 真实 ASR（可选，M1）

默认 `ASR_PROVIDER=mock`，无需额外依赖。启用 faster-whisper（CPU）：

```bash
cd apps/worker && python3 -m pip install -r requirements.txt   # 装 faster-whisper（首次运行会联网下载模型，base 约 150MB）
ASR_PROVIDER=whisper WHISPER_MODEL=base python3 -m agcs_worker.main --once
```

可配置：`WHISPER_MODEL`（tiny/base/small…，默认 base）、`WHISPER_DEVICE`（默认 cpu）、`WHISPER_COMPUTE_TYPE`（默认 int8）、`WHISPER_LANGUAGE`（留空=自动检测，强制中文填 `zh`）。

> 默认 CPU；如需 GPU（WHISPER_DEVICE=cuda），需另行安装 CUDA 版 CTranslate2，requirements.txt 不含。

## 测试

```bash
cd apps/api && npm test                 # vitest
cd apps/worker && python3 -m pytest -q   # pytest
```

## M0 范围与后续

M0 为骨架：流水线中 ASR/高光/文案为 mock 适配器，`render_clips`/`select_cover` 为真实 ffmpeg。
后续 M1（faster-whisper）、M2（LLM + 多信号高光 + 评测集）、M3（LLM 文案 + 视觉封面）、M4（admin 审核台）见
[docs/03-mvp-implementation-plan.md](docs/03-mvp-implementation-plan.md)。
