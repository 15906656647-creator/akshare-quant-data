"""Stage 2 network diagnostics that never request financial data."""
from __future__ import annotations

import json
import os
import socket
import ssl
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .adapters.akshare_probe import _sanitize_message


PREFLIGHT_HOSTS = (
    "push2his.eastmoney.com",
    "push2.eastmoney.com",
    "quotes.sina.cn",
    "money.finance.sina.com.cn",
    "emweb.securities.eastmoney.com",
    "datacenter-api.jin10.com",
)
PROXY_ENV_NAMES = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY")
CA_ENV_NAMES = ("REQUESTS_CA_BUNDLE", "SSL_CERT_FILE")


def _environment_presence(names: tuple[str, ...]) -> dict[str, bool]:
    """Return presence flags only; never expose environment values."""
    return {
        name: bool(os.environ.get(name) or os.environ.get(name.lower()))
        for name in names
    }


def _classify_layer_error(exc: BaseException, layer: str) -> str:
    if isinstance(exc, socket.gaierror) or layer == "dns":
        return "dns_error"
    if isinstance(exc, (socket.timeout, TimeoutError)):
        return "timeout"
    if isinstance(exc, ssl.SSLError) or layer == "tls":
        return "ssl_error"
    return "connection_error"


def _check_host(host: str, timeout: float) -> dict[str, Any]:
    result: dict[str, Any] = {
        "host": host,
        "dns_status": "fail",
        "resolved_addresses": [],
        "tcp_443_status": "not_tested",
        "tls_status": "not_tested",
        "error_layer": "",
        "error_type": "",
        "error_summary": "",
    }
    try:
        infos = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        addresses = sorted({entry[4][0] for entry in infos})
        result["resolved_addresses"] = addresses
        result["dns_status"] = "pass"
    except Exception as exc:
        result["error_layer"] = "dns"
        result["error_type"] = _classify_layer_error(exc, "dns")
        result["error_summary"] = _sanitize_message(exc)
        return result

    try:
        raw_socket = socket.create_connection((host, 443), timeout=timeout)
        result["tcp_443_status"] = "pass"
    except Exception as exc:
        result["tcp_443_status"] = "fail"
        result["error_layer"] = "tcp"
        result["error_type"] = _classify_layer_error(exc, "tcp")
        result["error_summary"] = _sanitize_message(exc)
        return result

    try:
        context = ssl.create_default_context()
        with raw_socket:
            with context.wrap_socket(raw_socket, server_hostname=host):
                result["tls_status"] = "pass"
    except Exception as exc:
        result["tls_status"] = "fail"
        result["error_layer"] = "tls"
        result["error_type"] = _classify_layer_error(exc, "tls")
        result["error_summary"] = _sanitize_message(exc)
    return result


def _markdown_report(report: dict[str, Any]) -> str:
    lines = [
        "# Stage 2 Network Preflight",
        "",
        f"- Checked at: `{report['checked_at']}`",
        f"- Overall status: **{report['overall_status']}**",
        f"- Proxy environment detected: `{report['proxy_detected']}`",
        f"- CA environment configured: `{report['ca_environment_configured']}`",
        "",
        "Only environment-variable presence is reported; proxy and CA values are never recorded.",
        "",
        "| host | DNS | TCP 443 | TLS | error layer | error type |",
        "|---|---|---|---|---|---|",
    ]
    for item in report["hosts"]:
        lines.append(
            f"| {item['host']} | {item['dns_status']} | "
            f"{item['tcp_443_status']} | {item['tls_status']} | "
            f"{item['error_layer'] or '-'} | {item['error_type'] or '-'} |"
        )
    lines.extend(
        [
            "",
            "This diagnostic performs DNS resolution, TCP 443 connection, and TLS "
            "handshake only. It does not request or save financial data.",
            "",
        ]
    )
    return "\n".join(lines)


def run_network_preflight(
    *,
    hosts: tuple[str, ...] = PREFLIGHT_HOSTS,
    timeout: float = 5.0,
    output_path: str | Path | None = None,
    markdown_path: str | Path | None = None,
) -> dict[str, Any]:
    proxy_presence = _environment_presence(PROXY_ENV_NAMES)
    ca_presence = _environment_presence(CA_ENV_NAMES)
    with ThreadPoolExecutor(max_workers=max(1, min(len(hosts), 6))) as executor:
        host_results = list(executor.map(lambda host: _check_host(host, timeout), hosts))
    overall = (
        "PASS"
        if host_results
        and all(
            item["dns_status"] == "pass"
            and item["tcp_443_status"] == "pass"
            and item["tls_status"] == "pass"
            for item in host_results
        )
        else "BLOCKED"
    )
    report = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "proxy_detected": any(proxy_presence.values()),
        "proxy_environment": proxy_presence,
        "ca_environment_configured": any(ca_presence.values()),
        "ca_environment": ca_presence,
        "hosts": host_results,
        "overall_status": overall,
    }
    if output_path:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(report, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    if markdown_path:
        path = Path(markdown_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_markdown_report(report), encoding="utf-8")
    return report
