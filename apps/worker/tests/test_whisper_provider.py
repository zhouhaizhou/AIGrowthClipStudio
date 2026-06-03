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
