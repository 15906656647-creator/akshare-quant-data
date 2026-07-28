"""
Stage 0 configuration tests (static checks only).

These tests validate the frozen configuration files without requiring
pytest, PyYAML, or any network access. Stage 1 will install full dependencies.

Run: python tests/test_stage0_config.py
"""

import json
import os
import re
import sys
from pathlib import Path

# ---- YAML parser (standard-library fallback) --------------------------------


def _parse_yaml_simple(text):
    """Parse a minimal subset of YAML sufficient for our config files.

    Supports:
    - comments starting with #
    - scalar keys and values
    - nested mappings via indentation (2-space)
    - sequences (lines starting with '- ')
    - quoted strings (single and double)
    - boolean literals: true/false
    - integer and float literals
    """
    lines = text.splitlines()
    result = {}
    stack = []
    current_dict = result
    current_list_key = None

    for line in lines:
        stripped = line.rstrip()
        if not stripped or stripped.lstrip().startswith("#"):
            continue

        indent = len(line) - len(line.lstrip())
        content = stripped

        if content.lstrip().startswith("- "):
            value_str = content.lstrip()[2:].strip()
            value = _parse_scalar(value_str)
            if current_list_key is not None:
                current_dict.setdefault(current_list_key, []).append(value)
            continue

        if ":" in content:
            key_part, _, val_part = content.partition(":")
            key = key_part.strip().strip("'\"")
            val_part = val_part.strip()

            while stack and indent <= stack[-1][0]:
                stack.pop()
            if stack:
                current_dict = stack[-1][1]
            else:
                current_dict = result

            if val_part:
                value = _parse_scalar(val_part)
                current_dict[key] = value
                current_list_key = None
            else:
                current_dict[key] = {}
                stack.append((indent, current_dict))
                current_dict = current_dict[key]
                current_list_key = key

    return result


def _parse_scalar(val):
    """Parse a YAML scalar value."""
    val = val.strip().strip("'\"")
    if val.lower() == "true":
        return True
    if val.lower() == "false":
        return False
    if val.lower() == "null" or val == "~":
        return None
    try:
        if "." in val or "e" in val.lower():
            return float(val)
        return int(val)
    except ValueError:
        return val


def load_yaml(path):
    """Load a YAML file, trying PyYAML first then falling back to simple parser."""
    try:
        import yaml
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    except ImportError:
        with open(path, "r", encoding="utf-8") as f:
            return _parse_yaml_simple(f.read())


# ---- Helpers -----------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = REPO_ROOT / "config"

EXPECTED_STOCKS = [
    "002067", "002600", "002230", "600763",
    "603259", "603799", "601012", "600438",
    "002361", "601500", "600231", "300274",
    "601636", "002129", "000100", "300433",
]

SH_PREFIXES = ("600", "601", "603")
SZ_PREFIXES = ("000", "002", "300")

EXPECTED_MA_WINDOWS = [3, 5, 7, 10, 13, 20, 21]


def classify_exchange(symbol):
    symbol = str(symbol)
    if any(symbol.startswith(p) for p in SH_PREFIXES):
        return "SH"
    if any(symbol.startswith(p) for p in SZ_PREFIXES):
        return "SZ"
    return "UNKNOWN"


# ---- Test functions ----------------------------------------------------------

results = []


def check(name, condition, detail=""):
    msg = "PASS: " + name if condition else "FAIL: " + name
    if detail and not condition:
        msg += "  [" + str(detail) + "]"
    results.append((condition, msg))
    print(msg)


# 1. Both YAML files parse
universe = load_yaml(CONFIG_DIR / "universe.yml")
metrics = load_yaml(CONFIG_DIR / "metric_definition.yml")
check("1a. universe.yml parses", isinstance(universe, dict))
check("1b. metric_definition.yml parses", isinstance(metrics, dict))

# 2. Stock count exactly 16
stocks = universe.get("stocks", [])
check("2. Stock count is 16", len(stocks) == 16, "got " + str(len(stocks)))

# 3. All symbols are 6-character strings
all_str = all(isinstance(s.get("symbol"), str) for s in stocks)
all_len6 = all(len(str(s.get("symbol", ""))) == 6 for s in stocks)
check("3a. All symbols are strings", all_str)
check("3b. All symbols are length 6", all_len6)

# 4. No duplicate symbols
symbols = [str(s.get("symbol", "")) for s in stocks]
dupes = [s for s in symbols if symbols.count(s) > 1]
check("4. No duplicate symbols", len(symbols) == len(set(symbols)),
      "duplicates: " + str(dupes))

# 4b. Symbols match expected list
check("4b. Symbols match expected 16-stock list",
      sorted(symbols) == sorted(EXPECTED_STOCKS),
      "expected=" + str(sorted(EXPECTED_STOCKS)) + ", got=" + str(sorted(symbols)))

# 5. Exchange, symbol_em, market_lower mappings correct
all_exchange_ok = True
all_symbol_em_ok = True
all_market_lower_ok = True
all_mapping_present = True
for s in stocks:
    sym = str(s.get("symbol", ""))
    exch = s.get("exchange", "")
    em = s.get("symbol_em", "")
    ml = s.get("market_lower", "")
    expected_exch = classify_exchange(sym)
    expected_em = expected_exch + sym
    expected_ml = expected_exch.lower()
    if not exch or not em or not ml:
        all_mapping_present = False
    if exch != expected_exch:
        all_exchange_ok = False
    if em != expected_em:
        all_symbol_em_ok = False
    if ml != expected_ml:
        all_market_lower_ok = False

check("5a. All mapping fields present", all_mapping_present)
check("5b. Exchange mapping correct", all_exchange_ok)
check("5c. symbol_em mapping correct", all_symbol_em_ok)
check("5d. market_lower mapping correct", all_market_lower_ok)

# 6. ETHUSDT exact match required
crypto_list = universe.get("crypto", [])
if crypto_list:
    eth = crypto_list[0]
    check("6a. ETHUSDT requested_pair present",
          eth.get("requested_pair") == "ETHUSDT")
    check("6b. ETHUSDT exact_match_required is true",
          eth.get("exact_match_required") is True)
    check("6c. ETHUSDT allow_pair_substitution is false",
          eth.get("allow_pair_substitution") is False)
    result_enum = eth.get("result_enum", [])
    check("6d. ETHUSDT result_enum correct",
          set(result_enum) == {"success", "partial_success", "unsupported"})
    check("6e. ETHUSDT base_asset is ETH", eth.get("base_asset") == "ETH")
    check("6f. ETHUSDT quote_asset is USDT", eth.get("quote_asset") == "USDT")
else:
    check("6. ETHUSDT config present", False, "crypto section missing or empty")

# 7. MA windows exact match
ma_price = metrics.get("ma_windows", {}).get("price", [])
check("7. MA windows match [3,5,7,10,13,20,21]",
      ma_price == EXPECTED_MA_WINDOWS,
      "got " + str(ma_price))

# 8. Activity scoring weights sum to ~1.0
weights = metrics.get("activity_scoring", {}).get("weights", {})
weight_sum = sum(float(v) for v in weights.values())
check("8. Activity weights sum to 1.0",
      abs(weight_sum - 1.0) < 0.001,
      "sum=" + str(weight_sum))

# 9. Adjustment rules
adj = metrics.get("adjustment_rules", {})
check("9a. Trend/MA uses qfq", adj.get("trend_and_ma", {}).get("adjust") == "qfq")
check("9b. Limit detection uses raw",
      adj.get("limit_detection", {}).get("adjust") == "")
check("9c. Mixed forbidden is true", adj.get("mixed_forbidden") is True)

# 10. No network access in configs
config_texts = []
for f in (CONFIG_DIR / "universe.yml", CONFIG_DIR / "metric_definition.yml"):
    with open(str(f), "r", encoding="utf-8") as fh:
        config_texts.append(fh.read())

network_patterns = [
    r"https?://",
    r"requests\.(get|post)",
    r"urllib\.request",
    r"import akshare",
    r"from akshare",
    r"ak\.\w+\(",
]

network_found = []
for text in config_texts:
    for pat in network_patterns:
        matches = re.findall(pat, text, re.IGNORECASE)
        network_found.extend(matches)

check("10. No network/akshare calls in config files",
      len(network_found) == 0,
      "found: " + str(network_found))

# 11. Test file itself clean
test_text = Path(__file__).read_text(encoding="utf-8")
test_lines = test_text.splitlines()
test_network = []
for line in test_lines:
    if any(kw in line for kw in ["skip_keywords", "re.findall", "re.search", "r\"(import", "r\"\\b(import", 'r"import akshare', 'r"from akshare']):
        continue
    match = re.search(r"\b(import akshare|from akshare)\b", line)
    if match:
        test_network.append(line.strip())
check("11. Test file has no network access",
      len(test_network) == 0,
      "found: " + str(test_network))

# 12. as_of_date
check("12a. universe.yml as_of_date is 2026-07-27",
      universe.get("as_of_date") == "2026-07-27")
check("12b. metric_definition.yml as_of_date is 2026-07-27",
      metrics.get("as_of_date") == "2026-07-27")

# 13. schema_version presence
check("13a. universe.yml has schema_version", "schema_version" in universe)
check("13b. metric_definition.yml has schema_version", "schema_version" in metrics)

# 14. Volume conventions
vol_conv = metrics.get("numeric_conventions", {})
check("14a. Volume conversion rule present",
      vol_conv.get("volume_conversion") == "1 lot = 100 shares")
check("14b. Percentage stored as decimal",
      vol_conv.get("percentage_storage") == "decimal")
check("14c. Currency is CNY", vol_conv.get("currency") == "CNY")
check("14d. Currency unit is yuan",
      vol_conv.get("currency_unit") == "yuan (元)")

# 15. Style labels
expected_styles = {"温和箱体型", "高波动震荡型", "放量冲击型",
                   "低活跃盘整型", "趋势型", "证据不足"}
actual_styles = set(metrics.get("consolidation_analysis", {}).get("style_labels", []))
check("15. Style labels match expected set", actual_styles == expected_styles,
      "expected=" + str(expected_styles) + ", got=" + str(actual_styles))

# 16. Consolidation required fields
cons_fields = metrics.get("consolidation_analysis", {}).get("required_fields", [])
check("16. Consolidation has >= 10 required fields", len(cons_fields) >= 10,
      "got " + str(len(cons_fields)) + ": " + str(cons_fields))

# 17. Fundamental metrics
fund_metrics = metrics.get("fundamental_metrics", {}).get("required", [])
check("17. At least 12 fundamental metrics", len(fund_metrics) >= 12,
      "got " + str(len(fund_metrics)) + ": " + str(fund_metrics))

# ---- Summary ----------------------------------------------------------------
print()
passed = sum(1 for c, _ in results if c)
total = len(results)
print(str(passed) + "/" + str(total) + " checks passed")
if passed < total:
    print("SOME CHECKS FAILED")
    sys.exit(1)
else:
    print("ALL CHECKS PASSED")
    try:
        import yaml
    except ImportError:
        print()
        print("NOTE: PyYAML not installed. Used simple fallback parser.")
        print("Stage 1 should install: pip install pyyaml pytest")
    try:
        import pytest
    except ImportError:
        print("NOTE: pytest not installed. Running with standard-library checks only.")
        print("Stage 1 should install: pip install pytest")
