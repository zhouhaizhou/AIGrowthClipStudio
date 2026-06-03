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


def test_load_config_llm_model_default(monkeypatch):
    monkeypatch.delenv("LLM_MODEL", raising=False)
    assert load_config().llm_model == "claude-sonnet-4-6"


def test_load_config_reads_llm_model_env(monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "claude-opus-4-8")
    assert load_config().llm_model == "claude-opus-4-8"
