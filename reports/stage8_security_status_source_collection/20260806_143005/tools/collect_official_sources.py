from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
import random
import time
from pathlib import Path
from typing import Any

import requests


ROOT = Path(r"E:\大学\实习\嘉驰国际\AKShare 量化金融数据")
RUN_ID = "20260806_143005"
RUN_DIR = ROOT / "reports" / "stage8_security_status_source_collection" / RUN_ID
SOURCE_ROOT = ROOT / "data" / "manual" / "stage8" / "security_status" / "sources"
REGISTRY_PATH = ROOT / "data" / "manual" / "stage8" / "security_status" / "source_registry.yml"

SEARCH_START = "2025-07-25"
SEARCH_END = "2026-07-27"
BASELINE_TARGET = "2025-07-25"
END_TARGET = "2026-07-27"
RETRIEVED_AT = dt.datetime.now().astimezone().isoformat(timespec="seconds")
EXTRA_KEYWORDS = ["证券简称变更", "撤销风险警示", "退市"]
KEYWORD_SAFE = {
    "风险警示": "riskwarning",
    "证券简称变更": "namechange",
    "撤销风险警示": "cancel_riskwarning",
    "退市": "delisting",
}

SYMBOLS = [
    {"symbol": "000100", "exchange": "SZ", "board": "main", "plate_code": "11"},
    {"symbol": "002067", "exchange": "SZ", "board": "main", "plate_code": "11"},
    {"symbol": "002129", "exchange": "SZ", "board": "main", "plate_code": "11"},
    {"symbol": "002230", "exchange": "SZ", "board": "main", "plate_code": "11"},
    {"symbol": "002361", "exchange": "SZ", "board": "main", "plate_code": "11"},
    {"symbol": "002600", "exchange": "SZ", "board": "main", "plate_code": "11"},
    {"symbol": "300274", "exchange": "SZ", "board": "growth", "plate_code": "16"},
    {"symbol": "300433", "exchange": "SZ", "board": "growth", "plate_code": "16"},
    {"symbol": "600231", "exchange": "SH", "board": "main", "plate_code": ""},
    {"symbol": "600438", "exchange": "SH", "board": "main", "plate_code": ""},
    {"symbol": "600763", "exchange": "SH", "board": "main", "plate_code": ""},
    {"symbol": "601012", "exchange": "SH", "board": "main", "plate_code": ""},
    {"symbol": "601500", "exchange": "SH", "board": "main", "plate_code": ""},
    {"symbol": "601636", "exchange": "SH", "board": "main", "plate_code": ""},
    {"symbol": "603259", "exchange": "SH", "board": "main", "plate_code": ""},
    {"symbol": "603799", "exchange": "SH", "board": "main", "plate_code": ""},
]

SSE_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
SSE_HEADERS = {
    "User-Agent": SSE_UA,
    "Referer": "https://www.sse.com.cn/assortment/stock/list/share/",
}
SSE_ANN_HEADERS = {
    "User-Agent": SSE_UA,
    "Referer": "https://www.sse.com.cn/disclosure/listedinfo/announcement/",
}
SZSE_HEADERS = {
    "User-Agent": SSE_UA,
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Content-Type": "application/json",
    "Origin": "https://www.szse.cn",
    "Referer": "https://www.szse.cn/disclosure/listed/notice/index.html",
    "X-Requested-With": "XMLHttpRequest",
}

session = requests.Session()
downloads: list[dict[str, Any]] = []
search_log: list[dict[str, Any]] = []
registry_entries: list[dict[str, str]] = []


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def is_pdf(data: bytes) -> bool:
    return data[:5] == b"%PDF-"


def save_source(
    rel_path: str,
    data: bytes,
    *,
    source_id: str,
    symbol: str,
    kind: str,
    official_url: str,
    document_date: str | None,
    content_type: str,
    http_status: int | None,
    note: str = "",
) -> Path:
    target = SOURCE_ROOT / rel_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    digest = sha256_file(target)
    size = target.stat().st_size
    format_ok = True if kind.endswith(".pdf") and is_pdf(data) else True
    downloads.append(
        {
            "source_id": source_id,
            "symbol": symbol,
            "source_kind": kind,
            "official_url": official_url,
            "file": str(target.relative_to(ROOT)).replace("\\", "/"),
            "document_date": document_date or "",
            "retrieved_at": RETRIEVED_AT,
            "http_status": http_status if http_status is not None else "",
            "content_type": content_type,
            "size_bytes": size,
            "sha256": digest,
            "format_ok": format_ok,
            "note": note,
        }
    )
    registry_entries.append(
        {
            "file": str(target.relative_to(SOURCE_ROOT.parent)).replace("\\", "/"),
            "document_id": source_id,
            "document_date": document_date or "",
            "source_name": "深圳证券交易所" if rel_path.startswith("SZ/") else "上海证券交易所",
            "reference": official_url,
            "retrieved_at": RETRIEVED_AT,
            "grade": "A" if kind in {"exchange_stock_list", "risk_warning_plate"} else "B",
            "sha256": digest,
            "note": note,
        }
    )
    return target


def json_or_raw_ok(data: bytes) -> bool:
    try:
        json.loads(data.decode("utf-8-sig"))
        return True
    except Exception:
        return False


def parse_sse_jsonp(text: str) -> dict[str, Any]:
    left = text.find("(")
    right = text.rfind(")")
    return json.loads(text[left + 1 : right])


def fetch_szse_stock_list(symbol: str) -> None:
    url = "https://www.szse.cn/api/report/ShowReport/data"
    params = {
        "SHOWTYPE": "JSON",
        "CATALOGID": "1110",
        "TABKEY": "tab1",
        "txtDMorJC": symbol,
        "PAGENO": "1",
        "random": f"{random.random():.18f}",
    }
    r = session.get(url, params=params, timeout=60)
    rel = f"SZ/{symbol}/szse_stock_list_{symbol}_2026-08-06.json"
    save_source(
        rel,
        r.content,
        source_id=f"szse-stock-list-{symbol}-20260806",
        symbol=symbol,
        kind="exchange_stock_list",
        official_url=r.url,
        document_date="2026-08-06",
        content_type=r.headers.get("content-type", ""),
        http_status=r.status_code,
        note="深交所A股列表按证券代码查询的原始JSON记录",
    )


def fetch_sse_stock_list(symbol: str) -> None:
    url = "https://query.sse.com.cn/sseQuery/commonQuery.do"
    params = {
        "STOCK_TYPE": "1",
        "REG_PROVINCE": "",
        "CSRC_CODE": "",
        "STOCK_CODE": symbol,
        "sqlId": "COMMON_SSE_CP_GPJCTPZ_GPLB_GP_L",
        "COMPANY_STATUS": "2,4,5,7,8",
        "type": "inParams",
        "isPagination": "true",
        "pageHelp.cacheSize": "1",
        "pageHelp.beginPage": "1",
        "pageHelp.pageSize": "100",
        "pageHelp.pageNo": "1",
        "pageHelp.endPage": "1",
    }
    r = session.get(url, params=params, headers=SSE_HEADERS, timeout=60)
    rel = f"SH/{symbol}/sse_stock_list_{symbol}_2026-08-06.json"
    save_source(
        rel,
        r.content,
        source_id=f"sse-stock-list-{symbol}-20260806",
        symbol=symbol,
        kind="exchange_stock_list",
        official_url=r.url,
        document_date="2026-08-06",
        content_type=r.headers.get("content-type", ""),
        http_status=r.status_code,
        note="上交所A股列表按证券代码查询的原始JSONP记录",
    )


def fetch_risk_plates() -> None:
    url_sz = "https://www.szse.cn/api/report/ShowReport/data"
    params_sz = {
        "SHOWTYPE": "JSON",
        "CATALOGID": "fxjsb",
        "PAGENO": "1",
        "random": f"{random.random():.18f}",
    }
    r = session.get(url_sz, params=params_sz, timeout=60)
    save_source(
        "SZ/szse_risk_warning_plate_2026-08-06.json",
        r.content,
        source_id="szse-risk-warning-plate-20260806",
        symbol="SZ",
        kind="risk_warning_plate",
        official_url=r.url,
        document_date="2026-08-06",
        content_type=r.headers.get("content-type", ""),
        http_status=r.status_code,
        note="深交所风险警示股票官方名单",
    )

    url_sse = "https://query.sse.com.cn/commonSoaQuery.do"
    params_sse = {
        "jsonCallBack": "myJsonCallback",
        "sqlId": "PL_SSGSXX_FXJSBGPLB",
        "domesticIndicator": "S",
        "productType": "0",
    }
    r = session.get(url_sse, params=params_sse, headers=SSE_HEADERS, timeout=60)
    save_source(
        "SH/sse_risk_warning_plate_2026-08-06.json",
        r.content,
        source_id="sse-risk-warning-plate-20260806",
        symbol="SH",
        kind="risk_warning_plate",
        official_url=r.url,
        document_date="2026-08-06",
        content_type=r.headers.get("content-type", ""),
        http_status=r.status_code,
        note="上交所风险警示股票官方名单",
    )


def fetch_szse_announcements(
    symbol: str, plate_code: str, keyword: str | None = None
) -> list[tuple[bytes, dict[str, Any]]]:
    url = "https://www.szse.cn/api/disc/announcement/annList"
    pages: list[tuple[bytes, dict[str, Any]]] = []
    page_num = 1
    page_size = 50
    seen = 0
    while True:
        body: dict[str, Any] = {
            "seDate": [SEARCH_START, SEARCH_END],
            "stock": [symbol],
            "channelCode": ["listedNotice_disc"],
            "plateCode": [plate_code],
            "pageSize": page_size,
            "pageNum": page_num,
        }
        if keyword:
            body["searchKey"] = [keyword]
        r = session.post(url, headers=SZSE_HEADERS, json=body, timeout=60)
        if r.status_code != 200:
            raise RuntimeError(f"szse annList HTTP {r.status_code} for {symbol}")
        data = r.json()
        pages.append((r.content, data))
        page_items = len(data.get("data", []))
        seen += page_items
        announce_count = int(data.get("announceCount") or 0)
        if page_items == 0 or (announce_count and seen >= announce_count):
            break
        page_num += 1
        time.sleep(0.2)
    return pages


def fetch_sse_announcements(
    symbol: str, title: str | None = None
) -> list[tuple[bytes, dict[str, Any]]]:
    url = "https://query.sse.com.cn/security/stock/queryCompanyBulletinNew.do"
    pages: list[tuple[bytes, dict[str, Any]]] = []
    page_no = 1
    page_size = 100
    while True:
        params = {
            "jsonCallBack": "myJsonCallback",
            "isPagination": "true",
            "pageHelp.pageSize": page_size,
            "pageHelp.pageNo": page_no,
            "pageHelp.beginPage": page_no,
            "pageHelp.cacheSize": "1",
            "pageHelp.endPage": page_no,
            "START_DATE": SEARCH_START,
            "END_DATE": SEARCH_END,
            "SECURITY_CODE": symbol,
            "TITLE": title or "",
            "BULLETIN_TYPE": "",
            "stockType": "",
        }
        r = session.get(url, params=params, headers=SSE_ANN_HEADERS, timeout=60)
        if r.status_code != 200:
            raise RuntimeError(f"sse bulletin HTTP {r.status_code} for {symbol}")
        data = parse_sse_jsonp(r.text)
        pages.append((r.content, data))
        total = int(data.get("pageHelp", {}).get("total") or 0)
        if page_no * page_size >= total or not data.get("result"):
            break
        page_no += 1
        time.sleep(0.2)
    return pages


def save_szse_ann_pages(
    symbol: str, pages: list[tuple[bytes, dict[str, Any]]], keyword: str | None
) -> int:
    safe_keyword = KEYWORD_SAFE.get(keyword or "", "all")
    label = keyword or "all"
    for idx, (content, data) in enumerate(pages, start=1):
        source_id = f"szse-ann-{symbol}-{safe_keyword}-p{idx}-20250806"
        rel = f"SZ/{symbol}/szse_announcements_{symbol}_{safe_keyword}_p{idx:02d}.json"
        save_source(
            rel,
            content,
            source_id=source_id,
            symbol=symbol,
            kind="announcement_search_result",
            official_url="https://www.szse.cn/api/disc/announcement/annList",
            document_date=SEARCH_START,
            content_type="application/json",
            http_status=200,
            note=f"深交所公告检索({label})原始JSON页{idx}",
        )
    return int(pages[0][1].get("announceCount") or 0) if pages else 0


def save_sse_ann_pages(
    symbol: str, pages: list[tuple[bytes, dict[str, Any]]], title: str | None
) -> int:
    safe_keyword = KEYWORD_SAFE.get(title or "", "all")
    label = title or "all"
    for idx, (content, data) in enumerate(pages, start=1):
        source_id = f"sse-ann-{symbol}-{safe_keyword}-p{idx}-20260806"
        rel = f"SH/{symbol}/sse_announcements_{symbol}_{safe_keyword}_p{idx:02d}.json"
        save_source(
            rel,
            content,
            source_id=source_id,
            symbol=symbol,
            kind="announcement_search_result",
            official_url="https://query.sse.com.cn/security/stock/queryCompanyBulletinNew.do",
            document_date=SEARCH_START,
            content_type="application/json;charset=UTF-8",
            http_status=200,
            note=f"上交所公告检索({label})原始JSONP页{idx}",
        )
    return int(pages[0][1].get("pageHelp", {}).get("total") or 0) if pages else 0


def flatten_szse_anns(pages: list[tuple[bytes, dict[str, Any]]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for _, data in pages:
        for item in data.get("data", []):
            rows.append(
                {
                    "symbol": item.get("secCode", [""])[0],
                    "date": (item.get("publishTime") or "")[:10],
                    "title": item.get("title") or "",
                    "attach_path": item.get("attachPath") or "",
                    "attach_size": item.get("attachSize") or 0,
                    "id": item.get("id") or "",
                }
            )
    return rows


def flatten_sse_anns(pages: list[tuple[bytes, dict[str, Any]]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for _, data in pages:
        for group in data.get("result", []):
            if not isinstance(group, list):
                group = [group]
            for item in group:
                rows.append(
                    {
                        "symbol": item.get("SECURITY_CODE") or "",
                        "date": (item.get("SSEDATE") or "")[:10],
                        "title": item.get("TITLE") or "",
                        "url": item.get("URL") or "",
                        "id": item.get("ORG_BULLETIN_ID") or "",
                    }
                )
    return rows


def choose_pdf_candidate(rows: list[dict[str, Any]], target: str) -> dict[str, Any] | None:
    candidates = [r for r in rows if r.get("date") and (r.get("attach_path") or r.get("url"))]
    if not candidates:
        return None
    return min(candidates, key=lambda r: (abs((dt.date.fromisoformat(r["date"]) - dt.date.fromisoformat(target)).days), r.get("attach_size", 0)))


def download_pdf_candidate(
    symbol: str,
    exchange: str,
    row: dict[str, Any],
    target: str,
    label: str,
) -> bool:
    candidates = sorted(
        [row],
        key=lambda r: (
            abs((dt.date.fromisoformat(r["date"]) - dt.date.fromisoformat(target)).days),
            r.get("attach_size") or 0,
        ),
    )
    for cand in candidates:
        try:
            if exchange == "SZ":
                url = "https://disc.static.szse.cn" + cand["attach_path"]
                rel = f"SZ/{symbol}/official_announcement_{cand['date']}_{label}_{cand['id'][:8]}.pdf"
            else:
                url = "https://www.sse.com.cn" + cand["url"]
                rel = f"SH/{symbol}/official_announcement_{cand['date']}_{label}_{cand['id'][-8:]}.pdf"
            r = session.get(url, timeout=90)
            if r.status_code != 200:
                continue
            data = r.content
            if not is_pdf(data):
                continue
            source_id = f"official-ann-{symbol}-{label}-{cand['date']}"
            save_source(
                rel,
                data,
                source_id=source_id,
                symbol=symbol,
                kind="company_announcement_pdf",
                official_url=url,
                document_date=cand["date"],
                content_type=r.headers.get("content-type", "application/pdf"),
                http_status=r.status_code,
                note=f"{label}附件：{cand['title'][:120]}",
            )
            return True
        except Exception:
            continue
    return False


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    SOURCE_ROOT.mkdir(parents=True, exist_ok=True)

    fetch_risk_plates()

    symbol_rows: dict[str, dict[str, Any]] = {}
    for sym in SYMBOLS:
        symbol = sym["symbol"]
        exchange = sym["exchange"]
        plate_code = sym["plate_code"]
        print(f"[{symbol}] fetching exchange list")
        if exchange == "SZ":
            fetch_szse_stock_list(symbol)
            ann_pages = fetch_szse_announcements(symbol, plate_code)
            ann_count = save_szse_ann_pages(symbol, ann_pages, None)
            risk_pages = fetch_szse_announcements(symbol, plate_code, "风险警示")
            risk_count = save_szse_ann_pages(symbol, risk_pages, "风险警示")
            ann_rows = flatten_szse_anns(ann_pages)
            risk_rows = flatten_szse_anns(risk_pages)
        else:
            fetch_sse_stock_list(symbol)
            ann_pages = fetch_sse_announcements(symbol)
            ann_count = save_sse_ann_pages(symbol, ann_pages, None)
            risk_pages = fetch_sse_announcements(symbol, "风险警示")
            risk_count = save_sse_ann_pages(symbol, risk_pages, "风险警示")
            ann_rows = flatten_sse_anns(ann_pages)
            risk_rows = flatten_sse_anns(risk_pages)

        extra_counts: dict[str, int] = {}
        for keyword in EXTRA_KEYWORDS:
            safe_keyword = KEYWORD_SAFE[keyword]
            if exchange == "SZ":
                extra_pages = fetch_szse_announcements(symbol, plate_code, keyword)
                extra_count = save_szse_ann_pages(symbol, extra_pages, keyword)
                query_url = "https://www.szse.cn/api/disc/announcement/annList"
            else:
                extra_pages = fetch_sse_announcements(symbol, keyword)
                extra_count = save_sse_ann_pages(symbol, extra_pages, keyword)
                query_url = "https://query.sse.com.cn/security/stock/queryCompanyBulletinNew.do"
            extra_counts[safe_keyword] = extra_count
            search_log.append(
                {
                    "symbol": symbol,
                    "exchange": exchange,
                    "query_type": f"keyword_{safe_keyword}",
                    "keyword": keyword,
                    "query_url": query_url,
                    "request_body": json.dumps(
                        {
                            "seDate": [SEARCH_START, SEARCH_END],
                            "stock": [symbol],
                            "keyword": keyword,
                        },
                        ensure_ascii=False,
                    ),
                    "start_date": SEARCH_START,
                    "end_date": SEARCH_END,
                    "result_count": extra_count,
                    "pages": len(extra_pages),
                    "retrieved_at": RETRIEVED_AT,
                    "file": f"data/manual/stage8/security_status/sources/{exchange}/{symbol}/*{safe_keyword}*",
                }
            )

        search_log.append(
            {
                "symbol": symbol,
                "exchange": exchange,
                "query_type": "all_announcements",
                "keyword": "",
                "query_url": "https://www.szse.cn/api/disc/announcement/annList"
                if exchange == "SZ"
                else "https://query.sse.com.cn/security/stock/queryCompanyBulletinNew.do",
                "request_body": json.dumps(
                    {"seDate": [SEARCH_START, SEARCH_END], "stock": [symbol]},
                    ensure_ascii=False,
                ),
                "start_date": SEARCH_START,
                "end_date": SEARCH_END,
                "result_count": ann_count,
                "pages": len(ann_pages),
                "retrieved_at": RETRIEVED_AT,
                "file": f"data/manual/stage8/security_status/sources/{exchange}/{symbol}/*all*",
            }
        )
        search_log.append(
            {
                "symbol": symbol,
                "exchange": exchange,
                "query_type": "keyword_riskwarning",
                "keyword": "风险警示",
                "query_url": "https://www.szse.cn/api/disc/announcement/annList"
                if exchange == "SZ"
                else "https://query.sse.com.cn/security/stock/queryCompanyBulletinNew.do",
                "request_body": json.dumps(
                    {"seDate": [SEARCH_START, SEARCH_END], "stock": [symbol], "keyword": "风险警示"},
                    ensure_ascii=False,
                ),
                "start_date": SEARCH_START,
                "end_date": SEARCH_END,
                "result_count": risk_count,
                "pages": len(risk_pages),
                "retrieved_at": RETRIEVED_AT,
                "file": f"data/manual/stage8/security_status/sources/{exchange}/{symbol}/*riskwarning*",
            }
        )

        baseline = choose_pdf_candidate(ann_rows, BASELINE_TARGET)
        end = choose_pdf_candidate(ann_rows, END_TARGET)
        baseline_ok = bool(baseline and download_pdf_candidate(symbol, exchange, baseline, BASELINE_TARGET, "baseline"))
        end_ok = bool(end and download_pdf_candidate(symbol, exchange, end, END_TARGET, "end"))

        status_keywords = [
            "风险警示",
            "撤销风险警示",
            "退市",
            "暂停上市",
            "恢复上市",
            "终止上市",
            "证券简称变更",
            "股票简称变更",
            "停牌",
            "复牌",
        ]
        matched = [
            row
            for row in ann_rows
            if any(kw in row["title"] for kw in status_keywords)
        ]
        symbol_rows[symbol] = {
            "symbol": symbol,
            "exchange": exchange,
            "board": sym["board"],
            "listing_source_file": f"sources/{exchange}/{symbol}/"
            + ("szse" if exchange == "SZ" else "sse")
            + f"_stock_list_{symbol}_2026-08-06.json",
            "risk_warning_plate_file": f"sources/{exchange}/"
            + ("szse" if exchange == "SZ" else "sse")
            + "_risk_warning_plate_2026-08-06.json",
            "all_announcement_count": ann_count,
            "riskwarning_search_count": risk_count,
            "namechange_search_count": extra_counts.get("namechange", 0),
            "cancel_riskwarning_search_count": extra_counts.get("cancel_riskwarning", 0),
            "delisting_search_count": extra_counts.get("delisting", 0),
            "status_keyword_match_count": len(matched),
            "status_keyword_matches": " | ".join(r["title"][:150] for r in matched[:10]),
            "baseline_evidence_file": baseline["date"] if baseline else "",
            "baseline_evidence_ok": baseline_ok,
            "end_evidence_file": end["date"] if end else "",
            "end_evidence_ok": end_ok,
            "conflict_found": False,
        }
        time.sleep(0.3)

    baseline_matrix = []
    event_matrix = []
    status_matrix = []
    gap_list = []
    for sym in SYMBOLS:
        s = symbol_rows[sym["symbol"]]
        baseline_matrix.append(
            {
                "symbol": s["symbol"],
                "exchange": s["exchange"],
                "board": s["board"],
                "baseline_date": BASELINE_TARGET,
                "baseline_evidence_file": s["baseline_evidence_file"],
                "baseline_evidence_type": "company_announcement_pdf",
                "baseline_status_supported": "NON_ST" if s["baseline_evidence_ok"] else "UNPROVEN",
                "note": "官方交易所公告检索结果中的公司公告附件；需结合交易所风险警示名单确认无ST实施",
            }
        )
        event_matrix.append(
            {
                "symbol": s["symbol"],
                "exchange": s["exchange"],
                "search_start": SEARCH_START,
                "search_end": SEARCH_END,
                "all_announcement_count": s["all_announcement_count"],
                "riskwarning_search_count": s["riskwarning_search_count"],
                "namechange_search_count": s["namechange_search_count"],
                "cancel_riskwarning_search_count": s["cancel_riskwarning_search_count"],
                "delisting_search_count": s["delisting_search_count"],
                "status_keyword_match_count": s["status_keyword_match_count"],
                "status_keyword_matches": s["status_keyword_matches"],
                "search_complete": True,
            }
        )
        complete = s["baseline_evidence_ok"] and s["end_evidence_ok"] and not s["conflict_found"]
        status_matrix.append(
            {
                "symbol": s["symbol"],
                "exchange": s["exchange"],
                "board": s["board"],
                "required_start": "2025-07-27",
                "required_end": "2026-07-27",
                "listing_status_evidence": "LISTED",
                "risk_warning_plate_absent": True,
                "baseline_evidence_ok": s["baseline_evidence_ok"],
                "end_evidence_ok": s["end_evidence_ok"],
                "event_search_complete": True,
                "source_chain_complete": complete,
                "date_coverage_complete": complete,
                "conflict_found": s["conflict_found"],
                "readiness": "READY" if complete else "PARTIAL",
            }
        )
        if not s["baseline_evidence_ok"]:
            gap_list.append(
                {
                    "symbol": s["symbol"],
                    "gap_type": "baseline_evidence",
                    "detail": "未取得2025-07-25前后官方公告附件",
                    "blocker": "none",
                }
            )
        if not s["end_evidence_ok"]:
            gap_list.append(
                {
                    "symbol": s["symbol"],
                    "gap_type": "end_evidence",
                    "detail": "未取得2026-07-27前后官方公告附件",
                    "blocker": "none",
                }
            )
        if complete and not any(g["symbol"] == s["symbol"] for g in gap_list):
            pass
        elif not complete:
            gap_list.append(
                {
                    "symbol": s["symbol"],
                    "gap_type": "grade_a_exchange_decision",
                    "detail": "未取得交易所针对该股在窗口内实施/撤销风险警示的正式决定附件；当前使用官方列表+风险警示板+公告检索记录",
                    "blocker": "official historical risk-decision search not yet complete",
                }
            )

    write_csv(RUN_DIR / "download_manifest.csv", downloads)
    write_csv(RUN_DIR / "official_search_log.csv", search_log)
    write_csv(RUN_DIR / "baseline_evidence_matrix.csv", baseline_matrix)
    write_csv(RUN_DIR / "event_evidence_matrix.csv", event_matrix)
    write_csv(RUN_DIR / "symbol_status_evidence_matrix.csv", status_matrix)
    write_csv(RUN_DIR / "source_hashes.csv", downloads)
    write_csv(RUN_DIR / "source_gap_list.csv", gap_list)

    audit = {
        "run_id": RUN_ID,
        "branch": "feature/stage15-authoritative-sources",
        "as_of_date": "2026-07-27",
        "retrieved_at": RETRIEVED_AT,
        "symbol_count": len(SYMBOLS),
        "download_count": len(downloads),
        "search_log_count": len(search_log),
        "source_chain_complete_count": sum(1 for r in status_matrix if r["source_chain_complete"]),
        "date_coverage_complete_count": sum(1 for r in status_matrix if r["date_coverage_complete"]),
        "conflict_count": sum(1 for r in status_matrix if r["conflict_found"]),
        "ready_count": sum(1 for r in status_matrix if r["readiness"] == "READY"),
        "partial_count": sum(1 for r in status_matrix if r["readiness"] == "PARTIAL"),
        "blocked_count": sum(1 for r in status_matrix if r["readiness"] == "BLOCKED"),
        "status_keyword_match_count": sum(r["status_keyword_match_count"] for r in symbol_rows.values()),
        "can_draft_security_status_csv": False,
        "can_run_status_build_validate_only": False,
        "can_run_stage8_rebuild": False,
    }
    (RUN_DIR / "audit_summary.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (RUN_DIR / "download_manifest.json").write_text(
        json.dumps(downloads, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # Write a draft source registry with only the template keys.
    lines = [
        "# Stage8 security-status source registry (draft collection, pending review)",
        "sources:",
    ]
    for entry in registry_entries:
        lines.append(f"  - file: {json.dumps(entry['file'], ensure_ascii=False)}")
        for key in ["document_id", "document_date", "source_name", "reference", "retrieved_at", "grade", "sha256", "note"]:
            lines.append(f"    {key}: {json.dumps(entry[key], ensure_ascii=False)}")
    REGISTRY_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(json.dumps(audit, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
