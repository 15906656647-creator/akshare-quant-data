import pandas as pd
import pytest

from akshare_data_test.storage.raw_store import RawStore, schema_hash


def test_raw_paths_include_run_adjust_and_symbol(tmp_path):
    store = RawStore(tmp_path)
    path = store.history_path("abc", "", "002067")
    assert "run_id=abc" in str(path)
    assert "adjust=raw" in str(path)
    assert "symbol=002067" in str(path)


def test_atomic_write_leaves_no_temp_file(tmp_path):
    store = RawStore(tmp_path)
    path = store.history_path("abc", "qfq", "002067")
    store.write_parquet(pd.DataFrame({"中文字段": [1]}), path)
    assert path.exists()
    assert not path.with_name("data.parquet.tmp").exists()
    assert pd.read_parquet(path).columns.tolist() == ["中文字段"]


def test_existing_run_file_is_never_overwritten(tmp_path):
    store = RawStore(tmp_path)
    path = store.history_path("abc", "qfq", "002067")
    store.write_parquet(pd.DataFrame({"x": [1]}), path)
    with pytest.raises(FileExistsError):
        store.write_parquet(pd.DataFrame({"x": [2]}), path)
    assert pd.read_parquet(path)["x"].tolist() == [1]


def test_schema_hash_is_stable_and_order_sensitive():
    frame = pd.DataFrame({"a": pd.Series([1], dtype="int64"), "b": ["x"]})
    assert schema_hash(frame) == schema_hash(frame.copy())
    assert schema_hash(frame) != schema_hash(frame[["b", "a"]])
    assert schema_hash(None) == ""
