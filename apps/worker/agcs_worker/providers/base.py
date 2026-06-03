from dataclasses import dataclass, field
from typing import List, Optional, Protocol


@dataclass
class TranscriptSegment:
    start_ms: int
    end_ms: int
    text: str


@dataclass
class Transcript:
    segments: List[TranscriptSegment]
    vtt: str


@dataclass
class HighlightSegment:
    start_ms: int
    end_ms: int
    highlight_type: str
    score: float
    reason: str
    summary: str
    transcript_text: str
    risk_level: str
    recommended_scenario: str
    risk_reason: Optional[str] = None


@dataclass
class Packaging:
    title: str
    cover_text: str
    recommendation_text: str
    tags: List[str] = field(default_factory=list)


class AsrProvider(Protocol):
    def transcribe(self, audio_path: str, duration_ms: int) -> Transcript: ...


class HighlightProvider(Protocol):
    def analyze(self, ctx: dict) -> List[HighlightSegment]: ...


class PackagingProvider(Protocol):
    def generate(self, ctx: dict) -> Packaging: ...
