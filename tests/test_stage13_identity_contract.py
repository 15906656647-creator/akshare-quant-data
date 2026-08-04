import hashlib
import json
from pathlib import Path

import pandas as pd

from akshare_data_test.stage13_presentation import SQL_MANIFEST_COLUMNS, visible_input_sha256


ROOT = Path(__file__).resolve().parents[1]


def test_formal_run_uses_current_config_hash():
    run = json.loads((ROOT / "reports/stage13/stage13_run.json").read_text(encoding="utf-8"))
    assert run["config_sha256"] == hashlib.sha256((ROOT / "config/stage13.yml").read_bytes()).hexdigest()


def test_presentation_prints_all_identity_hashes():
    run = json.loads((ROOT / "reports/stage13/stage13_run.json").read_text(encoding="utf-8"))
    report = (ROOT / "reports/stage13/stage13_presentation.md").read_text(encoding="utf-8")
    for key in ("config_sha256", "visible_input_sha256", "canonical_sha256", "run_identity_sha256"):
        assert run[key] in report


def test_sql_manifest_has_exact_contract():
    frame = pd.read_csv(ROOT / "reports/stage13/sql/query_manifest.csv")
    assert tuple(frame.columns) == SQL_MANIFEST_COLUMNS
    assert frame.sql_text.str.startswith(("SELECT", "WITH")).all()
    assert frame.source_tables.str.len().gt(0).all()
    for row in frame.itertuples(index=False):
        result = ROOT / f"reports/stage13/sql/{row.query_id}.csv"
        assert row.row_count == len(pd.read_csv(result))
        assert row.result_sha256 == hashlib.sha256(result.read_bytes()).hexdigest()


def test_visible_hash_is_order_and_dtype_stable():
    left = {"x": pd.DataFrame({"b": [2.0, 1.0], "a": ["y", "x"]})}
    right = {"x": pd.DataFrame({"a": ["x", "y"], "b": [1, 2]})}
    assert visible_input_sha256(left) == visible_input_sha256(right)
