import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_stage0_frozen_hashes_remain_unchanged():
    expected = {
        "config/universe.yml": "0b6f61d43e753945b7e7931d27359e34a199891eac3f7d59f29c9d17efccec65",
        "config/metric_definition.yml": "13f9415d3e55aacc91e9913652d6e6520d9c681ac3043f09409602c44b5c00c4",
        "docs/stage0_scope.md": "18eeec59594b2cca67cfc7e7f137855ed2b1f018c10623e426340188ac761615",
    }
    assert {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in expected} == expected
