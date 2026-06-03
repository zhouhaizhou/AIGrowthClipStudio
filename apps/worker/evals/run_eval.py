import argparse
import json
import os
import sys
from typing import List, Tuple

from .scoring import top3_hit_rate


def _ctx_from_fixture(fx: dict) -> dict:
    return {
        "duration_ms": fx.get("duration_ms", 0),
        "clip_count": fx.get("clip_count", 3),
        "target_scenarios": fx.get("target_scenarios") or ["feed"],
        "target_durations": fx.get("target_durations") or [15],
        "transcript_segments": fx.get("transcript_segments") or [],
        "content": fx.get("content") or {},
    }


def _predicted_windows(segments) -> List[Tuple[int, int]]:
    ordered = sorted(segments, key=lambda s: s.score, reverse=True)
    return [(s.start_ms, s.end_ms) for s in ordered]


def _gt_windows(fx: dict) -> List[Tuple[int, int]]:
    return [(g["start_ms"], g["end_ms"]) for g in fx.get("ground_truth", [])]


def evaluate(provider, fixtures: List[dict], iou_threshold: float = 0.5) -> dict:
    per_fixture = []
    for fx in fixtures:
        segments = provider.analyze(_ctx_from_fixture(fx))
        score = top3_hit_rate(_predicted_windows(segments), _gt_windows(fx), iou_threshold)
        per_fixture.append({"name": fx.get("name", "?"), "score": score})
    mean = sum(p["score"] for p in per_fixture) / len(per_fixture) if per_fixture else 0.0
    return {"per_fixture": per_fixture, "mean": mean}


def _load_fixtures(dir_path: str) -> List[dict]:
    out = []
    for fn in sorted(os.listdir(dir_path)):
        if fn.endswith(".json"):
            with open(os.path.join(dir_path, fn), "r", encoding="utf-8") as f:
                fx = json.load(f)
            fx.setdefault("name", fn)
            out.append(fx)
    return out


def _build_provider(name: str):
    if name in ("llm", "claude"):
        from agcs_worker.config import load_config
        from agcs_worker.providers.llm_highlight import ClaudeHighlightProvider
        return ClaudeHighlightProvider(model=load_config().llm_model)
    if name != "mock":
        raise ValueError(f"Unknown provider {name!r}; choices: mock, llm, claude")
    from agcs_worker.providers.mock import MockHighlightProvider
    return MockHighlightProvider()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="AGCS highlight eval")
    parser.add_argument("--provider", default="mock")
    parser.add_argument("--fixtures", default=os.path.join(os.path.dirname(__file__), "fixtures"))
    parser.add_argument("--iou", type=float, default=0.5)
    args = parser.parse_args(argv)
    if not os.path.isdir(args.fixtures):
        print(f"error: fixtures directory not found: {args.fixtures}", file=sys.stderr)
        return 1
    result = evaluate(_build_provider(args.provider), _load_fixtures(args.fixtures), args.iou)
    for p in result["per_fixture"]:
        print(f"{p['name']}: top3_hit_rate={p['score']:.3f}")
    print(f"MEAN top3_hit_rate={result['mean']:.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
