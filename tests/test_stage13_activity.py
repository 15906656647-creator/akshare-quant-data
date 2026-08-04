import pandas as pd
import pytest

from akshare_data_test.stage13_presentation import ACTIVITY_COMPONENTS, enrich_activity


def _row(symbol, score, missing=None):
    row = {"symbol": symbol, "as_of_date": "2026-07-27", "activity_score": score,
           "score_status": "scored", "event_component_source": "gap_proxy"}
    row.update({name: (None if name == missing else .5) for name in ACTIVITY_COMPONENTS})
    return row


def test_activity_preserves_formal_scores_and_adds_rank():
    source = pd.DataFrame([_row("B", .8), _row("A", .9), _row("C", .7)])
    result = enrich_activity(source)
    assert dict(zip(result.symbol, result.activity_score)) == {"A": .9, "B": .8, "C": .7}
    assert dict(zip(result.symbol, result.activity_rank)) == {"A": 1, "B": 2, "C": 3}
    assert dict(zip(result.symbol, result.activity_percentile)) == pytest.approx({"A": 1, "B": .5, "C": 0})


@pytest.mark.parametrize("missing", list(ACTIVITY_COMPONENTS))
def test_activity_completeness_and_reason_codes(missing):
    result = enrich_activity(pd.DataFrame([_row("A", .5, missing)]))
    assert result.iloc[0].component_completeness == pytest.approx(5 / 6)
    assert missing in result.iloc[0].reason_codes
    assert "score_status:scored" in result.iloc[0].reason_codes
    assert "event_source:gap_proxy" in result.iloc[0].reason_codes


def test_activity_ties_use_stable_min_rank():
    result = enrich_activity(pd.DataFrame([_row("B", .5), _row("A", .5)]))
    assert result.symbol.tolist() == ["A", "B"]
    assert result.activity_rank.astype(int).tolist() == [1, 1]


def test_single_activity_has_full_percentile():
    result = enrich_activity(pd.DataFrame([_row("A", .5)]))
    assert result.iloc[0].activity_percentile == 1
    assert result.iloc[0].component_completeness == 1
