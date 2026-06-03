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
            return Transcript(segments=[], vtt="WEBVTT\n\n")
        # duration_ms is unused here: faster-whisper derives timing from the audio file.
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
