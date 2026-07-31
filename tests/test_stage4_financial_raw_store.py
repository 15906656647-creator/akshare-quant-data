import pandas as pd
import pytest

from akshare_data_test.storage.raw_store import RawStore, schema_hash


def test_stage4_path_schema_order_append_only_and_atomic(tmp_path, monkeypatch):
    store = RawStore(tmp_path)
    run_id = "11111111-1111-4111-8111-111111111111"
    path = store.financial_path("stock_financial_abstract", run_id, "002067")
    assert f"run_id={run_id}" in path.as_posix()
    assert "symbol=002067" in path.as_posix()
    left = pd.DataFrame({"a": [1], "b": [2]})
    right = pd.DataFrame({"b": [2], "a": [1]})
    assert schema_hash(left) != schema_hash(right)
    store.write_parquet(left, path)
    with pytest.raises(FileExistsError):
        store.write_parquet(left, path)

    other = store.financial_path(
        "stock_financial_abstract",
        "22222222-2222-4222-8222-222222222222",
        "002067",
    )
    calls = []
    import akshare_data_test.storage.raw_store as module

    real_replace = module.os.replace

    def observed(source, destination):
        calls.append((str(source), str(destination)))
        return real_replace(source, destination)

    monkeypatch.setattr(module.os, "replace", observed)
    store.write_parquet(left, other)
    assert calls and calls[0][0].endswith(".tmp")
    assert not other.with_name("data.parquet.tmp").exists()
