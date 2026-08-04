import pytest

from akshare_data_test.quality.stage13_checks import validate_read_only_sql


@pytest.mark.parametrize("sql", [
    "SELECT * FROM x WHERE d <= ? ORDER BY d",
    "WITH x AS (SELECT 1 a) SELECT a FROM x ORDER BY a",
])
def test_read_only_sql_is_accepted(sql):
    validate_read_only_sql(sql)


@pytest.mark.parametrize("sql", [
    "DELETE FROM x", "SELECT 1; DROP TABLE x", "CREATE TABLE x(a INT)",
    "ATTACH 'x.duckdb' AS x", "PRAGMA version",
])
def test_writing_or_multi_statement_sql_is_rejected(sql):
    with pytest.raises(ValueError):
        validate_read_only_sql(sql)
