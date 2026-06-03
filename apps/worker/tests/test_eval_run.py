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
    assert result["mean"] == 1.0
    assert result["per_fixture"][0]["score"] == 1.0
