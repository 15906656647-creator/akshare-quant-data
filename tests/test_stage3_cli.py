import sys

import pytest

from akshare_data_test import cli
from akshare_data_test import market_fetch


def test_fetch_market_cli_passes_stage3_options(monkeypatch, capsys):
    captured = {}

    def fake_run(**kwargs):
        captured.update(kwargs)
        return (
            {
                "status": "PASS",
                "run_id": "11111111-1111-4111-8111-111111111111",
                "daily_success_count": 2,
                "daily_expected_count": 2,
                "spot": {"target_count": 0},
                "manifest_path": "reports/evidence/stage3/x/manifest.json",
            },
            0,
        )

    monkeypatch.setattr(market_fetch, "run_market_fetch", fake_run)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_pipeline.py",
            "fetch-market",
            "--as-of-date",
            "2026-07-27",
            "--run-id",
            "11111111-1111-4111-8111-111111111111",
            "--only-symbol",
            "002067",
            "--skip-spot",
        ],
    )
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 0
    assert captured["only_symbol"] == "002067"
    assert captured["skip_spot"] is True
    assert str(captured["as_of_date"]) == "2026-07-27"
    assert "Market fetch: PASS" in capsys.readouterr().out
