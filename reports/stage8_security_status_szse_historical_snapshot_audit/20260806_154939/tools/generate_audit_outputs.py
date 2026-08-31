"""Generate machine-readable outputs for the SZSE historical snapshot audit.

This helper only writes audit artifacts under the current run directory. It
does not modify project code, tests, or real Stage8 data.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
from pathlib import Path


RUN_DIR = Path(
    "reports/stage8_security_status_szse_historical_snapshot_audit/20260806_154939"
)
ORIGINAL_RUN_DIR = Path(
    "reports/stage8_security_status_source_collection/20260806_143005"
)
SOURCE_BASE = Path("data/manual/stage8/security_status/sources/SZ")
MANIFEST = ORIGINAL_RUN_DIR / "download_manifest.csv"
SEARCH_LOG = ORIGINAL_RUN_DIR / "official_search_log.csv"

SZ_SYMBOLS = [
    "000100",
    "002067",
    "002129",
    "002230",
    "002361",
    "002600",
    "300274",
    "300433",
]
BOARDS = {
    "000100": "main",
    "002067": "main",
    "002129": "main",
    "002230": "main",
    "002361": "main",
    "002600": "main",
    "300274": "growth",
    "300433": "growth",
}


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


def current_names() -> dict[str, str]:
    names: dict[str, str] = {}
    for symbol in SZ_SYMBOLS:
        path = SOURCE_BASE / symbol / f"szse_stock_list_{symbol}_2026-08-06.json"
        if not path.exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        for tab in data:
            for row in tab.get("data", []):
                if row.get("agdm") == symbol:
                    names[symbol] = re.sub(r"<[^>]+>", "", row.get("agjc", "")).strip()
    return names


def existing_source_reassessment(manifest: list[dict]) -> list[dict]:
    rows = []
    for r in manifest:
        if r.get("symbol") not in {*SZ_SYMBOLS, "SZ"}:
            continue
        kind = r.get("source_kind", "")
        if kind == "company_announcement_pdf":
            role = "BOUNDARY_ATTEMPT_INVALID"
            capability = "NO_STATUS_SNAPSHOT"
            grade = "INVALID_FOR_BOUNDARY"
            status = "REJECTED"
            note = "普通上市公司公告PDF不能单独证明NON_ST，按纠正标准剔除。"
        elif kind == "announcement_search_result":
            role = "EVENT_SEARCH_SUPPORT_ONLY"
            capability = "EVENT_SEARCH_ONLY"
            grade = "EVENT_SEARCH_ONLY"
            status = "NOT_BOUNDARY_EVIDENCE"
            note = "公告检索支持seDate日期范围，但只反映公告事件，不能证明历史证券状态快照。"
        elif kind == "exchange_stock_list":
            role = "CURRENT_STATUS_SUPPORT_ONLY"
            capability = "CURRENT_ONLY"
            grade = "CURRENT_ONLY"
            status = "NOT_BOUNDARY_EVIDENCE"
            note = "A股列表接口返回当前列表，metadata.subname为当前日期，无历史日期参数。"
        elif kind == "risk_warning_plate":
            role = "CURRENT_STATUS_SUPPORT_ONLY"
            capability = "CURRENT_ONLY"
            grade = "CURRENT_ONLY"
            status = "NOT_BOUNDARY_EVIDENCE"
            note = "风险警示板接口仅返回当前名单，无历史日期参数。"
        else:
            role = "OTHER"
            capability = "UNKNOWN"
            grade = "UNKNOWN"
            status = "UNKNOWN"
            note = "未归类来源类型。"
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
            "endpoint_name": "深交所风险警示板名单报表接口",
            "official_page_url": "https://www.szse.cn/disclosure/listed/warn/index.html",
            "official_data_url": "https://www.szse.cn/api/report/ShowReport/data",
            "query_parameters": "SHOWTYPE=JSON; CATALOGID=fxjsb; TABKEY; PAGENO; random",
            "response_fields": "metadata.subname; data -> zqdm, gsjc",
            "business_date_field": "metadata.subname为当前日期，无历史日期参数",
            "pagination": "是，PAGENO/pagecount/recordcount",
            "historical_capability": "CURRENT_ONLY",
            "access_model": "公开网页接口",
            "evidence_use": "只能证明检索时点是否在风险警示板，不能证明历史边界状态",
            "source_reference": "https://www.szse.cn/modules/report/js/report_new.min.js",
            "notes": "官方JS将查询条件由报表metadata.conditions生成，fxjsb无date条件。",
        },
        {
            "endpoint_name": "深交所A股列表报表接口",
            "official_page_url": "https://www.szse.cn/market/product/stock/list/index.html",
            "official_data_url": "https://www.szse.cn/api/report/ShowReport/data",
            "query_parameters": "SHOWTYPE=JSON; CATALOGID=1110; TABKEY; PAGENO; txtDMorJC; selectHylb; selectModule; txtShengorShi",
            "response_fields": "agdm, agjc, agssrq, agzgb, agltgb, ylbz",
            "business_date_field": "metadata.subname为当前日期，无历史日期参数",
            "pagination": "是，PAGENO/pagecount/recordcount",
            "historical_capability": "CURRENT_ONLY",
            "access_model": "公开网页接口",
            "evidence_use": "只能证明当前A股列表，不能映射至2025-07-25或2026-07-27",
            "source_reference": "https://www.szse.cn/modules/report/js/report_new.min.js",
            "notes": "metadata.conditions不含date输入项。",
        },
        {
            "endpoint_name": "深交所全部产品列表报表接口",
            "official_page_url": "https://www.szse.cn/market/product/list/all/index.html",
            "official_data_url": "https://www.szse.cn/api/report/ShowReport/data",
            "query_parameters": "SHOWTYPE=JSON; CATALOGID=1105; TABKEY; PAGENO; txtkey1; txtkey2; selectJjlb; selectTzlb",
            "response_fields": "sys_key, jjjcurl, ssrq, dqgm",
            "business_date_field": "metadata.subname为当前日期，无历史日期参数",
            "pagination": "是，PAGENO/pagecount/recordcount",
            "historical_capability": "CURRENT_ONLY",
            "access_model": "公开网页接口",
            "evidence_use": "主要包含基金列表，不能用于股票历史边界状态",
            "source_reference": "https://www.szse.cn/modules/report/js/report_new.min.js",
            "notes": "metadata.conditions不含date输入项。",
        },
        {
            "endpoint_name": "深交所证券名称变更报表接口",
            "official_page_url": "https://www.szse.cn/market/stock/changename/index.html",
            "official_data_url": "https://www.szse.cn/api/report/ShowReport/data",
            "query_parameters": "SHOWTYPE=JSON; CATALOGID=SSGSGMXX; TABKEY=tab2; PAGENO; txtZqdm; txtKsrq; txtZzrq",
            "response_fields": "bgrq, zqdm, zqjc, bgqzqjc, bghzqjc",
            "business_date_field": "txtKsrq/txtZzrq为变更事件日期范围",
            "pagination": "是，PAGENO/pagecount/recordcount",
            "historical_capability": "EVENT_SEARCH_ONLY",
            "access_model": "公开网页接口",
            "evidence_use": "只提供证券简称变更事件，不能证明无变更或无风险警示状态",
            "source_reference": "https://www.szse.cn/modules/report/js/report_new.min.js",
            "notes": "窗口内8只目标股票名称变更查询结果均为0。",
        },
        {
            "endpoint_name": "深交所暂停/终止上市报表接口",
            "official_page_url": "https://www.szse.cn/market/stock/suspend/index.html",
            "official_data_url": "https://www.szse.cn/api/report/ShowReport/data",
            "query_parameters": "SHOWTYPE=JSON; CATALOGID=1793_ssgs; TABKEY; PAGENO; selectModule",
            "response_fields": "zqdm, zqjc, ssrq, ztrq, zzrq",
            "business_date_field": "无历史日期参数",
            "pagination": "是，PAGENO/pagecount/recordcount",
            "historical_capability": "CURRENT_ONLY",
            "access_model": "公开网页接口",
            "evidence_use": "只提供当前暂停/终止上市列表，且当前为空",
            "source_reference": "https://www.szse.cn/modules/report/js/report_new.min.js",
            "notes": "metadata.conditions仅selectModule，无日期。",
        },
        {
            "endpoint_name": "深交所公告检索接口",
            "official_page_url": "https://www.szse.cn/disclosure/listed/notice/index.html",
            "official_data_url": "https://www.szse.cn/api/disc/announcement/annList",
            "query_parameters": "POST body -> seDate, stock, keyword, channelCode, random",
            "response_fields": "announcementTitle, announcementTime, attachmentPath",
            "business_date_field": "seDate为公告日期范围",
            "pagination": "是，pageSize/pageNum",
            "historical_capability": "EVENT_SEARCH_ONLY",
            "access_model": "公开网页接口",
            "evidence_use": "只用于事件检索，不能单独证明历史NON_ST",
            "source_reference": "原收集脚本 collect_official_sources.py",
            "notes": "原审计窗口内风险警示等关键词检索为0。",
        },
        {
            "endpoint_name": "深交所统计月报-证券停牌情况",
            "official_page_url": "https://www.szse.cn/market/periodical/month/index.html",
            "official_data_url": "http://docs.static.szse.cn/www/market/periodical/month/W020250805527892740980.html",
            "query_parameters": "静态HTML，按月度归档",
            "response_fields": "代码、证券简称、停牌原因、停牌时间、复牌时间",
            "business_date_field": "停牌时间/复牌时间为精确日期时间",
            "pagination": "否",
            "historical_capability": "EVENT_SEARCH_ONLY",
            "access_model": "公开网页",
            "evidence_use": "提供月度停牌/风险警示事件区间，但不能证明未列示证券的状态",
            "source_reference": "https://www.szse.cn/market/periodical/month/t20250805_615341.html",
            "notes": "2025-07与2026-07月报均未列示8只目标股票。",
        },
        {
            "endpoint_name": "深圳证券信息公司-深市增强行情历史数据",
            "official_page_url": "http://www.szsi.cn/cpfw/fwsq/hq/yw-2.htm",
            "official_data_url": "无公开按日下载URL",
            "query_parameters": "授权接入，非公开查询",
            "response_fields": "逐笔委托、逐笔成交、证券行情快照、证券委托队列、证券信息、证券状态、指数快照",
            "business_date_field": "按交易日落地文件",
            "pagination": "不适用",
            "historical_capability": "SUBSCRIPTION_ONLY",
            "access_model": "授权/订阅",
            "evidence_use": "官方说明历史增强行情自2008-01-01提供，含证券信息与证券状态，但未授权访问",
            "source_reference": "http://www.szsi.cn/cpfw/fwsq/hq/yw-2.htm",
            "notes": "未取得授权，不能直接作为本项目历史边界证据。",
        },
        {
            "endpoint_name": "深圳证券信息公司-巨潮数据库",
            "official_page_url": "http://www.szsi.cn/cpfw/fwsq/hq/xxsj/jcsjk.htm",
            "official_data_url": "无公开下载URL",
            "query_parameters": "商业产品申请",
            "response_fields": "证券信息历史及现状、公告、市场交易等",
            "business_date_field": "数据库按历史维护",
            "pagination": "不适用",
            "historical_capability": "SUBSCRIPTION_ONLY",
            "access_model": "商业授权",
            "evidence_use": "官方说明可反映证券信息历史，但需联系数据营销部申请",
            "source_reference": "http://www.szsi.cn/cpfw/fwsq/hq/xxsj/jcsjk.htm",
            "notes": "未取得授权，未下载实际历史文件。",
        },
        {
            "endpoint_name": "深交所英文数据服务",
            "official_page_url": "http://www.szse.cn/www/English/services/dataServices/index.html",
            "official_data_url": "无公开下载URL",
            "query_parameters": "商业数据服务",
            "response_fields": "Level-1/Level-2行情、公司数据、名称变更、退市风险警示等",
            "business_date_field": "服务按授权交付",
            "pagination": "不适用",
            "historical_capability": "SUBSCRIPTION_ONLY",
            "access_model": "授权数据服务",
            "evidence_use": "官方说明包含历史公司元素与风险警示信息，但需SSIC授权",
            "source_reference": "http://www.szse.cn/www/English/services/dataServices/index.html",
            "notes": "未取得授权。",
        },
        {
            "endpoint_name": "深交所数据文件交换接口-现货证券收盘行情文件",
            "official_page_url": "http://www.szse.cn/www/marketServices/technicalservice/notice/t20200508_576947.html",
            "official_data_url": "cashsecurityclosemd_YYYYMMDD.xml（经文件网关下发）",
            "query_parameters": "YYYYMMDD按日文件命名",
            "response_fields": "证券成交总量、成交总金额等收盘行情",
            "business_date_field": "文件名中的YYYYMMDD",
            "pagination": "不适用",
            "historical_capability": "TECHNICAL_INTERFACE_ONLY",
            "access_model": "深交所技术系统/文件网关",
            "evidence_use": "官方通知确认存在按日收盘行情文件，但未提供公开下载入口",
            "source_reference": "http://www.szse.cn/www/marketServices/technicalservice/notice/t20200508_576947.html",
            "notes": "本轮未获得文件本体。",
        },
    ]


def historical_query_attempts(search_log: list[dict]) -> list[dict]:
    attempts = [
        {
            "attempt_id": "szse-riskpage-20260806_154939",
            "symbol_scope": "SZ_ALL",
            "query_type": "official_page_inspection",
            "target_date": "N/A",
            "official_page_url": "https://www.szse.cn/disclosure/listed/warn/index.html",
            "official_data_url": "N/A",
            "request_parameters": "GET HTML",
            "http_status": "200",
            "response_business_date": "无",
            "result_count": "1",
            "local_file": "reports/stage8_security_status_szse_historical_snapshot_audit/20260806_154939/szse_risk_warning_page.html",
            "retrieved_at": "2026-08-06T15:49:39+08:00",
            "evidence_grade": "CURRENT_ONLY",
            "validation_status": "NO_HISTORY_INTERFACE",
            "notes": "页面仅加载当前风险警示板报表，无历史名单入口。",
        },
        {
            "attempt_id": "szse-riskplate-full-pages-20260806_154939",
            "symbol_scope": "SZ_ALL",
            "query_type": "current_snapshot",
            "target_date": "N/A",
            "official_page_url": "https://www.szse.cn/disclosure/listed/warn/index.html",
            "official_data_url": "https://www.szse.cn/api/report/ShowReport/data",
            "request_parameters": "CATALOGID=fxjsb; TABKEY=tab1; PAGENO=1..7",
            "http_status": "200",
            "response_business_date": "subname=2026-08-06",
            "result_count": "123",
            "local_file": "reports/stage8_security_status_szse_historical_snapshot_audit/20260806_154939/szse_riskplate_p1.json ... p7.json",
            "retrieved_at": "2026-08-06T15:49:39+08:00",
            "evidence_grade": "CURRENT_ONLY",
            "validation_status": "NOT_HISTORICAL",
            "notes": "完整123只当前风险警示股票中，8只目标股票均不在名单；该结果不能映射历史边界。",
        },
        {
            "attempt_id": "szse-stocklist-page-20260806_154939",
            "symbol_scope": "SZ_ALL",
            "query_type": "official_page_inspection",
            "target_date": "N/A",
            "official_page_url": "https://www.szse.cn/market/product/stock/list/index.html",
            "official_data_url": "N/A",
            "request_parameters": "GET HTML",
            "http_status": "200",
            "response_business_date": "无",
            "result_count": "1",
            "local_file": "reports/stage8_security_status_szse_historical_snapshot_audit/20260806_154939/szse_stock_list_page.html",
            "retrieved_at": "2026-08-06T15:49:39+08:00",
            "evidence_grade": "CURRENT_ONLY",
            "validation_status": "NO_HISTORY_INTERFACE",
            "notes": "A股列表页metadata.conditions不含日期。",
        },
        {
            "attempt_id": "szse-stocklist-current-20260806_154939",
            "symbol_scope": "SZ_ALL",
            "query_type": "current_snapshot",
            "target_date": "N/A",
            "official_page_url": "https://www.szse.cn/market/product/stock/list/index.html",
            "official_data_url": "https://www.szse.cn/api/report/ShowReport/data",
            "request_parameters": "CATALOGID=1110; TABKEY=tab1; txtDMorJC",
            "http_status": "200",
            "response_business_date": "subname=2026-08-06",
            "result_count": "8",
            "local_file": "data/manual/stage8/security_status/sources/SZ/<symbol>/szse_stock_list_<symbol>_2026-08-06.json",
            "retrieved_at": "2026-08-06T14:35:53+08:00",
            "evidence_grade": "CURRENT_ONLY",
            "validation_status": "NOT_HISTORICAL",
            "notes": "现有8个A股列表JSON均为当前快照。",
        },
        {
            "attempt_id": "szse-namechange-page-20260806_154939",
            "symbol_scope": "SZ_ALL",
            "query_type": "official_page_inspection",
            "target_date": "N/A",
            "official_page_url": "https://www.szse.cn/market/stock/changename/index.html",
            "official_data_url": "N/A",
            "request_parameters": "GET HTML",
            "http_status": "200",
            "response_business_date": "无",
            "result_count": "1",
            "local_file": "reports/stage8_security_status_szse_historical_snapshot_audit/20260806_154939/szse_stock_namechange_page.html",
            "retrieved_at": "2026-08-06T15:49:39+08:00",
            "evidence_grade": "EVENT_SEARCH_ONLY",
            "validation_status": "DATE_RANGE_EVENT_ONLY",
            "notes": "名称变更报表支持txtKsrq/txtZzrq，但只返回变更事件。",
        },
        {
            "attempt_id": "szse-namechange-metadata-20260806_154939",
            "symbol_scope": "SZ_ALL",
            "query_type": "official_endpoint_metadata",
            "target_date": "N/A",
            "official_page_url": "https://www.szse.cn/market/stock/changename/index.html",
            "official_data_url": "https://www.szse.cn/api/report/ShowReport/data",
            "request_parameters": "CATALOGID=SSGSGMXX; TABKEY=tab2; PAGENO=1",
            "http_status": "200",
            "response_business_date": "txtKsrq/txtZzrq日期控件",
            "result_count": "0",
            "local_file": "reports/stage8_security_status_szse_historical_snapshot_audit/20260806_154939/szse_namechange_metadata.json",
            "retrieved_at": "2026-08-06T15:49:39+08:00",
            "evidence_grade": "EVENT_SEARCH_ONLY",
            "validation_status": "NOT_BOUNDARY_EVIDENCE",
            "notes": "官方metadata确认存在起止日期条件。",
        },
        {
            "attempt_id": "szse-suspend-page-20260806_154939",
            "symbol_scope": "SZ_ALL",
            "query_type": "official_page_inspection",
            "target_date": "N/A",
            "official_page_url": "https://www.szse.cn/market/stock/suspend/index.html",
            "official_data_url": "N/A",
            "request_parameters": "GET HTML",
            "http_status": "200",
            "response_business_date": "无",
            "result_count": "1",
            "local_file": "reports/stage8_security_status_szse_historical_snapshot_audit/20260806_154939/szse_stock_suspend_page.html",
            "retrieved_at": "2026-08-06T15:49:39+08:00",
            "evidence_grade": "CURRENT_ONLY",
            "validation_status": "NO_HISTORY_INTERFACE",
            "notes": "暂停/终止上市页面仅当前列表。",
        },
        {
            "attempt_id": "szse-suspend-metadata-20260806_154939",
            "symbol_scope": "SZ_ALL",
            "query_type": "official_endpoint_metadata",
            "target_date": "N/A",
            "official_page_url": "https://www.szse.cn/market/stock/suspend/index.html",
            "official_data_url": "https://www.szse.cn/api/report/ShowReport/data",
            "request_parameters": "CATALOGID=1793_ssgs; TABKEY=tab1; PAGENO=1",
            "http_status": "200",
            "response_business_date": "无",
            "result_count": "0",
            "local_file": "reports/stage8_security_status_szse_historical_snapshot_audit/20260806_154939/szse_suspend_metadata.json",
            "retrieved_at": "2026-08-06T15:49:39+08:00",
            "evidence_grade": "CURRENT_ONLY",
            "validation_status": "NOT_HISTORICAL",
            "notes": "暂停/终止上市当前名单为空，且无日期参数。",
        },
        {
            "attempt_id": "szse-allproduct-page-20260806_154939",
            "symbol_scope": "SZ_ALL",
            "query_type": "official_page_inspection",
            "target_date": "N/A",
            "official_page_url": "https://www.szse.cn/market/product/list/all/index.html",
            "official_data_url": "N/A",
            "request_parameters": "GET HTML",
            "http_status": "200",
            "response_business_date": "无",
            "result_count": "1",
            "local_file": "reports/stage8_security_status_szse_historical_snapshot_audit/20260806_154939/szse_all_product_list_page.html",
            "retrieved_at": "2026-08-06T15:49:39+08:00",
            "evidence_grade": "CURRENT_ONLY",
            "validation_status": "NO_HISTORY_INTERFACE",
            "notes": "全部产品列表为当前列表，不含股票历史状态。",
        },
        {
            "attempt_id": "szse-monthly-202507-20260806_154939",
            "symbol_scope": "SZ_ALL",
            "query_type": "official_monthly_event_table",
            "target_date": "2025-07",
            "official_page_url": "https://www.szse.cn/market/periodical/month/t20250805_615341.html",
            "official_data_url": "http://docs.static.szse.cn/www/market/periodical/month/W020250805527892740980.html",
            "request_parameters": "GET HTML",
            "http_status": "200",
            "response_business_date": "停牌时间/复牌时间精确到时分",
            "result_count": "27",
            "local_file": "reports/stage8_security_status_szse_historical_snapshot_audit/20260806_154939/szse_suspension_202507.html",
            "retrieved_at": "2026-08-06T15:49:39+08:00",
            "evidence_grade": "EVENT_SEARCH_ONLY",
            "validation_status": "NOT_BOUNDARY_EVIDENCE",
            "notes": "8只目标股票均未出现在2025年7月停牌/风险警示事件表中。",
        },
        {
            "attempt_id": "szse-monthly-202607-20260806_154939",
            "symbol_scope": "SZ_ALL",
            "query_type": "official_monthly_event_table",
            "target_date": "2026-07",
            "official_page_url": "https://www.szse.cn/market/periodical/month/t20260806_622028.html",
            "official_data_url": "http://docs.static.szse.cn/www/market/periodical/month/W020260806351615093691.html",
            "request_parameters": "GET HTML",
            "http_status": "200",
            "response_business_date": "停牌时间/复牌时间精确到时分",
            "result_count": "22",
            "local_file": "reports/stage8_security_status_szse_historical_snapshot_audit/20260806_154939/szse_suspension_202607.html",
            "retrieved_at": "2026-08-06T15:49:39+08:00",
            "evidence_grade": "EVENT_SEARCH_ONLY",
            "validation_status": "NOT_BOUNDARY_EVIDENCE",
            "notes": "8只目标股票均未出现在2026年7月停牌/风险警示事件表中。",
        },
        {
            "attempt_id": "szse-listed-securities-202607-20260806_154939",
            "symbol_scope": "SZ_ALL",
            "query_type": "official_monthly_aggregate",
            "target_date": "2026-07",
            "official_page_url": "https://www.szse.cn/market/periodical/month/t20260806_622028.html",
            "official_data_url": "http://docs.static.szse.cn/www/market/periodical/month/W020260806349620016568.html",
            "request_parameters": "GET HTML",
            "http_status": "200",
            "response_business_date": "2026年7月底",
            "result_count": "1",
            "local_file": "reports/stage8_security_status_szse_historical_snapshot_audit/20260806_154939/szse_listed_securities_202607.html",
            "retrieved_at": "2026-08-06T15:49:39+08:00",
            "evidence_grade": "AGGREGATE_ONLY",
            "validation_status": "NOT_PER_SECURITY",
            "notes": "上市证券表仅给出总数，不按证券列出状态。",
        },
        {
            "attempt_id": "szsi-history-product-20260806_154939",
            "symbol_scope": "SZ_ALL",
            "query_type": "official_product_doc",
            "target_date": "N/A",
            "official_page_url": "http://www.szsi.cn/cpfw/fwsq/hq/yw-2.htm",
            "official_data_url": "N/A",
            "request_parameters": "GET HTML",
            "http_status": "200",
            "response_business_date": "历史增强行情自2008-01-01",
            "result_count": "1",
            "local_file": "reports/stage8_security_status_szse_historical_snapshot_audit/20260806_154939/szsi_hq_auth_page.html",
            "retrieved_at": "2026-08-06T15:49:39+08:00",
            "evidence_grade": "SUBSCRIPTION_ONLY",
            "validation_status": "NOT_PUBLIC_DOWNLOAD",
            "notes": "官方明确历史增强行情含证券信息、证券状态，但需授权。",
        },
        {
            "attempt_id": "szsi-basic-database-20260806_154939",
            "symbol_scope": "SZ_ALL",
            "query_type": "official_product_doc",
            "target_date": "N/A",
            "official_page_url": "http://www.szsi.cn/cpfw/fwsq/hq/xxsj/jcsjk.htm",
            "official_data_url": "N/A",
            "request_parameters": "GET HTML",
            "http_status": "200",
            "response_business_date": "数据库历史维护",
            "result_count": "1",
            "local_file": "reports/stage8_security_status_szse_historical_snapshot_audit/20260806_154939/szsi_basic_database_page.html",
            "retrieved_at": "2026-08-06T15:49:39+08:00",
            "evidence_grade": "SUBSCRIPTION_ONLY",
            "validation_status": "NOT_PUBLIC_DOWNLOAD",
            "notes": "巨潮数据库为商业产品，需联系数据营销部。",
        },
        {
            "attempt_id": "szse-data-services-20260806_154939",
            "symbol_scope": "SZ_ALL",
            "query_type": "official_product_doc",
            "target_date": "N/A",
            "official_page_url": "http://www.szse.cn/www/English/services/dataServices/index.html",
            "official_data_url": "N/A",
            "request_parameters": "GET HTML",
            "http_status": "200",
            "response_business_date": "数据服务按授权交付",
            "result_count": "1",
            "local_file": "reports/stage8_security_status_szse_historical_snapshot_audit/20260806_154939/szse_data_services_english.html",
            "retrieved_at": "2026-08-06T15:49:39+08:00",
            "evidence_grade": "SUBSCRIPTION_ONLY",
            "validation_status": "NOT_PUBLIC_DOWNLOAD",
            "notes": "SSIC授权数据服务包含历史公司元素和风险警示信息。",
        },
        {
            "attempt_id": "szse-tech-notice-cashsecurity-20260806_154939",
            "symbol_scope": "SZ_ALL",
            "query_type": "official_technical_doc",
            "target_date": "N/A",
            "official_page_url": "http://www.szse.cn/www/marketServices/technicalservice/notice/t20200508_576947.html",
            "official_data_url": "N/A",
            "request_parameters": "GET HTML",
            "http_status": "200",
            "response_business_date": "cashsecurityclosemd_YYYYMMDD.xml",
            "result_count": "1",
            "local_file": "reports/stage8_security_status_szse_historical_snapshot_audit/20260806_154939/szse_technical_notice_cashsecurity.html",
            "retrieved_at": "2026-08-06T15:49:39+08:00",
            "evidence_grade": "TECHNICAL_INTERFACE_ONLY",
            "validation_status": "NOT_PUBLIC_DOWNLOAD",
            "notes": "按日收盘行情文件通过文件网关下发，非公开网页下载。",
        },
    ]

    for row in search_log:
        symbol = row.get("symbol", "")
        if symbol not in SZ_SYMBOLS or row.get("query_type") != "keyword_riskwarning":
            continue
        attempts.append(
            {
                "attempt_id": f"prev-{symbol}-riskwarning-20260806_143005",
                "symbol_scope": symbol,
                "query_type": "announcement_event_search",
                "target_date": "2025-07-25至2026-07-27",
                "official_page_url": "https://www.szse.cn/disclosure/listed/notice/index.html",
                "official_data_url": "https://www.szse.cn/api/disc/announcement/annList",
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

    for symbol in SZ_SYMBOLS:
        attempts.append(
            {
                "attempt_id": f"szse-namechange-{symbol}-range-20260806_154939",
                "symbol_scope": symbol,
                "query_type": "name_change_event_search",
                "target_date": "2025-07-25至2026-07-27",
                "official_page_url": "https://www.szse.cn/market/stock/changename/index.html",
                "official_data_url": "https://www.szse.cn/api/report/ShowReport/data",
                "request_parameters": (
                    "CATALOGID=SSGSGMXX; TABKEY=tab2; "
                    f"txtZqdm={symbol}; txtKsrq=2025-07-25; txtZzrq=2026-07-27"
                ),
                "http_status": "200",
                "response_business_date": "N/A",
                "result_count": "0",
                "local_file": (
                    f"reports/stage8_security_status_szse_historical_snapshot_audit/"
                    f"20260806_154939/szse_namechange_{symbol}_range.json"
                ),
                "retrieved_at": "2026-08-06T15:49:39+08:00",
                "evidence_grade": "EVENT_SEARCH_ONLY",
                "validation_status": "NOT_BOUNDARY_EVIDENCE",
                "notes": "窗口内无证券简称变更事件记录，但不能证明无风险警示。",
            }
        )
    return attempts


def historical_file_inventory() -> list[dict]:
    rows = []
    files = sorted(RUN_DIR.glob("*.html")) + sorted(RUN_DIR.glob("*.js")) + sorted(
        RUN_DIR.glob("*.json")
    )
    for path in files:
        name = path.name
        if name.startswith("szse_riskplate_p") and name.endswith(".json"):
            kind = "current_risk_warning_plate_page"
            capability = "CURRENT_ONLY"
            grade = "CURRENT_ONLY"
            status = "NOT_HISTORICAL"
            business_date = "2026-08-06"
            note = "完整123只当前风险警示股票，8只目标均不在名单。"
        elif name in {
            "szse_suspension_202507.html",
            "szse_suspension_202607.html",
        }:
            kind = "official_monthly_suspension_event_table"
            capability = "EVENT_SEARCH_ONLY"
            grade = "EVENT_SEARCH_ONLY"
            status = "NOT_BOUNDARY_EVIDENCE"
            business_date = "2025-07/2026-07"
            note = "含精确停牌/风险警示事件区间，但不含目标股票，不能证明NON_ST。"
        elif name == "szse_listed_securities_202607.html":
            kind = "official_monthly_aggregate_table"
            capability = "AGGREGATE_ONLY"
            grade = "AGGREGATE_ONLY"
            status = "NOT_PER_SECURITY"
            business_date = "2026-07-31"
            note = "仅列出各类证券总数，不按证券给出状态。"
        elif name.startswith("szse_namechange_") and name.endswith("_range.json"):
            kind = "official_name_change_event_search"
            capability = "EVENT_SEARCH_ONLY"
            grade = "EVENT_SEARCH_ONLY"
            status = "NOT_BOUNDARY_EVIDENCE"
            business_date = "2025-07-25至2026-07-27"
            note = "窗口内该股票名称变更记录为0。"
        elif name == "szse_namechange_metadata.json":
            kind = "official_endpoint_metadata"
            capability = "EVENT_SEARCH_ONLY"
            grade = "EVENT_SEARCH_ONLY"
            status = "NOT_BOUNDARY_EVIDENCE"
            business_date = "txtKsrq/txtZzrq"
            note = "名称变更接口支持日期范围，但只返回事件。"
        elif name in {
            "szse_monthly_202507_index.html",
            "szse_monthly_202607_index.html",
        }:
            kind = "official_monthly_index"
            capability = "INDEX_ONLY"
            grade = "INDEX_ONLY"
            status = "NOT_BOUNDARY_EVIDENCE"
            business_date = "2025-07/2026-07"
            note = "月报目录页。"
        elif name in {
            "szsi_hq_auth_page.html",
            "szsi_basic_database_page.html",
            "szse_data_services_english.html",
        }:
            kind = "official_data_product_doc"
            capability = "SUBSCRIPTION_ONLY"
            grade = "SUBSCRIPTION_ONLY"
            status = "NOT_PUBLIC_DOWNLOAD"
            business_date = "N/A"
            note = "官方说明存在历史证券信息/证券状态数据，但需授权。"
        elif name == "szse_technical_notice_cashsecurity.html":
            kind = "official_technical_notice"
            capability = "TECHNICAL_INTERFACE_ONLY"
            grade = "TECHNICAL_INTERFACE_ONLY"
            status = "NOT_PUBLIC_DOWNLOAD"
            business_date = "cashsecurityclosemd_YYYYMMDD.xml"
            note = "按日收盘行情文件经文件网关下发。"
        elif name in {
            "szse_risk_warning_page.html",
            "szse_stock_list_page.html",
            "szse_stock_namechange_page.html",
            "szse_stock_suspend_page.html",
            "szse_all_product_list_page.html",
        }:
            kind = "official_page_shell"
            capability = "CURRENT_ONLY"
            grade = "CURRENT_ONLY"
            status = "NOT_BOUNDARY_EVIDENCE"
            business_date = "N/A"
            note = "页面本身无历史状态数据。"
        elif name.endswith(".js") or name in {
            "szsePath.js",
            "concatversion.js",
        }:
            kind = "official_js"
            capability = "SOURCE_OF_PARAMS"
            grade = "SOURCE_OF_PARAMS"
            status = "NOT_BOUNDARY_EVIDENCE"
            business_date = "N/A"
            note = "用于确认接口参数与日期能力。"
        else:
            kind = "other"
            capability = "UNKNOWN"
            grade = "UNKNOWN"
            status = "UNKNOWN"
            business_date = ""
            note = ""
        rows.append(
            {
                "file": path.as_posix(),
                "source_kind": kind,
                "official_page_url": "https://www.szse.cn/",
                "official_data_url": "N/A",
                "business_date": business_date,
                "size_bytes": path.stat().st_size,
                "sha256": sha256_of(path),
                "historical_capability": capability,
                "evidence_grade": grade,
                "validation_status": status,
                "notes": note,
            }
        )
    return rows


def boundary_evidence_mapping(manifest: list[dict]) -> list[dict]:
    names = current_names()
    manifest_by_source_id = {r["source_id"]: r for r in manifest}
    rows = []
    for symbol in SZ_SYMBOLS:
        stock = manifest_by_source_id.get(
            f"szse-stock-list-{symbol}-20260806", {}
        )
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
                    "exchange": "SZ",
                    "board": BOARDS[symbol],
                    "evidence_role": role,
                    "required_date": required_date,
                    "evidence_business_date": "",
                    "official_page_url": "https://www.szse.cn/market/product/stock/list/index.html",
                    "official_data_url": stock_url,
                    "local_file": (
                        f"{stock_file}; reports/stage8_security_status_szse_"
                        "historical_snapshot_audit/20260806_154939/"
                        "szse_riskplate_p1.json ... szse_riskplate_p7.json"
                    ),
                    "retrieved_at": stock.get("retrieved_at", ""),
                    "sha256": stock_hash,
                    "listing_status": "CURRENT_LISTED_ONLY",
                    "risk_warning_status": "CURRENT_ABSENT_ONLY",
                    "security_name": names.get(symbol, ""),
                    "date_mapping_reason": (
                        "深交所风险警示板和A股列表接口均无历史日期参数，"
                        f"当前快照不能映射至{required_date}。"
                    ),
                    "evidence_grade": "CURRENT_ONLY",
                    "validation_status": "PARTIAL",
                    "notes": (
                        "普通公告PDF已剔除；月度停牌/风险警示事件表不含该股票，"
                        "但零事件记录不能证明历史NON_ST；未取得历史证券状态快照。"
                    ),
                }
            )
    return rows


def remaining_source_gap_list() -> list[dict]:
    rows = []
    for symbol in SZ_SYMBOLS:
        for role, required_date, evidence_kind in [
            (
                "baseline_2025-07-25",
                "2025-07-25",
                "深交所2025-07-25历史风险警示名单或历史证券列表快照",
            ),
            (
                "endpoint_2026-07-27",
                "2026-07-27",
                "深交所2026-07-27历史风险警示名单或历史证券列表快照",
            ),
        ]:
            rows.append(
                {
                    "symbol": symbol,
                    "exchange": "SZ",
                    "required_date": required_date,
                    "evidence_role": role,
                    "gap_type": "MISSING_HISTORICAL_STATUS_SNAPSHOT",
                    "missing_evidence": evidence_kind,
                    "required_evidence_kind": (
                        "历史风险警示名单 / 历史证券列表 / 带业务日期的官方状态快照"
                    ),
                    "validation_status": "PARTIAL",
                    "notes": (
                        "公开网页仅有当前名单或事件检索；官方历史证券信息/证券状态"
                        "需通过深圳证券信息有限公司授权获取。"
                    ),
                }
            )
    return rows


def download_manifest_current_run() -> list[dict]:
    files = sorted(RUN_DIR.glob("*.html")) + sorted(RUN_DIR.glob("*.js")) + sorted(
        RUN_DIR.glob("*.json")
    )
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
    attempts = historical_query_attempts(search_log)
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
    file_inventory = historical_file_inventory()
    write_csv(
        RUN_DIR / "historical_file_inventory.csv",
        [
            "file",
            "source_kind",
            "official_page_url",
            "official_data_url",
            "business_date",
            "size_bytes",
            "sha256",
            "historical_capability",
            "evidence_grade",
            "validation_status",
            "notes",
        ],
        file_inventory,
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
            "listing_status",
            "risk_warning_status",
            "security_name",
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
    downloads = download_manifest_current_run()
    write_csv(
        RUN_DIR / "szse_audit_download_manifest.csv",
        ["file", "size_bytes", "sha256", "kind"],
        downloads,
    )
    summary = {
        "run_id": "20260806_154939",
        "branch": "feature/stage15-authoritative-sources",
        "audit_type": "szse_historical_status_snapshot",
        "retrieved_at": "2026-08-06T15:49:39+08:00",
        "boundary_dates": ["2025-07-25", "2026-07-27"],
        "target_sz_symbols": SZ_SYMBOLS,
        "existing_sz_source_count": len(reassessment),
        "historical_risk_warning_list_found": False,
        "historical_securities_list_found": False,
        "subscription_or_authorized_data_product_found": True,
        "current_riskplate_full_absent": True,
        "current_riskplate_record_count": 123,
        "monthly_suspension_event_table_found": True,
        "monthly_suspension_target_symbols_present": False,
        "name_change_event_query_found": True,
        "name_change_event_query_zero": True,
        "ordinary_announcement_misuse_check": "PASS",
        "szse_baseline_2025_07_25_complete": 0,
        "szse_endpoint_2026_07_27_complete": 0,
        "szse_source_chain_complete": 0,
        "all_16_source_chain_complete": 0,
        "conflict_symbol_count": 0,
        "partial_symbols": SZ_SYMBOLS,
        "blocked_symbols": [],
        "can_draft_security_status_history_csv": False,
        "can_run_stage8_status_build_validate_only": False,
        "can_run_stage8_rebuild": False,
        "notes": [
            "深交所风险警示板、A股列表、暂停/终止上市均为CURRENT_ONLY。",
            "名称变更接口支持日期范围，但只返回变更事件，8只目标窗口内均为0。",
            "月度停牌/风险警示事件表不含8只目标股票，但零事件不能证明历史NON_ST。",
            "深圳证券信息公司提供含证券信息/证券状态的历史增强行情数据，属授权订阅产品。",
            "普通公司公告PDF已按纠正标准剔除。",
        ],
    }
    with (RUN_DIR / "audit_summary.json").open("w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f"wrote SZSE audit outputs to {RUN_DIR}")


if __name__ == "__main__":
    main()
