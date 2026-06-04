# M2b — 多信号候选窗 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** 从视频抽音频能量 + 场景切换信号，融合成候选高光窗，喂给 LLM 高光 provider（"信号定位、LLM 解释"）。纯本地、零依赖、零 key。

**Architecture:** 新增 `signals.py`（stdlib wave+audioop 算 RMS 能量；ffmpeg 场景检测；融合候选窗）。pipeline 在有真实源时算信号、写 `signals.json`、把 `candidate_windows`+`audio_features` 塞进 highlight ctx。`ClaudeHighlightProvider` 把候选窗写进 prompt。mock 高光忽略，向后兼容。

**Tech Stack:** Python 3.9 stdlib（wave/audioop/subprocess/re）+ ffmpeg。无新依赖。

**对应 spec：** [docs/superpowers/specs/2026-06-04-m2b-multi-signal-candidate-windows-design.md](../specs/2026-06-04-m2b-multi-signal-candidate-windows-design.md)

**前置：** M2a 已在 main（HEAD 549ae1c）。从 `apps/worker` 跑 pytest。

---

## Task 1: signals.py（能量/场景/候选窗）

**Files:** Create `apps/worker/agcs_worker/signals.py`; Test `apps/worker/tests/test_signals.py`

- [ ] **Step 1: 写失败测试 `apps/worker/tests/test_signals.py`**

```python
import math
import struct
import wave

from agcs_worker import signals


def _write_wav(path, sr=16000, dur=6.0, loud_lo=2.0, loud_hi=3.0):
    frames = []
    for i in range(int(sr * dur)):
        t = i / sr
        amp = 30000 if loud_lo < t < loud_hi else 2000
        frames.append(int(amp * math.sin(2 * math.pi * 440 * t)))
    with wave.open(path, "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(b"".join(struct.pack("<h", f) for f in frames))


def test_audio_energy_profile_locates_loud_section(tmp_path):
    p = str(tmp_path / "e.wav")
    _write_wav(p)
    prof = signals.audio_energy_profile(p, window_ms=500)
    assert len(prof) >= 10
    peak = prof.index(max(prof))
    # loud burst 2.0-3.0s -> window index 4 or 5 (500ms windows)
    assert peak in (4, 5)


def test_audio_energy_profile_missing_file_returns_empty():
    assert signals.audio_energy_profile("/no/such.wav") == []


def test_parse_scene_times():
    stderr = "frame:1 ... pts_time:1.234 ...\nframe:2 ... pts_time:5.5 ..."
    assert signals._parse_scene_times(stderr) == [1.234, 5.5]


def test_candidate_windows_locates_energy_peak():
    # 12 windows of 500ms; burst at idx 4-5
    energy = [2000, 2000, 2000, 2000, 21000, 21000, 2000, 2000, 2000, 2000, 2000, 2000]
    cands = signals.candidate_windows(6000, energy, [], window_ms=500, clip_ms=2000, top_k=3)
    assert cands
    top = cands[0]
    assert top["start_ms"] <= 3000 and top["end_ms"] >= 2000   # overlaps the 2-3s burst
    assert "audio" in top["sources"]


def test_candidate_windows_scene_only():
    cands = signals.candidate_windows(10000, [], [1.0, 1.2, 5.0],
                                      window_ms=500, scene_weight=1.0, clip_ms=2000, top_k=3)
    assert cands
    top = cands[0]
    assert top["start_ms"] <= 1500 and top["end_ms"] >= 1000   # the dense scene region
    assert "scene" in top["sources"]


def test_candidate_windows_empty_signals():
    assert signals.candidate_windows(6000, [], []) == []
```

- [ ] **Step 2: 运行确认失败**

Run: `cd apps/worker && python3 -m pytest tests/test_signals.py -q`
Expected: FAIL（No module named 'agcs_worker.signals'）。

- [ ] **Step 3: 写 `apps/worker/agcs_worker/signals.py`**

```python
import audioop
import re
import subprocess
import wave
from typing import List


def audio_energy_profile(wav_path: str, window_ms: int = 500) -> List[int]:
    """RMS energy per window_ms window of a PCM wav. Returns [] on any read failure."""
    try:
        with wave.open(wav_path, "rb") as w:
            sr = w.getframerate()
            sw = w.getsampwidth()
            ch = w.getnchannels()
            data = w.readframes(w.getnframes())
    except (wave.Error, EOFError, OSError):
        return []
    if not data or sr <= 0:
        return []
    if ch > 1:
        data = audioop.tomono(data, sw, 0.5, 0.5)
    win_bytes = max(sw, int(sr * window_ms / 1000) * sw)
    profile = []
    for off in range(0, len(data), win_bytes):
        chunk = data[off:off + win_bytes]
        if len(chunk) >= sw:
            profile.append(audioop.rms(chunk, sw))
    return profile


def _parse_scene_times(stderr: str) -> List[float]:
    return [float(m) for m in re.findall(r"pts_time:([0-9.]+)", stderr or "")]


def scene_change_times(video_path: str, threshold: float = 0.3) -> List[float]:
    """Scene-change timestamps (seconds) via ffmpeg scene detection. Returns [] on failure."""
    cmd = ["ffmpeg", "-hide_banner", "-nostats", "-i", video_path,
           "-vf", f"select='gt(scene,{threshold})',showinfo", "-an", "-f", "null", "-"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    except Exception:
        return []
    return _parse_scene_times(proc.stderr)


def candidate_windows(duration_ms: int, energy_profile: List[int], scene_times: List[float],
                      window_ms: int = 500, scene_weight: float = 1.0,
                      clip_ms: int = 8000, top_k: int = 6) -> List[dict]:
    """Fuse audio energy + scene cuts into ranked candidate windows.
    Each window scored = normalized_energy + scene_weight*scene_count; the highest-scoring
    window centers are expanded to clip_ms-wide windows, overlap-deduped, top_k kept.
    Returns [{start_ms, end_ms, score, sources}], score desc. Empty signals -> []."""
    if duration_ms <= 0:
        return []
    num_windows = (duration_ms + window_ms - 1) // window_ms
    max_e = max(energy_profile) if energy_profile else 0
    scored = []
    for i in range(num_windows):
        win_start = i * window_ms
        win_end = min(win_start + window_ms, duration_ms)
        e = energy_profile[i] if i < len(energy_profile) else 0
        e_norm = (e / max_e) if max_e > 0 else 0.0
        scene_count = sum(1 for t in scene_times if win_start <= t * 1000 < win_end)
        score = e_norm + scene_weight * scene_count
        if score <= 0:
            continue
        sources = []
        if e_norm > 0:
            sources.append("audio")
        if scene_count > 0:
            sources.append("scene")
        center = (win_start + win_end) // 2
        scored.append((score, center, sources))
    scored.sort(key=lambda x: x[0], reverse=True)
    out: List[dict] = []
    for score, center, sources in scored:
        start = max(0, center - clip_ms // 2)
        end = min(duration_ms, start + clip_ms)
        start = max(0, end - clip_ms)
        if any(not (end <= c["start_ms"] or start >= c["end_ms"]) for c in out):
            continue
        out.append({"start_ms": start, "end_ms": end, "score": round(score, 4), "sources": sources})
        if len(out) >= top_k:
            break
    return out
```

- [ ] **Step 4: 运行确认通过**

Run: `python3 -m pytest tests/test_signals.py -q`
Expected: PASS（6 passed）。

- [ ] **Step 5: Commit**

```bash
cd /Users/jc/codesOther/AIGrowthClipStudio && git add -A && git commit -m "feat(m2b/worker): signals.py (audio energy, scene detection, candidate windows)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: pipeline 接入信号 + signals.json

**Files:** Modify `apps/worker/agcs_worker/pipeline.py`; Test `apps/worker/tests/test_pipeline.py`

- [ ] **Step 1: APPEND failing assertion to `tests/test_pipeline.py`** —— 在 `test_run_task_with_real_video` 末尾追加（该测试已 import os，用真实视频）：

```python
    # M2b: signals.json artifact written for a real source
    sig_path = os.path.join(str(tmp_path / "storage"), "task_p", "signals.json")
    assert os.path.exists(sig_path)
    import json as _json
    with open(sig_path, encoding="utf-8") as f:
        sig = _json.load(f)
    assert "candidate_windows" in sig
```

- [ ] **Step 2: 运行确认失败**

Run: `cd apps/worker && python3 -m pytest tests/test_pipeline.py::test_run_task_with_real_video -q`
Expected: FAIL（signals.json 不存在）。

- [ ] **Step 3: 改 `pipeline.py`** —— 顶部 import 增加 `from . import signals`（与 `from . import ffmpeg` 并列）。

- [ ] **Step 4: 在 `pipeline.py` 的 detect_scenes 块之后（写完 scenes.json 之后、analyze_highlights 之前）插入信号计算**：

```python
    # multi-signal candidate windows (audio energy + scene cuts; real source only)
    candidate_wins = []
    audio_features = {}
    if src:
        energy = signals.audio_energy_profile(audio_path) if audio_path else []
        scene_times = signals.scene_change_times(src)
        candidate_wins = signals.candidate_windows(duration_ms, energy, scene_times)
        audio_features = {"window_ms": 500, "energy_len": len(energy)}
        with open(os.path.join(task_dir, "signals.json"), "w", encoding="utf-8") as f:
            json.dump({"candidate_windows": candidate_wins, "audio_features": audio_features,
                       "scene_change_count": len(scene_times)}, f, ensure_ascii=False)
```

- [ ] **Step 5: 在 `pipeline.py` 的 `highlight.analyze({...})` ctx 里增补两键**（在 `"content": {...}` 之后、闭合 `})` 之前）：

```python
        "candidate_windows": candidate_wins,
        "audio_features": audio_features,
```

- [ ] **Step 6: 运行该用例 + 全量回归**

Run: `python3 -m pytest tests/test_pipeline.py -q` → PASS（真实视频用例现写 signals.json）。
Run: `python3 -m pytest -q` → 全量绿（mock 高光忽略新 key；stub 路径无 src 不写 signals.json，其断言不变）。

- [ ] **Step 7: Commit**

```bash
cd /Users/jc/codesOther/AIGrowthClipStudio && git add -A && git commit -m "feat(m2b/worker): compute candidate windows in pipeline + signals.json + feed to highlight ctx

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: ClaudeHighlightProvider 把候选窗写进 prompt

**Files:** Modify `apps/worker/agcs_worker/providers/llm_highlight.py`; Test `apps/worker/tests/test_llm_highlight_provider.py`

- [ ] **Step 1: APPEND failing tests to `tests/test_llm_highlight_provider.py`**

```python
def test_candidate_windows_go_into_prompt():
    raw = [{"startMs": 0, "endMs": 4000, "highlightType": "conflict", "score": 0.9,
            "reason": "", "summary": "", "recommendedScenario": "feed", "riskLevel": "low"}]
    fake = _FakeClient(raw)
    ctx = _ctx()
    ctx["candidate_windows"] = [{"start_ms": 1000, "end_ms": 5000, "score": 0.8}]
    ClaudeHighlightProvider(client=fake).analyze(ctx)
    user_msg = fake.messages.calls[0]["messages"][0]["content"]
    assert "候选窗" in user_msg and "1000-5000" in user_msg


def test_no_candidate_windows_keeps_prompt_plain():
    raw = [{"startMs": 0, "endMs": 4000, "highlightType": "conflict", "score": 0.9,
            "reason": "", "summary": "", "recommendedScenario": "feed", "riskLevel": "low"}]
    fake = _FakeClient(raw)
    ClaudeHighlightProvider(client=fake).analyze(_ctx())  # _ctx has no candidate_windows
    assert "候选窗" not in fake.messages.calls[0]["messages"][0]["content"]
```

- [ ] **Step 2: 运行确认失败**

Run: `cd apps/worker && python3 -m pytest tests/test_llm_highlight_provider.py -q`
Expected: FAIL（candidate-window 段落未进 prompt → `test_candidate_windows_go_into_prompt` 失败）。

- [ ] **Step 3: 改 `llm_highlight.py` 的 `_build_user`** —— 增加 `candidate_windows` 参数与段落。新签名与实现：

```python
def _build_user(content: dict, transcript: list, scenarios: list,
                clip_count: int, duration_ms: int, candidate_windows: list) -> str:
    lines = [f"[{t['start_ms']}-{t['end_ms']}] {t['text']}" for t in transcript]
    msg = (
        f"内容元信息：{_json.dumps(content, ensure_ascii=False)}\n"
        f"视频总时长(ms)：{duration_ms}\n"
        f"目标场景：{scenarios}\n"
        f"需要的高光数量：{clip_count}\n"
        f"字幕（每行 [起-止ms] 文本）：\n" + "\n".join(lines)
    )
    if candidate_windows:
        cw = "\n".join(
            f"[{c['start_ms']}-{c['end_ms']}] score={c.get('score')}" for c in candidate_windows
        )
        msg += ("\n\n信号定位的候选窗（优先在这些窗内选择/细化高光边界，可微调但不要远离所有候选窗）：\n" + cw)
    return msg
```

- [ ] **Step 4: 改 `llm_highlight.py` 的 `analyze`** —— 读 `candidate_windows` 并传入 `_build_user`：

在 `content = ctx.get("content") or {}` 之后加一行：
```python
        candidate_windows = ctx.get("candidate_windows") or []
```
并把 `_build_user(...)` 调用改为：
```python
            messages=[{"role": "user",
                       "content": _build_user(content, transcript, scenarios, clip_count,
                                              duration_ms, candidate_windows)}],
```

- [ ] **Step 5: 运行确认通过 + 全量回归**

Run: `python3 -m pytest tests/test_llm_highlight_provider.py -q` → PASS（9 passed：原 7 + 2 新）。
Run: `python3 -m pytest -q` → 全量绿。

- [ ] **Step 6: Commit**

```bash
cd /Users/jc/codesOther/AIGrowthClipStudio && git add -A && git commit -m "feat(m2b/worker): include signal candidate windows in Claude highlight prompt

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: README 说明 + 演示脚本验证

**Files:** Modify `README.md`; (no new source — Phase B is a runnable demo)

- [ ] **Step 1: 在 `README.md` 的「LLM 高光（可选，M2a）」一节之后追加一小节**（用真正三反引号）：

```markdown
## 多信号候选窗（M2b）

高光识别不只看字幕：worker 会从视频抽**音频能量**（RMS）和**场景切换**信号，融合成候选时间窗，写入 `storage/<task>/signals.json`，并在 `HIGHLIGHT_PROVIDER=llm` 时把候选窗带进 Claude 的 prompt（"优先在信号窗内选高光"）。纯本地、无需 key。
```

IMPORTANT：用正常三反引号；写完确认 README ``` 数为偶数、未破坏其它小节。

- [ ] **Step 2: 演示候选窗真实工作（合成"中段高能"视频）**

Run（一次性验证，不提交产物）：
```bash
cd /Users/jc/codesOther/AIGrowthClipStudio/apps/worker
# 合成 8s 视频，音频在 3-5s 有高能爆发（volume 包络）
ffmpeg -y -f lavfi -i testsrc=duration=8:size=640x360:rate=10 \
  -f lavfi -i "sine=frequency=440:duration=8,volume='if(between(t,3,5),1.0,0.05)':eval=frame" \
  -c:v libx264 -preset ultrafast -c:a aac -shortest /tmp/agcs_burst.mp4 >/dev/null 2>&1
python3 -c "
from agcs_worker import ffmpeg, signals
ffmpeg.extract_audio('/tmp/agcs_burst.mp4', '/tmp/agcs_burst.wav')
energy = signals.audio_energy_profile('/tmp/agcs_burst.wav')
scenes = signals.scene_change_times('/tmp/agcs_burst.mp4')
cands = signals.candidate_windows(8000, energy, scenes, clip_ms=3000, top_k=3)
print('ENERGY windows:', len(energy), 'SCENES:', len(scenes))
print('CANDIDATE WINDOWS:', cands)
"
rm -f /tmp/agcs_burst.mp4 /tmp/agcs_burst.wav
```
Expected: 打印候选窗，top1 覆盖 3-5s 高能区（start_ms 落在约 3000-5000 区间，sources 含 "audio"）。

- [ ] **Step 3: Commit**

```bash
cd /Users/jc/codesOther/AIGrowthClipStudio && git add -A && git commit -m "docs(m2b): multi-signal candidate windows note

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

- **Spec coverage：** 成功标准 1（能量）/2（场景+解析器）/3（融合）→ Task 1；4（pipeline 接入 + signals.json + ctx）→ Task 2；5（prompt 带候选窗）→ Task 3；6（演示）→ Task 4。§2.2 融合 → Task 1 candidate_windows；§4 pipeline → Task 2；§5 provider → Task 3；§7 降级（读失败/ffmpeg 失败/空信号→[]）→ Task 1 的 try/except + 空返回。无缺口。
- **Placeholder scan：** 无 TBD；每步含完整代码 + 命令 + 期望。README 围栏注明。
- **Type consistency：** `audio_energy_profile(wav, window_ms)->list[int]`、`_parse_scene_times(stderr)->list[float]`、`scene_change_times(video, threshold)->list[float]`、`candidate_windows(duration_ms, energy, scene_times, window_ms, scene_weight, clip_ms, top_k)->list[dict{start_ms,end_ms,score,sources}]`、`_build_user(..., candidate_windows)` —— 各 Task 间一致；ctx 新键 `candidate_windows`/`audio_features` 在 Task 2 写、Task 3 读，键名一致；mock 不读这些键（向后兼容）。

---

## Execution: subagent-driven，每 Task 实现→规格评审→质量评审→修复；完成后合并 main + 推送 + 演示。
