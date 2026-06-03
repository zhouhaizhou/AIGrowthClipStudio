# M1 — 真实 ASR（faster-whisper）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用 faster-whisper 在 CPU 上替换 mock ASR，`ASR_PROVIDER=whisper` 时产出真实字幕；mock 仍为默认，pipeline 结构基本不变。

**Architecture:** 新增 `WhisperAsrProvider`（实现既有 `AsrProvider` 契约，model 可注入以便单测），`get_providers()` 按 `config.asr_provider` 懒选择；`prepare_video` 用 ffmpeg 抽 16k 单声道 wav 再交给 transcribe。faster-whisper 懒导入，mock 路径与现有测试零影响。

**Tech Stack:** Python 3.9 / faster-whisper 1.2.1（CTranslate2, CPU int8）/ ffmpeg / pytest。本机 Apple Silicon CPU、无 GPU。

**对应 spec：** [docs/superpowers/specs/2026-06-03-m1-real-asr-faster-whisper-design.md](../specs/2026-06-03-m1-real-asr-faster-whisper-design.md)

**前置：** M0 已在 main（HEAD 28ac36c）。所有命令从 `apps/worker` 运行 pytest（除非另说）。ESM/路径约定见 M0。

---

## File Structure

```text
apps/worker/
  agcs_worker/
    config.py                 # 改：+4 个 whisper 配置字段
    ffmpeg.py                 # 改：+extract_audio()
    pipeline.py               # 改：get_providers 接线 + prepare 抽音频
    providers/whisper.py      # 增：WhisperAsrProvider（model 注入 + 懒加载）
  requirements.txt            # 增：faster-whisper==1.2.1
  tests/
    test_config.py            # 增：whisper 默认值
    test_ffmpeg.py            # 改：+extract_audio 测试
    test_whisper_provider.py  # 增：fake-model 映射单测
    test_get_providers.py     # 增：provider 选择（不加载模型）
    test_whisper_integration.py  # 增：env-gate 真实转写
.env.example                  # 改：+4 个 WHISPER_* 变量
README.md                     # 改：安装 + ASR_PROVIDER 用法
```

---

## Task 1: Config 增加 whisper 字段

**Files:**
- Modify: `apps/worker/agcs_worker/config.py`
- Modify: `.env.example`
- Test: `apps/worker/tests/test_config.py`

- [ ] **Step 1: 写失败测试 `apps/worker/tests/test_config.py`**

```python
from agcs_worker.config import load_config


def test_load_config_whisper_defaults(monkeypatch):
    for k in ["WHISPER_MODEL", "WHISPER_DEVICE", "WHISPER_COMPUTE_TYPE",
              "WHISPER_LANGUAGE", "ASR_PROVIDER"]:
        monkeypatch.delenv(k, raising=False)
    cfg = load_config()
    assert cfg.asr_provider == "mock"
    assert cfg.whisper_model == "base"
    assert cfg.whisper_device == "cpu"
    assert cfg.whisper_compute_type == "int8"
    assert cfg.whisper_language == ""


def test_load_config_reads_whisper_env(monkeypatch):
    monkeypatch.setenv("WHISPER_MODEL", "small")
    monkeypatch.setenv("WHISPER_LANGUAGE", "zh")
    cfg = load_config()
    assert cfg.whisper_model == "small"
    assert cfg.whisper_language == "zh"
```

- [ ] **Step 2: 运行确认失败**

Run: `cd apps/worker && python3 -m pytest tests/test_config.py -q`
Expected: FAIL（`AttributeError: 'Config' object has no attribute 'whisper_model'`）。

- [ ] **Step 3: 改 `apps/worker/agcs_worker/config.py`**

把 `Config` dataclass 改为（在现有字段后追加 4 个）：
```python
@dataclass
class Config:
    db_path: str
    storage_dir: str
    poll_interval_ms: int
    asr_provider: str
    highlight_provider: str
    packaging_provider: str
    whisper_model: str
    whisper_device: str
    whisper_compute_type: str
    whisper_language: str
```

把 `load_config()` 的返回改为（在现有参数后追加 4 个）：
```python
def load_config() -> Config:
    _load_env_file()
    return Config(
        db_path=os.environ.get("DB_PATH", "./data/agcs.db"),
        storage_dir=os.environ.get("STORAGE_DIR", "./storage"),
        poll_interval_ms=int(os.environ.get("WORKER_POLL_INTERVAL_MS", "1000")),
        asr_provider=os.environ.get("ASR_PROVIDER", "mock"),
        highlight_provider=os.environ.get("HIGHLIGHT_PROVIDER", "mock"),
        packaging_provider=os.environ.get("PACKAGING_PROVIDER", "mock"),
        whisper_model=os.environ.get("WHISPER_MODEL", "base"),
        whisper_device=os.environ.get("WHISPER_DEVICE", "cpu"),
        whisper_compute_type=os.environ.get("WHISPER_COMPUTE_TYPE", "int8"),
        whisper_language=os.environ.get("WHISPER_LANGUAGE", ""),
    )
```

- [ ] **Step 4: 改 `.env.example`** — 在末尾追加：

```bash
WHISPER_MODEL=base
WHISPER_DEVICE=cpu
WHISPER_COMPUTE_TYPE=int8
WHISPER_LANGUAGE=
```

- [ ] **Step 5: 运行确认通过**

Run: `python3 -m pytest tests/test_config.py -q`
Expected: PASS（2 passed）。

> 注意：其它构造 `Config(...)` 的测试（如 test_pipeline.py / test_main.py 里的 `_cfg`）此时会因缺少新字段而 **TypeError**。这是预期的——Task 4 会更新它们。本步只需 test_config.py 通过；不要在此修改其它测试。

- [ ] **Step 6: Commit**

```bash
cd /Users/jc/codesOther/AIGrowthClipStudio && git add -A && git commit -m "feat(m1/worker): add whisper config fields + .env.example

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: ffmpeg.extract_audio

**Files:**
- Modify: `apps/worker/agcs_worker/ffmpeg.py`
- Test: `apps/worker/tests/test_ffmpeg.py`

- [ ] **Step 1: 追加失败测试到 `apps/worker/tests/test_ffmpeg.py`**

在文件末尾追加：
```python
def test_extract_audio(sample_video, tmp_path):
    out = str(tmp_path / "audio.wav")
    ffmpeg.extract_audio(sample_video, out)
    assert os.path.exists(out) and os.path.getsize(out) > 0
    # 16k 单声道 wav 应能被 ffprobe 读出时长
    assert ffmpeg.probe_duration_ms(out) is not None
```

- [ ] **Step 2: 运行确认失败**

Run: `cd apps/worker && python3 -m pytest tests/test_ffmpeg.py::test_extract_audio -q`
Expected: FAIL（`AttributeError: module 'agcs_worker.ffmpeg' has no attribute 'extract_audio'`）。

- [ ] **Step 3: 在 `apps/worker/agcs_worker/ffmpeg.py` 末尾追加**

```python
def extract_audio(src: str, out_path: str) -> None:
    _run(["ffmpeg", "-y", "-i", src, "-vn", "-ac", "1", "-ar", "16000",
          "-c:a", "pcm_s16le", out_path])
```

- [ ] **Step 4: 运行确认通过**

Run: `python3 -m pytest tests/test_ffmpeg.py -q`
Expected: PASS（test_ffmpeg 全部通过，含新增 extract_audio）。

- [ ] **Step 5: Commit**

```bash
cd /Users/jc/codesOther/AIGrowthClipStudio && git add -A && git commit -m "feat(m1/worker): ffmpeg.extract_audio (16k mono wav)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: WhisperAsrProvider（model 注入 + 映射）

**Files:**
- Create: `apps/worker/agcs_worker/providers/whisper.py`
- Test: `apps/worker/tests/test_whisper_provider.py`

- [ ] **Step 1: 写失败测试 `apps/worker/tests/test_whisper_provider.py`**

```python
from agcs_worker.providers.whisper import WhisperAsrProvider


class _FakeSeg:
    def __init__(self, start, end, text):
        self.start = start
        self.end = end
        self.text = text


class _FakeModel:
    def __init__(self):
        self.calls = []

    def transcribe(self, audio_path, language=None):
        self.calls.append((audio_path, language))
        return iter([_FakeSeg(0.0, 1.5, " 你好 "), _FakeSeg(1.5, 3.0, "世界")]), {"language": "zh"}


def test_maps_segments_and_builds_vtt():
    p = WhisperAsrProvider(model=_FakeModel())
    t = p.transcribe("/tmp/a.wav", 3000)
    assert len(t.segments) == 2
    assert t.segments[0].start_ms == 0
    assert t.segments[0].end_ms == 1500
    assert t.segments[0].text == "你好"   # stripped
    assert t.segments[1].text == "世界"
    assert t.vtt.startswith("WEBVTT")
    assert "你好" in t.vtt


def test_empty_audio_returns_empty_without_model():
    # model=None + 空 audio_path 必须不触发懒加载（不需要 faster-whisper）
    p = WhisperAsrProvider(model=None, model_size="tiny")
    t = p.transcribe("", 0)
    assert t.segments == []
    assert t.vtt.startswith("WEBVTT")


def test_passes_language_to_model():
    fake = _FakeModel()
    WhisperAsrProvider(model=fake, language="zh").transcribe("/tmp/a.wav", 1000)
    assert fake.calls[0][1] == "zh"
```

- [ ] **Step 2: 运行确认失败**

Run: `cd apps/worker && python3 -m pytest tests/test_whisper_provider.py -q`
Expected: FAIL（`No module named 'agcs_worker.providers.whisper'`）。

- [ ] **Step 3: 写 `apps/worker/agcs_worker/providers/whisper.py`**

```python
from typing import Optional

from .base import Transcript, TranscriptSegment


class WhisperAsrProvider:
    """Real ASR via faster-whisper. `model` is injectable for tests; when None it is
    lazily constructed on first use so importing this module never requires faster-whisper."""

    def __init__(self, model=None, model_size: str = "base", device: str = "cpu",
                 compute_type: str = "int8", language: str = ""):
        self._model = model
        self._model_size = model_size
        self._device = device
        self._compute_type = compute_type
        self._language: Optional[str] = language or None

    def _ensure_model(self):
        if self._model is None:
            from faster_whisper import WhisperModel  # lazy: only needed for real transcription
            self._model = WhisperModel(
                self._model_size, device=self._device, compute_type=self._compute_type
            )
        return self._model

    def transcribe(self, audio_path: str, duration_ms: int) -> Transcript:
        if not audio_path:
            return Transcript(segments=[], vtt="WEBVTT\n")
        model = self._ensure_model()
        raw_segments, _info = model.transcribe(audio_path, language=self._language)
        segs = []
        for s in raw_segments:
            segs.append(TranscriptSegment(
                start_ms=int(s.start * 1000),
                end_ms=int(s.end * 1000),
                text=s.text.strip(),
            ))
        vtt = "WEBVTT\n\n" + "\n\n".join(
            f"{x.start_ms} --> {x.end_ms}\n{x.text}" for x in segs
        )
        return Transcript(segments=segs, vtt=vtt)
```

- [ ] **Step 4: 运行确认通过**

Run: `python3 -m pytest tests/test_whisper_provider.py -q`
Expected: PASS（3 passed）—— 注意全程未 import faster_whisper（model 注入 / 空音频短路）。

- [ ] **Step 5: Commit**

```bash
cd /Users/jc/codesOther/AIGrowthClipStudio && git add -A && git commit -m "feat(m1/worker): WhisperAsrProvider (injectable model, lazy load, segment->VTT mapping)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: 接线 get_providers + prepare 抽音频

**Files:**
- Modify: `apps/worker/agcs_worker/pipeline.py`
- Modify: `apps/worker/tests/test_pipeline.py`（更新 `_cfg` 以含新字段）
- Modify: `apps/worker/tests/test_main.py`（更新 `_cfg` 以含新字段）
- Test: `apps/worker/tests/test_get_providers.py`

- [ ] **Step 1: 写失败测试 `apps/worker/tests/test_get_providers.py`**

```python
from agcs_worker.config import Config
from agcs_worker.pipeline import get_providers, _build_asr
from agcs_worker.providers.mock import MockAsrProvider
from agcs_worker.providers.whisper import WhisperAsrProvider


def _cfg(asr):
    return Config(db_path="", storage_dir="", poll_interval_ms=1000,
                  asr_provider=asr, highlight_provider="mock", packaging_provider="mock",
                  whisper_model="base", whisper_device="cpu", whisper_compute_type="int8",
                  whisper_language="")


def test_default_uses_mock_asr():
    asr, _h, _p = get_providers(_cfg("mock"))
    assert isinstance(asr, MockAsrProvider)


def test_whisper_selects_whisper_provider_without_loading_model():
    # 构造 provider 不应加载/下载 faster-whisper 模型（懒加载）
    asr = _build_asr(_cfg("whisper"))
    assert isinstance(asr, WhisperAsrProvider)
```

- [ ] **Step 2: 运行确认失败**

Run: `cd apps/worker && python3 -m pytest tests/test_get_providers.py -q`
Expected: FAIL（`ImportError: cannot import name '_build_asr'`）。

- [ ] **Step 3: 改 `apps/worker/agcs_worker/pipeline.py` 的 get_providers**

把现有：
```python
def get_providers(config: Config):
    # M0 仅支持 mock；真实 provider 在后续里程碑接入
    return MockAsrProvider(), MockHighlightProvider(), MockPackagingProvider()
```
替换为：
```python
def get_providers(config: Config):
    return _build_asr(config), MockHighlightProvider(), MockPackagingProvider()


def _build_asr(config: Config):
    if config.asr_provider in ("whisper", "faster-whisper"):
        from .providers.whisper import WhisperAsrProvider  # lazy: avoid import on mock path
        return WhisperAsrProvider(
            model_size=config.whisper_model,
            device=config.whisper_device,
            compute_type=config.whisper_compute_type,
            language=config.whisper_language,
        )
    return MockAsrProvider()
```

- [ ] **Step 4: 改 `pipeline.py` 的 prepare_video + transcribe**

把现有这段：
```python
    # prepare_video
    dbm.update_progress(conn, task_id, 5, "prepare_video")
    duration_ms = ffmpeg.probe_duration_ms(src) if src else None
    if not duration_ms:
        duration_ms = 20000

    # transcribe_audio (mock)
    dbm.update_progress(conn, task_id, 20, "transcribe_audio")
    transcript = asr.transcribe(src or "", duration_ms)
```
替换为：
```python
    # prepare_video（有源时抽 16k 单声道 wav 供真实 ASR；mock 忽略该路径）
    dbm.update_progress(conn, task_id, 5, "prepare_video")
    duration_ms = ffmpeg.probe_duration_ms(src) if src else None
    if not duration_ms:
        duration_ms = 20000
    audio_path = ""
    if src:
        audio_path = os.path.join(task_dir, "audio.wav")
        ffmpeg.extract_audio(src, audio_path)

    # transcribe_audio
    dbm.update_progress(conn, task_id, 20, "transcribe_audio")
    transcript = asr.transcribe(audio_path, duration_ms)
```

- [ ] **Step 5: 更新两个测试里的 `_cfg` 以含新字段**

`apps/worker/tests/test_pipeline.py` 的 `_cfg`：把
```python
def _cfg(tmp_path):
    return Config(db_path="", storage_dir=str(tmp_path / "storage"),
                  poll_interval_ms=1000, asr_provider="mock",
                  highlight_provider="mock", packaging_provider="mock")
```
改为：
```python
def _cfg(tmp_path):
    return Config(db_path="", storage_dir=str(tmp_path / "storage"),
                  poll_interval_ms=1000, asr_provider="mock",
                  highlight_provider="mock", packaging_provider="mock",
                  whisper_model="base", whisper_device="cpu",
                  whisper_compute_type="int8", whisper_language="")
```

`apps/worker/tests/test_main.py` 的 `_cfg`：同样在 `packaging_provider="mock"` 后追加
```python
                  whisper_model="base", whisper_device="cpu",
                  whisper_compute_type="int8", whisper_language="",
```
（保持其余不变。）

- [ ] **Step 6: 运行全量 worker 测试确认通过**

Run: `python3 -m pytest -q`
Expected: PASS。test_get_providers（2）、test_config（2）、test_whisper_provider（3）、以及更新 `_cfg` 后的 test_pipeline（2）/ test_main（2）全部通过；test_whisper_integration 被 skip。预计约 22 passed, 1 skipped（数量以实际为准）。
说明：test_pipeline 的真实视频用例现在会额外调用 `extract_audio` 产出 `audio.wav`，仍走 mock ASR，断言不变（3 segments / 3 assets / succeeded）。

- [ ] **Step 7: Commit**

```bash
cd /Users/jc/codesOther/AIGrowthClipStudio && git add -A && git commit -m "feat(m1/worker): wire whisper provider selection + extract audio in prepare_video

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: requirements.txt + README

**Files:**
- Create: `apps/worker/requirements.txt`
- Modify: `README.md`

- [ ] **Step 1: 写 `apps/worker/requirements.txt`**

```text
faster-whisper==1.2.1
```

- [ ] **Step 2: 在 `README.md` 的「测试」一节之前（或「分开运行」一节内）补一段真实 ASR 说明**

在 README 中加入如下小节（放在 Worker 运行说明附近）：
```markdown
## 真实 ASR（可选，M1）

默认 `ASR_PROVIDER=mock`，无需额外依赖。启用 faster-whisper：

​```bash
cd apps/worker && python3 -m pip install -r requirements.txt   # 装 faster-whisper（首次运行会联网下载模型）
ASR_PROVIDER=whisper WHISPER_MODEL=base python3 -m agcs_worker.main --once
​```

可配置：`WHISPER_MODEL`（tiny/base/small…，默认 base）、`WHISPER_DEVICE`（默认 cpu）、`WHISPER_COMPUTE_TYPE`（默认 int8）、`WHISPER_LANGUAGE`（留空=自动检测）。
```

（写入 README.md 时用真正的三反引号 ```bash，上面的 `​```` 仅为转义避免歧义。）

- [ ] **Step 3: Commit**

```bash
cd /Users/jc/codesOther/AIGrowthClipStudio && git add -A && git commit -m "docs(m1): worker requirements + real-ASR run docs

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: 集成测试（env-gate）+ 安装 + 真实验证

**Files:**
- Create: `apps/worker/tests/test_whisper_integration.py`

- [ ] **Step 1: 写 `apps/worker/tests/test_whisper_integration.py`**

```python
import os
import shutil
import subprocess

import pytest

_RUN = os.environ.get("RUN_ASR_TESTS") == "1"
try:
    import faster_whisper  # noqa: F401
    _HAS_FW = True
except Exception:
    _HAS_FW = False

pytestmark = pytest.mark.skipif(
    not (_RUN and _HAS_FW and shutil.which("say") and shutil.which("ffmpeg")),
    reason="needs RUN_ASR_TESTS=1, faster-whisper installed, macOS `say`, ffmpeg",
)


def test_real_transcription_of_synthetic_speech(tmp_path):
    from agcs_worker import ffmpeg
    from agcs_worker.providers.whisper import WhisperAsrProvider

    aiff = str(tmp_path / "speech.aiff")
    subprocess.run(["say", "-o", aiff, "this is a speech recognition test"],
                   check=True, capture_output=True)
    wav = str(tmp_path / "speech.wav")
    ffmpeg.extract_audio(aiff, wav)

    transcript = WhisperAsrProvider(model_size="tiny").transcribe(wav, 0)
    assert len(transcript.segments) >= 1
    text = " ".join(s.text for s in transcript.segments).lower()
    assert text.strip() != ""
    assert ("speech" in text) or ("recognition" in text) or ("test" in text)
```

- [ ] **Step 2: 确认默认（无 env）下该测试被 skip，全量套件仍快**

Run: `cd apps/worker && python3 -m pytest -q`
Expected: 之前的用例全 PASS，`test_whisper_integration` 显示为 1 skipped。

- [ ] **Step 3: 安装 faster-whisper**

Run: `cd /Users/jc/codesOther/AIGrowthClipStudio/apps/worker && python3 -m pip install -r requirements.txt`
Expected: 成功安装 faster-whisper + ctranslate2（arm64 macOS、py3.9 wheel）。若安装失败，读报错并报告（不要自行降级版本，先报告由 controller 决定）。

- [ ] **Step 4: 真实跑通集成测试（联网下载 tiny 模型）**

Run: `cd /Users/jc/codesOther/AIGrowthClipStudio/apps/worker && RUN_ASR_TESTS=1 python3 -m pytest tests/test_whisper_integration.py -q -s`
Expected: PASS（1 passed）。首次会下载 tiny 模型（联网，约几十 MB）。若模型下载被网络阻断，报告实际错误。

- [ ] **Step 5: 用 base 模型做一次人工真实验证**

Run（一次性脚本，验证默认 base 模型链路）：
```bash
cd /Users/jc/codesOther/AIGrowthClipStudio/apps/worker
say -o /tmp/agcs_speech.aiff "this is a speech recognition test"
python3 -c "
from agcs_worker import ffmpeg
from agcs_worker.providers.whisper import WhisperAsrProvider
ffmpeg.extract_audio('/tmp/agcs_speech.aiff', '/tmp/agcs_speech.wav')
t = WhisperAsrProvider(model_size='base').transcribe('/tmp/agcs_speech.wav', 0)
print('SEGMENTS:', len(t.segments))
print('TEXT:', ' '.join(s.text for s in t.segments))
"
rm -f /tmp/agcs_speech.aiff /tmp/agcs_speech.wav
```
Expected: 打印 SEGMENTS >= 1，TEXT 大致是 "this is a speech recognition test"（允许小幅差异）。

- [ ] **Step 6: 用 whisper 跑一次 smoke，验证接线不崩**

Run: `cd /Users/jc/codesOther/AIGrowthClipStudio && ASR_PROVIDER=whisper WHISPER_MODEL=tiny ./scripts/smoke.sh`
Expected: 正弦样例无语音 → whisper 转出空/极少字幕，但 `task: ... succeeded`、`assets:` 仍 6 条；脚本退出后 `lsof -ti tcp:8787` 为空。证明真实 ASR 接入后流水线端到端不崩。

- [ ] **Step 7: Commit**

```bash
cd /Users/jc/codesOther/AIGrowthClipStudio && git add -A && git commit -m "test(m1/worker): env-gated real-ASR integration test (say + faster-whisper)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review（计划自检结论）

- **Spec coverage：** 成功标准 1（契约一致）→ Task 3；2（fake-model 单测零依赖）→ Task 3 的 test_whisper_provider；3（env-gate 集成测）→ Task 6；4（mock 路径/现有测试不受影响、未装时不 import）→ Task 4 Step6 全量回归 + 懒导入（Task 3/4）；5（本会话真实验证）→ Task 6 Step3-6。§2.2 抽音频 → Task 2 + Task 4；§4 配置/依赖/接线 → Task 1/5/4；§6 降级（空音频空 transcript、ImportError→mark_failed）→ Task 3 空音频短路 + 懒导入（外层 process_once 已捕获）；§7 验证 → Task 6。无缺口。
- **Placeholder scan：** 无 TBD/“稍后”。每个代码步骤含完整代码与确切命令、期望输出。README 三反引号转义已注明。
- **Type consistency：** `WhisperAsrProvider(model, model_size, device, compute_type, language)`、`transcribe(audio_path, duration_ms) -> Transcript`、`extract_audio(src, out_path)`、`_build_asr(config)`、`get_providers(config)`、`Config` 新增 4 字段——在 Task 1/2/3/4/6 间签名一致；`Config(...)` 的所有构造点（test_pipeline/_cfg、test_main/_cfg、test_get_providers/_cfg）都在 Task 4/Task 6 同步补齐新字段，无遗漏。

---

## Execution Handoff

计划已保存。两种执行方式：

1. **Subagent-Driven（推荐）** — 每个 Task 派全新 subagent，任务间两阶段审查，迭代快。
2. **Inline Execution** — 当前会话用 executing-plans 批量执行、带检查点。

> 注意：Task 6 含 `pip install` + 模型下载（联网）；若执行时网络受限，该任务的真实验证步可能受阻，会如实报告。
