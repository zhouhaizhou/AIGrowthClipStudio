# M1 — 真实 ASR（faster-whisper）设计 Spec

- 日期：2026-06-03
- 范围：M1 第一项 —— 用 faster-whisper 替换 mock ASR，让 `transcribe_audio` 产出真实字幕。其余流水线步骤（detect_scenes / analyze_highlights / generate_packaging）仍为 mock。
- 依赖前置：M0 已合并到 main（HEAD 28ac36c），worker 的 provider 适配器接缝已就绪。
- 状态：已与用户对齐，待写实现计划。

## 1. 目标

在不改变流水线结构的前提下，新增一个真实的 ASR provider，并通过 env 切换启用：

- `ASR_PROVIDER=mock`（默认）→ 现有 `MockAsrProvider`，零外部依赖。
- `ASR_PROVIDER=whisper`（或 `faster-whisper`）→ 新增 `WhisperAsrProvider`，用 faster-whisper 在 CPU 上转写。

成功标准（M1-ASR 验收）：

1. `WhisperAsrProvider.transcribe(audio_path, duration_ms)` 返回与 `AsrProvider` 契约一致的 `Transcript`（`segments: List[TranscriptSegment]` + `vtt`）。
2. 映射逻辑（whisper segment → TranscriptSegment + VTT）有**不依赖 faster-whisper、零网络**的单元测试（注入 fake model）。
3. env-gate 的集成测试在 `RUN_ASR_TESTS=1` 且 faster-whisper 已安装、`say` 可用时，对一段真实合成语音转写并断言非空。
4. mock-only 运行与现有全部测试不受影响（faster-whisper 未安装时 `import` 不应被触发）。
5. 本会话内用真实 base 模型对一段中文语音验证一次转写输出合理。

## 2. 关键架构决策

### 2.1 复用既有 provider 接缝，pipeline 结构不变

- 契约不动：`AsrProvider.transcribe(self, audio_path: str, duration_ms: int) -> Transcript`（[providers/base.py](../../../apps/worker/agcs_worker/providers/base.py)）。
- `get_providers(config)` 改为按 `config.asr_provider` 选择 ASR，**懒导入** whisper provider，保证 mock 路径与现有测试无需安装 faster-whisper。

### 2.2 在 prepare_video 抽音频，再喂 whisper

- 给 `ffmpeg.py` 新增 `extract_audio(src, out_wav)`：抽 16kHz 单声道 WAV（`-ar 16000 -ac 1 -vn`，pcm_s16le）。
- pipeline 的 `prepare_video` 步骤在有 `src` 时产出 `audio.wav`，并把其路径作为 `transcribe` 的 `audio_path`。
- 理由：更可控、贴合设计文档 `prepare_video → audioPath → transcribe_audio`，并让 ASR provider 只关心“音频→文本”，不耦合视频解码。
- mock provider 忽略 `audio_path`，行为不变。无 `src` 时（stub 路径）`audio_path=""`，mock 照常工作；whisper 路径在无音频时返回空 transcript（见 §6 降级）。

### 2.3 WhisperAsrProvider 用 model 注入实现可测性

- 构造签名：`WhisperAsrProvider(model=None, model_size="base", device="cpu", compute_type="int8", language="")`。
- `model` 注入时（测试）直接用；否则首次 `transcribe` 时懒加载真实 `faster_whisper.WhisperModel(model_size, device=device, compute_type=compute_type)`（懒加载避免构造即下载/占用内存）。
- 这样单测可注入一个 fake model，without faster-whisper installed。

## 3. WhisperAsrProvider 行为

```python
# providers/whisper.py（示意，非最终代码）
class WhisperAsrProvider:
    def __init__(self, model=None, model_size="base", device="cpu",
                 compute_type="int8", language=""):
        self._model = model
        self._model_size = model_size
        self._device = device
        self._compute_type = compute_type
        self._language = language or None

    def _ensure_model(self):
        if self._model is None:
            from faster_whisper import WhisperModel  # 懒导入
            self._model = WhisperModel(self._model_size, device=self._device,
                                       compute_type=self._compute_type)
        return self._model

    def transcribe(self, audio_path: str, duration_ms: int) -> Transcript:
        if not audio_path:
            return Transcript(segments=[], vtt="WEBVTT\n")
        model = self._ensure_model()
        segments, _info = model.transcribe(audio_path, language=self._language)
        segs = []
        for s in segments:  # faster-whisper 返回生成器；.start/.end 为秒(float)
            segs.append(TranscriptSegment(
                start_ms=int(s.start * 1000),
                end_ms=int(s.end * 1000),
                text=s.text.strip(),
            ))
        vtt = "WEBVTT\n\n" + "\n\n".join(
            f"{x.start_ms} --> {x.end_ms}\n{x.text}" for x in segs)
        return Transcript(segments=segs, vtt=vtt)
```

- VTT 格式与 `MockAsrProvider` 保持一致（同样的 `start_ms --> end_ms` 文本形式），下游不需要区分来源。
- `language=""` → `None` → faster-whisper 自动检测语言；可用 `WHISPER_LANGUAGE=zh` 强制中文。

## 4. 配置 / 依赖 / 接线

### 4.1 Config 扩展（config.py + .env.example）

新增字段（均带默认值，不破坏现有）：

- `whisper_model`（`WHISPER_MODEL`，默认 `base`）
- `whisper_device`（`WHISPER_DEVICE`，默认 `cpu`）
- `whisper_compute_type`（`WHISPER_COMPUTE_TYPE`，默认 `int8`）
- `whisper_language`（`WHISPER_LANGUAGE`，默认 ``=自动）

### 4.2 get_providers 接线（pipeline.py）

```python
def get_providers(config):
    return _build_asr(config), MockHighlightProvider(), MockPackagingProvider()

def _build_asr(config):
    if config.asr_provider in ("whisper", "faster-whisper"):
        from .providers.whisper import WhisperAsrProvider  # 懒导入
        return WhisperAsrProvider(
            model_size=config.whisper_model, device=config.whisper_device,
            compute_type=config.whisper_compute_type, language=config.whisper_language)
    return MockAsrProvider()
```

### 4.3 依赖

- 新增 `apps/worker/requirements.txt`，内容 `faster-whisper==1.2.1`。
- README 补充：`cd apps/worker && python3 -m pip install -r requirements.txt`，并说明首次运行会下载模型（联网）。

## 5. 测试策略

### 5.1 单元测试（默认 CI 跑，零网络、不需 faster-whisper）

- `tests/test_whisper_provider.py`：构造 `WhisperAsrProvider(model=FakeModel())`，FakeModel.transcribe 返回 `(iterable_of_fake_segments, fake_info)`，fake segment 有 `.start/.end/.text`。
- 断言：返回的 `Transcript.segments` 的 `start_ms/end_ms/text` 与输入对应（秒→毫秒、text.strip()），`vtt` 以 `WEBVTT` 开头且包含各段。
- 断言：`audio_path=""` 时返回空 segments 的 Transcript，且**不触发懒导入**（不需要 faster-whisper）。

### 5.2 集成测试（env-gate，真实模型）

- `tests/test_whisper_integration.py`，整文件 `pytestmark = pytest.mark.skipif(...)`：
  - skip 条件：`os.environ.get("RUN_ASR_TESTS") != "1"`，或 faster-whisper 未安装，或 `shutil.which("say") is None`（非 macOS）。
- 流程：用 macOS `say`（**默认语音 + 英文文本**，避免依赖未必安装的中文语音）合成一段语音，如 `say -o speech.aiff "this is a speech recognition test"`，用 ffmpeg 转 16k 单声道 wav，`WhisperAsrProvider(model_size="tiny")` 转写，断言 `len(segments) >= 1` 且转写文本非空（whisper 自动检测语言，英文即可证明真实转写链路通）。
- 用 `tiny` 模型让集成测更快；真实使用默认仍是 `base`。
- 产品面向中文短剧，但 ASR 链路验证用英文语音即可（更可移植）；中文质量留给真实素材在使用中验证。

### 5.3 回归

- 运行既有 worker 全量测试，确认 mock 路径与 pipeline 测试不受影响（faster-whisper 未装时不应被 import）。

## 6. 错误处理与降级

- `audio_path` 为空（无 `src` 的 stub 路径）→ 返回空 `Transcript`，pipeline 继续（scenes 空、highlights 仍由 mock 按 duration 生成、assets 照常）。任务仍 succeeded。
- faster-whisper 未安装但 `ASR_PROVIDER=whisper` → 懒导入抛 `ImportError`，由 pipeline 外层（worker `process_once`）捕获并 `mark_failed`，错误信息提示装依赖。
- ffmpeg 抽音频失败 → `extract_audio` 抛 `FfmpegError`，任务 `failed`（与现有 ffmpeg 失败语义一致）。
- 正弦/无语音音频 → whisper 返回空或少量段，pipeline 仍 succeeded（M1 不校验 ASR 质量）。

## 7. 本会话内验证（实现后执行）

1. `pip install -r apps/worker/requirements.txt`（装 faster-whisper + ctranslate2）。
2. 用 `say`（默认语音 + 英文文本，如 "this is a speech recognition test"）合成语音 → ffmpeg 转 16k wav → `WhisperAsrProvider(model_size="base")` 转写 → 打印转写文本，确认合理（非空、大致匹配英文句子）。
3. `ASR_PROVIDER=whisper WHISPER_MODEL=tiny ./scripts/smoke.sh`：正弦样例下 whisper 转出空/少量字幕，但 pipeline 仍 `succeeded`、产物 6 个，验证接线不崩。

## 8. 不做（M1 范围外）

- WhisperX 强制对齐 / 词级时间戳精修、说话人分离（diarization）。
- detect_scenes / analyze_highlights / generate_packaging 仍 mock（后续 M2/M3）。
- GPU / Metal 加速、模型预热与缓存管理、多语言批量。
- 把音频/字幕作为长期工件入对象存储（仍走本地 storage）。

## 9. 受影响文件

- 改：`apps/worker/agcs_worker/config.py`（+4 字段）、`apps/worker/agcs_worker/ffmpeg.py`（+extract_audio）、`apps/worker/agcs_worker/pipeline.py`（prepare 抽音频 + get_providers 接线）、`.env.example`、`README.md`。
- 增：`apps/worker/agcs_worker/providers/whisper.py`、`apps/worker/requirements.txt`、`tests/test_whisper_provider.py`、`tests/test_whisper_integration.py`。
