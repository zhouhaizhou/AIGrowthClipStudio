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
    subprocess.run(["say", "-v", "Samantha", "-o", aiff, "this is a speech recognition test"],
                   check=True, capture_output=True)
    wav = str(tmp_path / "speech.wav")
    ffmpeg.extract_audio(aiff, wav)

    # First run downloads the ~75 MB faster-whisper 'tiny' model from HuggingFace.
    transcript = WhisperAsrProvider(model_size="tiny").transcribe(wav, 0)
    assert len(transcript.segments) >= 1
    text = " ".join(s.text for s in transcript.segments).lower()
    assert text.strip() != ""
    assert ("speech" in text) or ("recognition" in text) or ("test" in text)
    assert transcript.vtt.startswith("WEBVTT")
