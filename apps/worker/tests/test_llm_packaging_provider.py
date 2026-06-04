from agcs_worker.providers.llm_packaging import ClaudePackagingProvider


class _FakeBlock:
    def __init__(self, payload):
        self.type = "tool_use"
        self.name = "report_packaging"
        self.input = payload


class _FakeResp:
    def __init__(self, payload):
        self.content = [_FakeBlock(payload)]


class _FakeMessages:
    def __init__(self, payload):
        self._payload = payload
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return _FakeResp(self._payload)


class _FakeClient:
    def __init__(self, payload):
        self.messages = _FakeMessages(payload)


def _ctx():
    return {"summary": "女主身份曝光", "transcript_text": "她竟是董事长的女儿。",
            "highlight_type": "reversal", "scenario": "feed", "duration_ms": 15000,
            "tags": ["逆袭"], "content": {"title": "退婚", "category": "短剧"}}


def test_maps_packaging():
    payload = {"title": "退婚当天身份曝光", "coverText": "全场后悔",
               "recommendationText": "强反转开局。", "tags": ["逆袭", "反转"]}
    p = ClaudePackagingProvider(client=_FakeClient(payload)).generate(_ctx())
    assert p.title == "退婚当天身份曝光"
    assert p.cover_text == "全场后悔"
    assert p.recommendation_text == "强反转开局。"
    assert p.tags == ["逆袭", "反转"]


def test_cover_text_truncated_to_12():
    payload = {"title": "t", "coverText": "这是一个非常非常非常长的封面文案超过十二个字",
               "recommendationText": "r", "tags": []}
    p = ClaudePackagingProvider(client=_FakeClient(payload)).generate(_ctx())
    assert len(p.cover_text) == 12


def test_empty_title_and_bad_tags_fall_back():
    payload = {"title": "  ", "coverText": "", "recommendationText": "", "tags": "notalist"}
    p = ClaudePackagingProvider(client=_FakeClient(payload)).generate(_ctx())
    assert p.title == "精彩片段"
    assert p.cover_text == "精彩片段"
    assert p.recommendation_text
    assert p.tags == ["逆袭"]


def test_tags_dedup_strip_and_cap():
    payload = {"title": "t", "coverText": "c", "recommendationText": "r",
               "tags": ["a", "a", " b ", "", "c", "d", "e", "f", "g"]}
    p = ClaudePackagingProvider(client=_FakeClient(payload)).generate(_ctx())
    assert p.tags == ["a", "b", "c", "d", "e", "f"]


def test_missing_tool_block_falls_back():
    class _Empty:
        content = []

    class _C:
        class messages:
            @staticmethod
            def create(**k):
                return _Empty()

    p = ClaudePackagingProvider(client=_C()).generate(_ctx())
    assert p.title == "精彩片段"
