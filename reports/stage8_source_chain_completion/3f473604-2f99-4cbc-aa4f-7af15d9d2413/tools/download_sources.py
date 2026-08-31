# -*- coding: utf-8 -*-
"""Download official rule sources and compare hashes with the working files."""

import csv
import hashlib
import json
import re
import subprocess
import sys
import zipfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path.cwd()
RUN_ID = "3f473604-2f99-4cbc-aa4f-7af15d9d2413"
OUT = ROOT / "reports/stage8_source_chain_completion" / RUN_ID
DOWNLOADS = OUT / "downloads"
PAGES = DOWNLOADS / "pages"
SOURCES = ROOT / "data/manual/stage8/limit_rules/sources"
TOOLS = ROOT / "reports/stage8_rule_source_audit/e9a2d920-c4e2-42f4-b738-edf215c15fd1/tools"
sys.path.insert(0, str(TOOLS))

PDFINFO = Path(
    r"C:\Users\赵\.cache\codex-runtimes\codex-primary-runtime\dependencies\native\poppler\Library\bin\pdfinfo.exe"
)

MAPPINGS = [
    {
        "source_key": "sse-trading-rules-2023",
        "local_source_file": "sources/sse_trading_rules_2023.docx",
        "official_page_url": "https://www.sse.com.cn/lawandrules/sselawsrules2025/repeal/rules/c/c_20250612_10824490.shtml",
        "official_attachment_url": "https://www.sse.com.cn/lawandrules/sselawsrules2025/repeal/rules/c/10824490/files/dcbe58edb194451d93f19b1f7dd8fb4c.docx",
        "kind": "body",
        "extension": ".docx",
    },
    {
        "source_key": "sse-trading-rules-2023-explanation",
        "local_source_file": "sources/sse_trading_rules_2023_explanation.docx",
        "official_page_url": "https://www.sse.com.cn/lawandrules/sselawsrules2025/repeal/rules/c/c_20250612_10824490.shtml",
        "official_attachment_url": "https://www.sse.com.cn/lawandrules/sselawsrules2025/repeal/rules/c/10824490/files/0e769c598d024441a2300f7d4c8f8093.docx",
        "kind": "explanation",
        "extension": ".docx",
    },
    {
        "source_key": "sse-trading-rules-2023-deferred-articles",
        "local_source_file": "sources/sse_trading_rules_2023_deferred_articles.docx",
        "official_page_url": "https://www.sse.com.cn/lawandrules/sselawsrules2025/repeal/rules/c/c_20250612_10824490.shtml",
        "official_attachment_url": "https://www.sse.com.cn/lawandrules/sselawsrules2025/repeal/rules/c/10824490/files/3f0cc77bae0543c795a42731398bc8e0.docx",
        "kind": "deferred",
        "extension": ".docx",
    },
    {
        "source_key": "sse-trading-rules-2026",
        "local_source_file": "sources/sse_trading_rules_2026.docx",
        "official_page_url": "https://www.sse.com.cn/lawandrules/sselawsrules2025/trade/universal/c/c_20260424_10816492.shtml",
        "official_attachment_url": "https://www.sse.com.cn/lawandrules/sselawsrules2025/trade/universal/c/10816492/files/704204728fe74fff89de4f16efda4791.docx",
        "kind": "body",
        "extension": ".docx",
    },
    {
        "source_key": "sse-trading-rules-2026-explanation",
        "local_source_file": "sources/sse_trading_rules_2026_explanation.docx",
        "official_page_url": "https://www.sse.com.cn/lawandrules/sselawsrules2025/trade/universal/c/c_20260424_10816492.shtml",
        "official_attachment_url": "https://www.sse.com.cn/lawandrules/sselawsrules2025/trade/universal/c/10816492/files/92435c67211f452fa2e01792bf72012b.docx",
        "kind": "explanation",
        "extension": ".docx",
    },
    {
        "source_key": "sse-trading-rules-2026-deferred-articles",
        "local_source_file": "sources/sse_trading_rules_2026_deferred_articles.docx",
        "official_page_url": "https://www.sse.com.cn/lawandrules/sselawsrules2025/trade/universal/c/c_20260424_10816492.shtml",
        "official_attachment_url": "https://www.sse.com.cn/lawandrules/sselawsrules2025/trade/universal/c/10816492/files/2ebdf02d60684b07a6ca0fd1f8cd1456.docx",
        "kind": "deferred",
        "extension": ".docx",
    },
    {
        "source_key": "szse-trading-rules-2023",
        "local_source_file": "sources/szse_trading_rules_2023.pdf",
        "official_page_url": "https://www.szse.cn/lawrules/rule/repeal/rules/t20230217_598773.html",
        "official_attachment_url": "https://docs.static.szse.cn/www/lawrules/rule/repeal/rules/W020230217564423808793.pdf",
        "kind": "body",
        "extension": ".pdf",
        "url_note": "registered_url_returned_404;used_official_page_attachment_url",
    },
    {
        "source_key": "szse-trading-rules-2026",
        "local_source_file": "sources/szse_trading_rules_2026.pdf",
        "official_page_url": "https://www.szse.cn/lawrules/rule/allrules/bussiness/t20260424_620190.html",
        "official_attachment_url": "https://docs.static.szse.cn/www/lawrules/rule/allrules/bussiness/W020260424690713155663.pdf",
        "kind": "body",
        "extension": ".pdf",
    },
    {
        "source_key": "szse-trading-rules-2026-explanation",
        "local_source_file": "sources/szse_trading_rules_2026_explanation.pdf",
        "official_page_url": "https://www.szse.cn/lawrules/rule/allrules/bussiness/t20260424_620190.html",
        "official_attachment_url": "https://docs.static.szse.cn/www/lawrules/rule/allrules/bussiness/W020260424690713346617.pdf",
        "kind": "explanation",
        "extension": ".pdf",
    },
]

NOTICE_PAGES = [
    {
        "source_key": "sse-trading-rules-2023-notice",
        "official_page_url": "https://www.sse.com.cn/lawandrules/sselawsrules2025/repeal/rules/c/c_20250612_10824490.shtml",
    },
    {
        "source_key": "sse-trading-rules-2026-notice",
        "official_page_url": "https://www.sse.com.cn/lawandrules/sselawsrules2025/trade/universal/c/c_20260424_10816492.shtml",
    },
    {
        "source_key": "szse-trading-rules-2023-notice",
        "official_page_url": "https://www.szse.cn/lawrules/rule/repeal/rules/t20230217_598773.html",
    },
    {
        "source_key": "szse-trading-rules-2026-notice",
        "official_page_url": "https://www.szse.cn/lawrules/rule/allrules/bussiness/t20260424_620190.html",
    },
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def now_iso() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")


def curl_download(url: str, target: Path) -> tuple[int, str, int]:
    target.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "curl.exe",
        "-sS",
        "-L",
        "--max-time",
        "60",
        "-o",
        str(target),
        "-w",
        "%{http_code}|%{content_type}|%{size_download}",
        url,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    meta = result.stdout.strip()
    parts = meta.split("|")
    status = int(parts[0]) if parts and parts[0].isdigit() else 0
    content_type = parts[1] if len(parts) > 1 else ""
    size = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
    if result.returncode != 0:
        return 0, f"curl_error:{result.stderr.strip()[:200]}", 0
    return status, content_type, size


def validate_pdf(path: Path) -> tuple[bool, int, str]:
    raw = path.read_bytes()
    if not raw.startswith(b"%PDF-"):
        return False, 0, "not_pdf_magic"
    if raw.lstrip().lower().startswith(b"%pdf-") and b"<html" in raw.lower()[:512]:
        return False, 0, "html_inside_pdf"
    result = subprocess.run(
        [str(PDFINFO), str(path)], capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    match = re.search(r"Pages:\s*(\d+)", result.stdout or "")
    pages = int(match.group(1)) if match else 0
    if pages <= 0:
        return False, 0, "zero_pages_or_unreadable"
    return True, pages, "ok"


def validate_docx(path: Path) -> tuple[bool, int, str]:
    try:
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
            if "[Content_Types].xml" not in names or "word/document.xml" not in names:
                return False, 0, "missing_docx_members"
            text = z.read("word/document.xml").decode("utf-8", errors="replace")
    except Exception as exc:
        return False, 0, f"zip_error:{type(exc).__name__}"
    if "<html" in text.lower()[:2000]:
        return False, 0, "html_like_document"
    return True, len(text), "ok"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    DOWNLOADS.mkdir(parents=True, exist_ok=True)
    PAGES.mkdir(parents=True, exist_ok=True)
    records = []
    hash_rows = []

    for mapping in MAPPINGS:
        source_key = mapping["source_key"]
        local = SOURCES / Path(mapping["local_source_file"]).name
        downloaded = DOWNLOADS / (source_key + mapping["extension"])
        started = now_iso()
        status, content_type, size = curl_download(mapping["official_attachment_url"], downloaded)
        completed = now_iso()
        existing_hash = sha256(local) if local.is_file() else ""
        downloaded_hash = sha256(downloaded) if downloaded.is_file() and downloaded.stat().st_size > 0 else ""
        format_valid = False
        format_detail = ""
        if status == 200 and downloaded.is_file() and downloaded.stat().st_size > 0:
            if mapping["extension"] == ".pdf":
                format_valid, pages, format_detail = validate_pdf(downloaded)
                format_detail = f"pages={pages};{format_detail}"
            else:
                format_valid, chars, format_detail = validate_docx(downloaded)
                format_detail = f"document_xml_chars={chars};{format_detail}"
        hash_match = bool(existing_hash and downloaded_hash and existing_hash == downloaded_hash)
        if status == 0:
            retrieval_status = "URL_UNAVAILABLE"
        elif not format_valid:
            retrieval_status = "INVALID_FORMAT"
            hash_match = False
        elif not hash_match:
            retrieval_status = "HASH_MISMATCH"
        else:
            retrieval_status = "OK"
        records.append(
            {
                "source_key": source_key,
                "local_source_file": mapping["local_source_file"],
                "official_page_url": mapping["official_page_url"],
                "official_attachment_url": mapping["official_attachment_url"],
                "downloaded_file": str(downloaded.relative_to(OUT)),
                "download_started_at": started,
                "download_completed_at": completed,
                "http_status": status,
                "content_type": content_type,
                "size_bytes": size,
                "existing_sha256": existing_hash,
                "downloaded_sha256": downloaded_hash,
                "hash_match": hash_match,
                "retrieval_status": retrieval_status,
                "notes": " | ".join(filter(None, [mapping.get("url_note", ""), format_detail])),
            }
        )
        hash_rows.append(
            {
                "source_key": source_key,
                "local_source_file": mapping["local_source_file"],
                "existing_sha256": existing_hash,
                "downloaded_sha256": downloaded_hash,
                "hash_match": hash_match,
                "retrieval_status": retrieval_status,
            }
        )

    page_rows = []
    for page in NOTICE_PAGES:
        source_key = page["source_key"]
        downloaded = PAGES / (source_key + ".html")
        started = now_iso()
        status, content_type, size = curl_download(page["official_page_url"], downloaded)
        completed = now_iso()
        is_html = downloaded.is_file() and (
            b"<html" in downloaded.read_bytes()[:4096].lower()
            or b"<!doctype" in downloaded.read_bytes()[:4096].lower()
            or "html" in content_type.lower()
        )
        retrieval_status = "OK_PAGE" if status == 200 and is_html else ("URL_UNAVAILABLE" if status == 0 else "PAGE_INVALID")
        page_rows.append(
            {
                "source_key": source_key,
                "local_source_file": "",
                "official_page_url": page["official_page_url"],
                "official_attachment_url": "",
                "downloaded_file": str(downloaded.relative_to(OUT)),
                "download_started_at": started,
                "download_completed_at": completed,
                "http_status": status,
                "content_type": content_type,
                "size_bytes": size,
                "existing_sha256": "",
                "downloaded_sha256": "",
                "hash_match": False,
                "retrieval_status": retrieval_status,
                "notes": "source_role=notice;authoritative_rule_body=false",
            }
        )

    all_records = records + page_rows
    with (OUT / "retrieval_manifest.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(all_records[0].keys()))
        writer.writeheader()
        writer.writerows(all_records)
    (OUT / "retrieval_manifest.json").write_text(
        json.dumps(all_records, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    with (OUT / "hash_comparison.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(hash_rows[0].keys()))
        writer.writeheader()
        writer.writerows(hash_rows)

    summary = {
        "run_id": RUN_ID,
        "retrieved_at_complete": all(
            row["retrieval_status"] == "OK" for row in records
        ),
        "download_ok_count": sum(row["retrieval_status"] == "OK" for row in records),
        "hash_match_count": sum(row["hash_match"] for row in records),
        "attachment_count": len(records),
        "page_count": len(page_rows),
        "records": records,
        "page_rows": page_rows,
    }
    (OUT / "source_chain_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
