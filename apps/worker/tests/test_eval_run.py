import os

from agcs_worker.providers.mock import MockHighlightProvider
from evals.run_eval import evaluate, _load_fixtures

FIX_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "evals", "fixtures"
)


def test_evaluate_mock_on_example_is_perfect_and_deterministic():
    fixtures = _load_fixtures(FIX_DIR)
    assert len(fixtures) >= 1
    result = evaluate(MockHighlightProvider(), fixtures)
    assert 0.0 <= result["mean"] <= 1.0
    # fixture ground_truth is authored to align with MockHighlightProvider's deterministic
    # windows for duration_ms=20000/clip_count=3, so mock scores exactly 1.0.
    assert result["mean"] == 1.0
    assert result["per_fixture"][0]["score"] == 1.0


def test_build_provider_rejects_unknown():
    import pytest
    from evals.run_eval import _build_provider
    with pytest.raises(ValueError):
        _build_provider("claud")  # typo -> must raise, not silently mock
