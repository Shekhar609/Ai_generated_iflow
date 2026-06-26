from __future__ import annotations

from app.rag.eval.eval import GOLDEN_PATH, _f1, _recall_at_k, load_golden


def test_golden_set_has_20_rows():
    rows = load_golden(GOLDEN_PATH)
    assert len(rows) == 20
    for r in rows:
        assert "prompt" in r
        assert r.get("expected_components")
        assert r.get("expected_sources")


def test_recall_at_k_basic():
    assert _recall_at_k(["a", "b"], ["a"]) == 1.0
    assert _recall_at_k(["x"], ["a"]) == 0.0
    assert _recall_at_k(["a"], ["a", "b"]) == 0.5
    assert _recall_at_k(["a"], []) == 1.0


def test_f1_score_basic():
    assert _f1(["a", "b"], ["a", "b"]) == 1.0
    assert _f1([], []) == 1.0
    assert _f1(["a"], ["b"]) == 0.0
    # precision=1/2, recall=1/1 → F1 = 2*(0.5*1)/(0.5+1) = 0.6667
    val = _f1(["a", "b"], ["a"])
    assert abs(val - (2 * 0.5 * 1 / 1.5)) < 1e-6
