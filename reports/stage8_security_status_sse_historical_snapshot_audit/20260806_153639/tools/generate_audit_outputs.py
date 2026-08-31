"""Generate machine-readable outputs for the SSE historical snapshot audit.

This helper only writes audit artifacts under the current run directory. It
does not modify project code, tests, or real Stage8 data.
"""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path


RUN_DIR = Path(
    "reports/stage8_security_status_sse_historical_snapshot_audit/20260806_153639"
)
ORIGINAL_RUN_DIR = Path(
    "reports/stage8_security_status_source_collection/20260806_143005"
)
MANIFEST = ORIGINAL_RUN_DIR / "download_manifest.csv"
SEARCH_LOG = ORIGINAL_RUN_DIR / "official_search_log.csv"

SH_SYMBOLS = [
    "600231",
    "600438",
    "600763",
    "601012",
    "601500",
    "601636",
    "603259",
    "603799",
]
ALL_SYMBOLS = [
    "000100",
    "002067",
    "002129",
    "002230",
    "002361",
    "002600",
    "300274",
    "300433",
    *SH_SYMBOLS,
]


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_csv(path: Path, columns: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def load_manifest() -> list[dict]:
    with MANIFEST.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def load_search_log() -> list[dict]:
    with SEARCH_LOG.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def existing_source_reassessment(manifest: list[dict]) -> list[dict]:
    rows = []
    for r in manifest:
        kind = r.get("source_kind", "")
        if kind == "company_announcement_pdf":
            role = "BOUNDARY_ATTEMPT_INVALID"
            capability = "NO_STATUS_SNAPSHOT"
            grade = "INVALID_FOR_BOUNDARY"
            status = "REJECTED"
            note = (
                "普通上市公司公告PDF不能单独证明NON_ST；按纠正后的证据标准，"
                "不得作为2025-07-25或2026-07-27边界状态证据。"
            )
        elif kind == "announcement_search_result":
            role = "EVENT_SEARCH_SUPPORT_ONLY"
            capability = "EVENT_SEARCH_ONLY"
            grade = "EVENT_SEARCH_ONLY"
            status = "NOT_BOUNDARY_EVIDENCE"
            note = (
                "公告检索支持按START_DATE/END_DATE查询公告发布日期，但只反映公告事件，"
                "不能证明历史证券状态快照。"
            )
        elif kind in {"exchange_stock_list", "risk_warning_plate"}:
            role = "CURRENT_STATUS_SUPPORT_ONLY"
            capability = "CURRENT_ONLY"
            grade = "CURRENT_ONLY"
            status = "NOT_BOUNDARY_EVIDENCE"
            note = (
                "交易所股票列表或风险警示板为当前快照，响应无业务日期且接口无历史日期参数，"
                "不能映射至2025-07-25或2026-07-27。"
            )
        else:
            role = "OTHER"
            capability = "UNKNOWN"
            grade = "UNKNOWN"
            status = "UNKNOWN"
            note = "未归类的来源类型。"
        rows.append(
            {
                "source_id": r.get("source_id", ""),
                "symbol": r.get("symbol", ""),
                "source_kind": kind,
                "file": r.get("file", ""),
                "document_date": r.get("document_date", ""),
                "official_url": r.get("official_url", ""),
                "sha256": r.get("sha256", ""),
                "evidence_role": role,
                "historical_capability": capability,
                "evidence_grade": grade,
                "validation_status": status,
                "note": note,
            }
        )
    return rows


def official_endpoint_inventory() -> list[dict]:
    return [
        {
            "endpoint_name": "上交所风险警示板名单JSONP",
            "official_page_url": "https://www.sse.com.cn/disclosure/listedinfo/riskplate/",
            "official_data_url": "https://query.sse.com.cn/commonSoaQuery.do",
            "query_parameters": (
                "jsonCallBack; sqlId=PL_SSGSXX_FXJSBGPLB; "
                "domesticIndicator; productType"
            ),
            "response_fields": (
                "pageHelp.data/result -> INSTRUMENT_ID, INSTRUMENT_SHORT"
            ),
            "business_date_field": (
                "无历史日期参数；响应queryDate=''、searchDate=null"
            ),
            "pagination": "否",
            "historical_capability": "CURRENT_ONLY",
            "access_model": "公开网页接口",
            "evidence_use": "只能证明检索时点不在当前风险警示板，不能证明历史边界状态",
            "source_reference": (
                "https://www.sse.com.cn/xhtml/home/2021public/querySearch/"
                "search_listedCompanyInfo_2021.js"
            ),
            "notes": "官方JS仅传sqlId/domesticIndicator/productType，无日期参数。",
        },
        {
            "endpoint_name": "上交所科创板风险警示名单JSONP",
            "official_page_url": "https://www.sse.com.cn/disclosure/listedinfo/riskplate/",
            "official_data_url": "https://query.sse.com.cn/commonSoaQuery.do",
            "query_parameters": "jsonCallBack; sqlId=SSE_PL_SSGSXX_KCBFXTS_L; type",
            "response_fields": "result -> secCode, secNameCn",
            "business_date_field": "无历史日期参数；仅当前名单",
            "pagination": "否",
            "historical_capability": "CURRENT_ONLY",
            "access_model": "公开网页接口",
            "evidence_use": "只能证明检索时点当前状态，不能证明历史边界状态",
            "source_reference": (
                "https://www.sse.com.cn/xhtml/home/2021public/querySearch/"
                "search_listedCompanyInfo_2021.js"
            ),
            "notes": "官方JS仅传sqlId/type，无日期参数。",
        },
        {
            "endpoint_name": "上交所A股列表JSONP",
            "official_page_url": "https://www.sse.com.cn/assortment/stock/list/share/",
            "official_data_url": "https://query.sse.com.cn/sseQuery/commonQuery.do",
            "query_parameters": (
                "STOCK_TYPE; STOCK_CODE; "
                "sqlId=COMMON_SSE_CP_GPJCTPZ_GPLB_GP_L; COMPANY_STATUS; "
                "type=inParams; isPagination; pageHelp.*"
            ),
            "response_fields": (
                "A_STOCK_CODE, COMPANY_ABBR, STATE_CODE, STATE_CODE_STOCK, "
                "LIST_DATE, DELIST_DATE, PRODUCT_STATUS"
            ),
            "business_date_field": (
                "无历史日期参数；响应queryDate=''、pageHelp.startDate/endDate=null"
            ),
            "pagination": "是，pageHelp.*",
            "historical_capability": "CURRENT_ONLY",
            "access_model": "公开网页接口",
            "evidence_use": "只能证明当前上市状态，不能证明历史边界状态",
            "source_reference": (
                "https://www.sse.com.cn/xhtml/home/2021public/querySearch/"
                "search_stocksDepositoryReceipts_2021.js"
            ),
            "notes": "官方JS仅传STOCK_CODE/COMPANY_STATUS等，无历史日期参数。",
        },
        {
            "endpoint_name": "上交所暂停/终止上市公司列表JSONP",
            "official_page_url": "https://www.sse.com.cn/assortment/stock/list/delisting/",
            "official_data_url": "https://query.sse.com.cn/commonQuery.do",
            "query_parameters": (
                "STOCK_CODE; sqlId=COMMON_SSE_CP_GPJCTPZ_GPLB_ZZGP_L 或 "
                "COMMON_SSE_CP_GPJCTPZ_GPLB_ZTGP_L; COMPANY_STATUS; pageHelp.*"
            ),
            "response_fields": "A_STOCK_CODE, COMPANY_ABBR, LIST_DATE, DELIST_DATE",
            "business_date_field": "无历史日期参数；官方JS中的参数未含日期",
            "pagination": "是，pageHelp.*",
            "historical_capability": "CURRENT_ONLY",
            "access_model": "公开网页接口",
            "evidence_use": "只能作为当前暂停/终止状态辅助证据",
            "source_reference": (
                "https://www.sse.com.cn/xhtml/home/2021public/querySearch/"
                "search_stocksDepositoryReceipts_2021.js"
            ),
            "notes": "参数依据官方JS，本轮未重复下载响应。",
        },
        {
            "endpoint_name": "上交所公司公告检索JSONP",
            "official_page_url": "https://www.sse.com.cn/disclosure/listedinfo/announcement/",
            "official_data_url": (
                "https://query.sse.com.cn/security/stock/queryCompanyBulletinNew.do"
            ),
            "query_parameters": (
                "isPagination; pageHelp.*; START_DATE; END_DATE; SECURITY_CODE; "
                "TITLE; BULLETIN_TYPE; stockType"
            ),
            "response_fields": "SSEDATE, SECURITY_CODE, SECURITY_NAME, TITLE, URL",
            "business_date_field": "SSEDATE为公告发布日期",
            "pagination": "是，pageHelp.*",
            "historical_capability": "EVENT_SEARCH_ONLY",
            "access_model": "公开网页接口",
            "evidence_use": "只能用于事件检索，不能单独证明历史NON_ST",
            "source_reference": (
                "https://www.sse.com.cn/xhtml/home/2021public/querySearch/"
                "search_listedCompanyInfo_2021.js"
            ),
            "notes": "START_DATE/END_DATE只约束公告发布日期，不是证券状态快照日期。",
        },
        {
            "endpoint_name": "上交所发行上市公告检索JSONP",
            "official_page_url": "https://www.sse.com.cn/assortment/stock/home/",
            "official_data_url": "https://query.sse.com.cn/security/stock/queryCompanyBulletin.do",
            "query_parameters": (
                "productId; securityType; reportType2=LSGG; reportType=FXSSGG; "
                "beginDate; endDate; pageHelp.*"
            ),
            "response_fields": "SECURITY_CODE, SECURITY_NAME, SSEDATE, TITLE, URL",
            "business_date_field": "SSEDATE为公告发布日期",
            "pagination": "是，pageHelp.*",
            "historical_capability": "EVENT_SEARCH_ONLY",
            "access_model": "公开网页接口",
            "evidence_use": "只能检索发行上市公告事件，不能单独证明持续上市状态",
            "source_reference": (
                "https://www.sse.com.cn/xhtml/home/2021public/querySearch/"
                "search_listedCompanyInfo_2021.js"
            ),
            "notes": "beginDate/endDate用于发行上市公告日期范围，不是证券状态快照。",
        },
        {
            "endpoint_name": "上证所信息公司行情历史数据产品",
            "official_page_url": "https://www.sseinfo.com/services/assortment/historical/",
            "official_data_url": "无公开按日下载URL",
            "query_parameters": "不适用",
            "response_fields": "证券基本信息文件、行情快照、逐笔、K线等",
            "business_date_field": "历史数据产品按订阅交付",
            "pagination": "不适用",
            "historical_capability": "SUBSCRIPTION_ONLY",
            "access_model": "付费订阅/技术接入",
            "evidence_use": "官方说明含证券基本信息文件，但本项目未获得订阅授权，不能直接下载",
            "source_reference": (
                "https://www.sseinfo.com/services/assortment/document/product/c/"
                "10010539/files/5322995.pdf"
            ),
            "notes": "无法以公开方式取得2025-07-25或2026-07-27历史文件。",
        },
        {
            "endpoint_name": "上证所信息公司上证智能数据历史数据订阅",
            "official_page_url": "https://www.sseinfo.com/services/assortment/znsj/",
            "official_data_url": "无公开按日下载URL",
            "query_parameters": "不适用",
            "response_fields": "历史数据、每日数据、证券基础数据",
            "business_date_field": "按订阅服务提供",
            "pagination": "不适用",
            "historical_capability": "SUBSCRIPTION_ONLY",
            "access_model": "付费订阅/云服务",
            "evidence_use": "仅登记为官方订阅端点，不能作为本轮公开证据",
            "source_reference": "https://www.sseinfo.com/services/assortment/znsj/",
            "notes": "未授权访问历史存量数据。",
        },
        {
            "endpoint_name": "上交所对外公示数据目录",
            "official_page_url": "https://www.sse.com.cn/market/publicdata/",
            "official_data_url": "目录页仅链接现有栏目",
            "query_parameters": "不适用",
            "response_fields": "风险警示板、股票列表、暂停/终止上市公司等栏目",
            "business_date_field": "无历史状态快照入口",
            "pagination": "不适用",
            "historical_capability": "CURRENT_ONLY",
            "access_model": "公开网页",
            "evidence_use": "确认官网公开目录中无历史证券状态快照栏目",
            "source_reference": "https://www.sse.com.cn/market/publicdata/",
            "notes": "栏目均指向当前列表或公告，未发现历史名单下载。",
        },
        {
            "endpoint_name": "上交所数据文件交换接口规范",
            "official_page_url": "https://www.sse.com.cn/services/tradingtech/data/",
            "official_data_url": (
                "http://big5.sse.com.cn/site/cht/www.sse.com.cn/services/tradingtech/"
                "data/c/10800108/files/8c0e10542f8b47d5ad2b0874ea51b5ae.pdf"
            ),
            "query_parameters": "YYYYMMDD文件名（产品基础信息等）",
            "response_fields": "产品基础信息、非交易业务基础信息等",
            "business_date_field": "文件名中的YYYYMMDD表示适用日期",
            "pagination": "不适用",
            "historical_capability": "TECHNICAL_INTERFACE_ONLY",
            "access_model": "面向市场参与主体的技术接口",
            "evidence_use": "规范显示存在按日文件命名，但官网未提供公开下载入口",
            "source_reference": (
                "https://www.sse.com.cn/services/tradingtech/data/c/10800108/"
                "files/8c0e10542f8b47d5ad2b0874ea51b5ae.pdf"
            ),
            "notes": "直接URL在本轮返回404；搜索结果中的繁体镜像地址也返回404，未获得文件本体。",
        },
    ]


def historical_query_attempts(
    manifest: list[dict], search_log: list[dict]
) -> list[dict]:
    attempts = [
        {
            "attempt_id": "sse-riskplate-page-20260806_153639",
            "symbol_scope": "SH_ALL",
            "query_type": "official_page_inspection",
            "target_date": "N/A",
            "official_page_url": "https://www.sse.com.cn/disclosure/listedinfo/riskplate/",
            "official_data_url": "N/A",
            "request_parameters": "GET HTML",
            "http_status": "200",
            "response_business_date": "无",
            "result_count": "1",
            "local_file": "reports/stage8_security_status_sse_historical_snapshot_audit/20260806_153639/sse_riskplate_page.html",
            "retrieved_at": "2026-08-06T15:36:39+08:00",
            "evidence_grade": "CURRENT_ONLY",
            "validation_status": "NO_HISTORY_INTERFACE",
            "notes": "页面仅含简介、业务规则和当前风险警示板，无历史名单入口。",
        },
        {
            "attempt_id": "sse-riskplate-js-20260806_153639",
            "symbol_scope": "SH_ALL",
            "query_type": "official_js_inspection",
            "target_date": "N/A",
            "official_page_url": "https://www.sse.com.cn/disclosure/listedinfo/riskplate/",
            "official_data_url": "https://query.sse.com.cn/commonSoaQuery.do",
            "request_parameters": "sqlId=PL_SSGSXX_FXJSBGPLB; domesticIndicator; productType",
            "http_status": "200",
            "response_business_date": "无",
            "result_count": "1",
            "local_file": "reports/stage8_security_status_sse_historical_snapshot_audit/20260806_153639/search_listedCompanyInfo_2021.js",
            "retrieved_at": "2026-08-06T15:36:39+08:00",
            "evidence_grade": "CURRENT_ONLY",
            "validation_status": "NO_HISTORY_PARAMETER",
            "notes": "官方JS确认风险警示板请求未传任何日期参数。",
        },
        {
            "attempt_id": "sse-stocklist-page-20260806_153639",
            "symbol_scope": "SH_ALL",
            "query_type": "official_page_inspection",
            "target_date": "N/A",
            "official_page_url": "https://www.sse.com.cn/assortment/stock/list/share/",
            "official_data_url": "N/A",
            "request_parameters": "GET HTML",
            "http_status": "200",
            "response_business_date": "无",
            "result_count": "1",
            "local_file": "reports/stage8_security_status_sse_historical_snapshot_audit/20260806_153639/sse_stock_list_page.html",
            "retrieved_at": "2026-08-06T15:36:39+08:00",
            "evidence_grade": "CURRENT_ONLY",
            "validation_status": "NO_HISTORY_INTERFACE",
            "notes": "A股列表页仅显示当前列表，无历史日期入口。",
        },
        {
            "attempt_id": "sse-stocklist-js-20260806_153639",
            "symbol_scope": "SH_ALL",
            "query_type": "official_js_inspection",
            "target_date": "N/A",
            "official_page_url": "https://www.sse.com.cn/assortment/stock/list/share/",
            "official_data_url": "https://query.sse.com.cn/sseQuery/commonQuery.do",
            "request_parameters": "STOCK_CODE; sqlId=COMMON_SSE_CP_GPJCTPZ_GPLB_GP_L; COMPANY_STATUS",
            "http_status": "200",
            "response_business_date": "无",
            "result_count": "1",
            "local_file": "reports/stage8_security_status_sse_historical_snapshot_audit/20260806_153639/search_stocksDepositoryReceipts_2021.js",
            "retrieved_at": "2026-08-06T15:36:39+08:00",
            "evidence_grade": "CURRENT_ONLY",
            "validation_status": "NO_HISTORY_PARAMETER",
            "notes": "官方JS确认股票列表请求未传历史日期参数。",
        },
        {
            "attempt_id": "sse-riskplate-current-20260806_153639",
            "symbol_scope": "SH_ALL",
            "query_type": "current_snapshot",
            "target_date": "N/A",
            "official_page_url": "https://www.sse.com.cn/disclosure/listedinfo/riskplate/",
            "official_data_url": "https://query.sse.com.cn/commonSoaQuery.do",
            "request_parameters": "sqlId=PL_SSGSXX_FXJSBGPLB; domesticIndicator=S; productType=0",
            "http_status": "200",
            "response_business_date": "queryDate=''; searchDate=null",
            "result_count": "72",
            "local_file": "reports/stage8_security_status_sse_historical_snapshot_audit/20260806_153639/query_sse_riskplate_current.jsonp",
            "retrieved_at": "2026-08-06T15:36:39+08:00",
            "evidence_grade": "CURRENT_ONLY",
            "validation_status": "NOT_HISTORICAL",
            "notes": "8只目标沪市股票均不在当前风险警示板，但该结果不能映射至历史边界日。",
        },
        {
            "attempt_id": "sse-stocklist-600231-current-20260806_153639",
            "symbol_scope": "600231",
            "query_type": "current_snapshot",
            "target_date": "N/A",
            "official_page_url": "https://www.sse.com.cn/assortment/stock/list/share/",
            "official_data_url": "https://query.sse.com.cn/sseQuery/commonQuery.do",
            "request_parameters": "STOCK_CODE=600231; sqlId=COMMON_SSE_CP_GPJCTPZ_GPLB_GP_L; COMPANY_STATUS=2,4,5,7,8",
            "http_status": "200",
            "response_business_date": "queryDate=''; pageHelp.startDate/endDate=null",
            "result_count": "1",
            "local_file": "reports/stage8_security_status_sse_historical_snapshot_audit/20260806_153639/query_sse_stock_list_600231_current.jsonp",
            "retrieved_at": "2026-08-06T15:36:39+08:00",
            "evidence_grade": "CURRENT_ONLY",
            "validation_status": "NOT_HISTORICAL",
            "notes": "响应仅含当前A股列表信息，无业务日期，不能作为历史边界证据。",
        },
        {
            "attempt_id": "sse-ann-600231-20250725-20260806_153639",
            "symbol_scope": "600231",
            "query_type": "announcement_event_search",
            "target_date": "2025-07-25",
            "official_page_url": "https://www.sse.com.cn/disclosure/listedinfo/announcement/",
            "official_data_url": "https://query.sse.com.cn/security/stock/queryCompanyBulletinNew.do",
            "request_parameters": "START_DATE=2025-07-25; END_DATE=2025-07-25; SECURITY_CODE=600231",
            "http_status": "200",
            "response_business_date": "SSEDATE=2025-07-25",
            "result_count": "2",
            "local_file": "reports/stage8_security_status_sse_historical_snapshot_audit/20260806_153639/query_sse_announcement_600231_20250725.jsonp",
            "retrieved_at": "2026-08-06T15:36:39+08:00",
            "evidence_grade": "EVENT_SEARCH_ONLY",
            "validation_status": "NOT_BOUNDARY_EVIDENCE",
            "notes": "当天2条均为董事、高管辞职等普通公告，不能证明证券状态。",
        },
        {
            "attempt_id": "sse-ann-600231-20260727-20260806_153639",
            "symbol_scope": "600231",
            "query_type": "announcement_event_search",
            "target_date": "2026-07-27",
            "official_page_url": "https://www.sse.com.cn/disclosure/listedinfo/announcement/",
            "official_data_url": "https://query.sse.com.cn/security/stock/queryCompanyBulletinNew.do",
            "request_parameters": "START_DATE=2026-07-27; END_DATE=2026-07-27; SECURITY_CODE=600231",
            "http_status": "200",
            "response_business_date": "SSEDATE=N/A; total=0",
            "result_count": "0",
            "local_file": "reports/stage8_security_status_sse_historical_snapshot_audit/20260806_153639/query_sse_announcement_600231_20260727.jsonp",
            "retrieved_at": "2026-08-06T15:36:39+08:00",
            "evidence_grade": "EVENT_SEARCH_ONLY",
            "validation_status": "NOT_BOUNDARY_EVIDENCE",
            "notes": "零公告不能解释为NON_ST，仍需历史状态名单。",
        },
        {
            "attempt_id": "sseinfo-historical-products-20260806_153639",
            "symbol_scope": "SH_ALL",
            "query_type": "official_product_doc",
            "target_date": "N/A",
            "official_page_url": "https://www.sseinfo.com/services/assortment/historical/",
            "official_data_url": "N/A",
            "request_parameters": "GET HTML",
            "http_status": "200",
            "response_business_date": "不适用",
            "result_count": "1",
            "local_file": "reports/stage8_security_status_sse_historical_snapshot_audit/20260806_153639/sse_historical_products.html",
            "retrieved_at": "2026-08-06T15:36:39+08:00",
            "evidence_grade": "SUBSCRIPTION_ONLY",
            "validation_status": "NOT_PUBLIC_DOWNLOAD",
            "notes": "官方页面将历史数据列为产品，含证券基本信息文件，但未提供公开按日下载。",
        },
        {
            "attempt_id": "sseinfo-basic-file-doc-20260806_153639",
            "symbol_scope": "SH_ALL",
            "query_type": "official_product_doc",
            "target_date": "N/A",
            "official_page_url": "https://www.sseinfo.com/services/assortment/historical/",
            "official_data_url": "https://www.sseinfo.com/services/assortment/document/product/c/10010539/files/5322995.pdf",
            "request_parameters": "GET PDF",
            "http_status": "200",
            "response_business_date": "不适用",
            "result_count": "1",
            "local_file": "reports/stage8_security_status_sse_historical_snapshot_audit/20260806_153639/sse_basic_file_doc.pdf",
            "retrieved_at": "2026-08-06T15:36:39+08:00",
            "evidence_grade": "SUBSCRIPTION_ONLY",
            "validation_status": "NOT_PUBLIC_DOWNLOAD",
            "notes": "官方产品说明将证券基本信息文件纳入历史数据订阅服务。",
        },
        {
            "attempt_id": "sseinfo-market-file-doc-20260806_153639",
            "symbol_scope": "SH_ALL",
            "query_type": "official_product_doc",
            "target_date": "N/A",
            "official_page_url": "https://www.sseinfo.com/services/assortment/historical/",
            "official_data_url": "https://www.sseinfo.com/services/assortment/market/hqywwd/wdkfcsjk/c/10776917/files/54f07b0ece334b729a01d1ffb5c6ae5a.pdf",
            "request_parameters": "GET PDF",
            "http_status": "200",
            "response_business_date": "不适用",
            "result_count": "1",
            "local_file": "reports/stage8_security_status_sse_historical_snapshot_audit/20260806_153639/sse_market_file_doc.pdf",
            "retrieved_at": "2026-08-06T15:36:39+08:00",
            "evidence_grade": "SUBSCRIPTION_ONLY",
            "validation_status": "NOT_PUBLIC_DOWNLOAD",
            "notes": "官方文档提到products_yyyymmdd.xml等按日文件命名，但无公开下载入口。",
        },
        {
            "attempt_id": "sse-publicdata-directory-20260806_153639",
            "symbol_scope": "SH_ALL",
            "query_type": "official_page_inspection",
            "target_date": "N/A",
            "official_page_url": "https://www.sse.com.cn/market/publicdata/",
            "official_data_url": "N/A",
            "request_parameters": "GET HTML",
            "http_status": "200",
            "response_business_date": "无",
            "result_count": "1",
            "local_file": "reports/stage8_security_status_sse_historical_snapshot_audit/20260806_153639/sse_publicdata_page.html",
            "retrieved_at": "2026-08-06T15:36:39+08:00",
            "evidence_grade": "CURRENT_ONLY",
            "validation_status": "NO_HISTORY_INTERFACE",
            "notes": "公开数据目录指向当前股票列表、风险警示板和暂停/终止上市公司栏目，无历史快照。",
        },
        {
            "attempt_id": "sse-tradingtech-spec-404-20260806_153639",
            "symbol_scope": "SH_ALL",
            "query_type": "official_interface_spec",
            "target_date": "N/A",
            "official_page_url": "https://www.sse.com.cn/services/tradingtech/data/",
            "official_data_url": (
                "http://big5.sse.com.cn/site/cht/www.sse.com.cn/services/tradingtech/"
                "data/c/10800108/files/8c0e10542f8b47d5ad2b0874ea51b5ae.pdf"
            ),
            "request_parameters": "GET PDF",
            "http_status": "404",
            "response_business_date": "不适用",
            "result_count": "0",
            "local_file": (
                "reports/stage8_security_status_sse_historical_snapshot_audit/"
                "20260806_153639/sse_tradingtech_data_spec.404.html"
            ),
            "retrieved_at": "2026-08-06T15:36:39+08:00",
            "evidence_grade": "TECHNICAL_INTERFACE_ONLY",
            "validation_status": "UNAVAILABLE",
            "notes": (
                "官方直接URL与搜索结果的繁体镜像URL均返回404；"
                "无法据此取得历史证券信息文件公开下载入口。"
            ),
        },
    ]

    for row in search_log:
        symbol = row.get("symbol", "")
        if symbol not in SH_SYMBOLS or row.get("query_type") != "keyword_riskwarning":
            continue
        attempts.append(
            {
                "attempt_id": f"prev-{row.get('symbol')}-riskwarning-20260806_143005",
                "symbol_scope": symbol,
                "query_type": "announcement_event_search",
                "target_date": "2025-07-25至2026-07-27",
                "official_page_url": "https://www.sse.com.cn/disclosure/listedinfo/announcement/",
                "official_data_url": row.get("query_url", ""),
                "request_parameters": row.get("request_body", ""),
                "http_status": "200",
                "response_business_date": "N/A",
                "result_count": row.get("result_count", "0"),
                "local_file": row.get("file", ""),
                "retrieved_at": row.get("retrieved_at", ""),
                "evidence_grade": "EVENT_SEARCH_ONLY",
                "validation_status": "NOT_BOUNDARY_EVIDENCE",
                "notes": "窗口内风险警示关键词公告检索为0，但不能单独证明历史NON_ST。",
            }
        )
    return attempts


def boundary_evidence_mapping(manifest: list[dict]) -> list[dict]:
    manifest_by_source_id = {r["source_id"]: r for r in manifest}
    rows = []
    for symbol in SH_SYMBOLS:
        stock_source_id = f"sse-stock-list-{symbol}-20260806"
        stock = manifest_by_source_id.get(stock_source_id, {})
        stock_file = stock.get("file", "")
        stock_hash = stock.get("sha256", "")
        stock_url = stock.get("official_url", "")
        for role, required_date in [
            ("baseline_2025-07-25", "2025-07-25"),
            ("endpoint_2026-07-27", "2026-07-27"),
        ]:
            rows.append(
                {
                    "symbol": symbol,
                    "exchange": "SH",
                    "board": "main",
                    "evidence_role": role,
                    "required_date": required_date,
                    "evidence_business_date": "",
                    "official_page_url": "https://www.sse.com.cn/assortment/stock/list/share/",
                    "official_data_url": stock_url,
                    "local_file": (
                        f"{stock_file}; data/manual/stage8/security_status/sources/"
                        "SH/sse_risk_warning_plate_2026-08-06.json"
                    ),
                    "retrieved_at": stock.get("retrieved_at", ""),
                    "sha256": stock_hash,
                    "status_value": "UNKNOWN",
                    "listing_status": "CURRENT_LISTED_ONLY",
                    "risk_warning_flag": "CURRENT_ABSENT_ONLY",
                    "date_mapping_reason": (
                        "官方接口无历史日期参数，当前快照无业务日期，"
                        f"不能映射至{required_date}。"
                    ),
                    "evidence_grade": "CURRENT_ONLY",
                    "validation_status": "PARTIAL",
                    "notes": (
                        "普通公告PDF已剔除；未找到上交所历史风险警示名单或历史证券列表，"
                        "历史边界状态未证明。"
                    ),
                }
            )
    return rows


def remaining_source_gap_list() -> list[dict]:
    rows = []
    for symbol in SH_SYMBOLS:
        for role, required_date, evidence_kind in [
            (
                "baseline_2025-07-25",
                "2025-07-25",
                "上交所2025-07-25历史风险警示名单或历史证券列表快照",
            ),
            (
                "endpoint_2026-07-27",
                "2026-07-27",
                "上交所2026-07-27历史风险警示名单或历史证券列表快照",
            ),
        ]:
            rows.append(
                {
                    "symbol": symbol,
                    "exchange": "SH",
                    "required_date": required_date,
                    "evidence_role": role,
                    "gap_type": "MISSING_HISTORICAL_STATUS_SNAPSHOT",
                    "missing_evidence": evidence_kind,
                    "required_evidence_kind": (
                        "历史风险警示板名单 / 历史证券列表 / 带业务日期的官方状态快照"
                    ),
                    "validation_status": "PARTIAL",
                    "notes": (
                        "当前快照与公告检索不可替代历史边界证据；"
                        "若官方历史数据仅订阅提供，需另行取得授权后补充。"
                    ),
                }
            )
    return rows


def download_manifest_current_run() -> list[dict]:
    files = sorted(RUN_DIR.glob("*.html")) + sorted(RUN_DIR.glob("*.js")) + sorted(
        RUN_DIR.glob("*.jsonp")
    ) + sorted(RUN_DIR.glob("*.pdf"))
    rows = []
    for path in files:
        rows.append(
            {
                "file": path.as_posix(),
                "size_bytes": path.stat().st_size,
                "sha256": sha256_of(path),
                "kind": path.suffix.lstrip("."),
            }
        )
    return rows


def main() -> None:
    manifest = load_manifest()
    search_log = load_search_log()
    reassessment = existing_source_reassessment(manifest)
    write_csv(
        RUN_DIR / "existing_source_reassessment.csv",
        [
            "source_id",
            "symbol",
            "source_kind",
            "file",
            "document_date",
            "official_url",
            "sha256",
            "evidence_role",
            "historical_capability",
            "evidence_grade",
            "validation_status",
            "note",
        ],
        reassessment,
    )
    endpoints = official_endpoint_inventory()
    write_csv(
        RUN_DIR / "official_endpoint_inventory.csv",
        [
            "endpoint_name",
            "official_page_url",
            "official_data_url",
            "query_parameters",
            "response_fields",
            "business_date_field",
            "pagination",
            "historical_capability",
            "access_model",
            "evidence_use",
            "source_reference",
            "notes",
        ],
        endpoints,
    )
    attempts = historical_query_attempts(manifest, search_log)
    write_csv(
        RUN_DIR / "historical_query_attempts.csv",
        [
            "attempt_id",
            "symbol_scope",
            "query_type",
            "target_date",
            "official_page_url",
            "official_data_url",
            "request_parameters",
            "http_status",
            "response_business_date",
            "result_count",
            "local_file",
            "retrieved_at",
            "evidence_grade",
            "validation_status",
            "notes",
        ],
        attempts,
    )
    mapping = boundary_evidence_mapping(manifest)
    write_csv(
        RUN_DIR / "boundary_evidence_mapping.csv",
        [
            "symbol",
            "exchange",
            "board",
            "evidence_role",
            "required_date",
            "evidence_business_date",
            "official_page_url",
            "official_data_url",
            "local_file",
            "retrieved_at",
            "sha256",
            "status_value",
            "listing_status",
            "risk_warning_flag",
            "date_mapping_reason",
            "evidence_grade",
            "validation_status",
            "notes",
        ],
        mapping,
    )
    gaps = remaining_source_gap_list()
    write_csv(
        RUN_DIR / "remaining_source_gap_list.csv",
        [
            "symbol",
            "exchange",
            "required_date",
            "evidence_role",
            "gap_type",
            "missing_evidence",
            "required_evidence_kind",
            "validation_status",
            "notes",
        ],
        gaps,
    )
    current_downloads = download_manifest_current_run()
    write_csv(
        RUN_DIR / "sse_audit_download_manifest.csv",
        ["file", "size_bytes", "sha256", "kind"],
        current_downloads,
    )
    summary = {
        "run_id": "20260806_153639",
        "branch": "feature/stage15-authoritative-sources",
        "audit_type": "sse_historical_status_snapshot",
        "retrieved_at": "2026-08-06T15:36:39+08:00",
        "boundary_dates": ["2025-07-25", "2026-07-27"],
        "target_sh_symbols": SH_SYMBOLS,
        "existing_download_count": len(manifest),
        "existing_source_reassessment_count": len(reassessment),
        "historical_risk_warning_list_found": False,
        "historical_securities_list_found": False,
        "current_only_riskplate": True,
        "current_only_stock_list": True,
        "sseinfo_historical_access": "SUBSCRIPTION_ONLY",
        "ordinary_announcement_misuse_check": "PASS",
        "sse_baseline_2025_07_25_complete": 0,
        "sse_endpoint_2026_07_27_complete": 0,
        "sse_source_chain_complete": 0,
        "all_16_source_chain_complete": 0,
        "conflict_symbol_count": 0,
        "partial_symbols": SH_SYMBOLS,
        "blocked_symbols": [],
        "can_draft_security_status_history_csv": False,
        "can_run_stage8_status_build_validate_only": False,
        "can_run_stage8_rebuild": False,
        "notes": [
            "上交所风险警示板和A股列表接口均为CURRENT_ONLY，无历史日期参数。",
            "上交所历史数据/证券基本信息文件属于SSEINFO订阅产品，未取得公开下载入口。",
            "普通上市公司公告PDF已按纠正标准剔除，不作为边界状态证据。",
            "深市8只股票原边界证据也包含普通公告PDF，纠正标准后同样不视为完整；本轮未另行收集深市历史快照。",
        ],
    }
    with (RUN_DIR / "audit_summary.json").open("w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f"wrote audit outputs to {RUN_DIR}")


if __name__ == "__main__":
    main()
