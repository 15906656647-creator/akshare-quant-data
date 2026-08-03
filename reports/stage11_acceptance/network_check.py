from __future__ import annotations

import hashlib
import json
import ssl
import urllib.error
import urllib.parse
import urllib.request
from datetime import timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).with_name("stage11_network_evidence.json")


def request_json(base: str, params: dict[str, str]) -> dict:
    url = base + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "stage11-independent-acceptance/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=30, context=ssl.create_default_context()) as resp:
            body = resp.read()
            return {
                "url": url,
                "http_status": resp.status,
                "headers": dict(resp.headers.items()),
                "body_sha256": hashlib.sha256(body).hexdigest(),
                "json": json.loads(body),
            }
    except urllib.error.HTTPError as exc:
        body = exc.read()
        result = {
            "url": url,
            "http_status": exc.code,
            "headers": dict(exc.headers.items()),
            "body_sha256": hashlib.sha256(body).hexdigest(),
            "body_preview": body[:500].decode("utf-8", errors="replace"),
        }
        try:
            result["json"] = json.loads(body)
        except json.JSONDecodeError:
            pass
        return result


def main() -> None:
    rows = json.loads((ROOT / "reports" / "stage11_crypto_price.json").read_text(encoding="utf-8"))
    if not rows:
        raise RuntimeError("saved ETHUSDT row not found")
    saved = max(rows, key=lambda x: x["trade_time"])
    saved_time = __import__("datetime").datetime.fromisoformat(saved["trade_time"]).astimezone(timezone.utc)
    cursor_ms = int(saved_time.timestamp() * 1000) + 3_600_000

    instrument = request_json(
        "https://www.okx.com/api/v5/public/instruments",
        {"instType": "SPOT", "instId": "ETH-USDT"},
    )
    candles = request_json(
        "https://www.okx.com/api/v5/market/history-candles",
        {"instId": "ETH-USDT", "bar": "1H", "after": str(cursor_ms), "limit": "5"},
    )
    binance = request_json(
        "https://api.binance.com/api/v3/klines",
        {
            "symbol": "ETHUSDT",
            "interval": "1h",
            "startTime": "1781740800000",
            "endTime": "1785196800000",
            "limit": "1000",
        },
    )

    instrument_data = instrument.get("json", {}).get("data", [])
    candle_data = candles.get("json", {}).get("data", [])
    matching = [x for x in candle_data if int(x[0]) == int(saved_time.timestamp() * 1000)]
    comparisons = []
    if matching:
        live = matching[0]
        names = ["open", "high", "low", "close", "volume", "quote_volume"]
        for name, actual in zip(names, live[1:7]):
            expected = saved[name]
            comparisons.append(
                {
                    "field": name,
                    "saved": float(expected),
                    "live": float(actual),
                    "abs_error": abs(float(expected) - float(actual)),
                }
            )

    result = {
        "independent_network_access": True,
        "saved_latest_utc": saved_time.isoformat(),
        "okx_instrument": instrument,
        "okx_candles": candles,
        "binance": binance,
        "checks": {
            "okx_http_200": instrument.get("http_status") == 200 and candles.get("http_status") == 200,
            "okx_exact_spot_instrument": any(
                x.get("instId") == "ETH-USDT" and x.get("instType") == "SPOT"
                for x in instrument_data
            ),
            "saved_latest_found_live": len(matching) == 1,
            "saved_latest_confirmed_closed": len(matching) == 1 and matching[0][8] == "1",
            "saved_latest_values_match": bool(comparisons)
            and all(x["abs_error"] <= 1e-12 for x in comparisons),
            "binance_http_451_reproduced": binance.get("http_status") == 451,
        },
        "comparisons": comparisons,
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps(result["checks"], ensure_ascii=False))


if __name__ == "__main__":
    main()
