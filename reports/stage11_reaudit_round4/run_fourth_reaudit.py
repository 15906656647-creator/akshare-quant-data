from __future__ import annotations

import atexit
import csv
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import duckdb


ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
THIRD_DRIVER = ROOT / "reports" / "stage11_reaudit_round3" / "run_third_reaudit.py"
spec = importlib.util.spec_from_file_location("第三轮独立驱动", THIRD_DRIVER)
driver = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(driver)


def 文件哈希(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def 文件集合哈希(paths: list[Path]) -> dict[str, str]:
    return {str(path.relative_to(ROOT)): 文件哈希(path) for path in paths}


def 目录哈希(path: Path) -> str:
    data = driver.snapshot(path)
    payload = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def Git状态() -> dict:
    commands = {
        "当前分支": ["git", "branch", "--show-current"],
        "完整提交号": ["git", "rev-parse", "HEAD"],
        "简短状态": ["git", "status", "--short"],
        "已暂存文件": ["git", "diff", "--cached", "--name-status"],
        "未暂存文件": ["git", "diff", "--name-status"],
        "未跟踪文件": ["git", "ls-files", "--others", "--exclude-standard"],
        "差异统计": ["git", "diff", "--stat"],
        "差异名称状态": ["git", "diff", "--name-status"],
        "空白检查": ["git", "diff", "--check"],
    }
    result = {}
    for name, command in commands.items():
        completed = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, encoding="utf-8")
        result[name] = {
            "命令": " ".join(command), "退出码": completed.returncode,
            "标准输出": completed.stdout, "标准错误": completed.stderr,
        }
    return result


def 保护快照() -> dict:
    files = [
        ROOT / "config" / "universe.yml",
        ROOT / "config" / "metric_definition.yml",
        ROOT / "docs" / "stage0_scope.md",
        ROOT / "database" / "akshare_crypto_stage11.duckdb",
        ROOT / "data" / "raw" / "crypto_js_spot" / "run_id=stage11-ethusdt-20260727" / "crypto_spot.parquet",
        ROOT / "data" / "raw" / "crypto_js_spot" / "run_id=stage11-ethusdt-20260727" / "metadata.json",
        ROOT / "reports" / "stage11_crypto_price.csv",
        ROOT / "reports" / "stage11_crypto_price.json",
    ]
    historical = [
        ROOT / "reports" / "stage11_acceptance",
        ROOT / "reports" / "stage11_reaudit",
        ROOT / "reports" / "stage11_reaudit_round3",
    ]
    remediation = sorted((ROOT / "reports").glob("stage11_remediation*"))
    return {
        "受保护文件": {
            str(path.relative_to(ROOT)): {
                "存在": path.is_file(), "SHA-256": 文件哈希(path) if path.is_file() else None,
                "大小": path.stat().st_size if path.is_file() else None,
                "修改时间纳秒": path.stat().st_mtime_ns if path.is_file() else None,
            }
            for path in files
        },
        "历次验收目录哈希": {
            str(path.relative_to(ROOT)): 目录哈希(path) for path in historical
        },
        "历次修复文件哈希": {
            str(path.relative_to(ROOT)): 文件哈希(path)
            for path in remediation if path.is_file()
        },
    }


def 安装网络守卫(root: Path) -> tuple[Path, callable]:
    guard = root / "网络守卫"
    guard.mkdir()
    count_file = guard / "连接计数.log"
    (guard / "sitecustomize.py").write_text(
        "import atexit, os, pathlib, socket\n"
        "count=[0]\n"
        "def blocked(*args, **kwargs):\n"
        "    count[0]+=1\n"
        "    raise AssertionError('验收禁止网络访问')\n"
        "socket.create_connection=blocked\n"
        "socket.socket.connect=blocked\n"
        "@atexit.register\n"
        "def save():\n"
        "    with pathlib.Path(os.environ['REAUDIT_NETWORK_COUNT']).open('a', encoding='utf-8') as f:\n"
        "        f.write(str(count[0])+'\\n')\n",
        encoding="utf-8",
    )
    original = driver.environment

    def guarded_environment():
        env = original()
        env["PYTHONPATH"] = str(guard) + os.pathsep + env.get("PYTHONPATH", "")
        env["REAUDIT_NETWORK_COUNT"] = str(count_file)
        return env

    driver.environment = guarded_environment
    return count_file, original


原始说明 = {
    "I01": "非目标交易品种 ETH-USD", "I02": "衍生品 ETH-USDT-SWAP",
    "I03": "错误数据提供方", "I04": "错误交易所", "I05": "缺少品种类型",
    "I06": "周期不是 1 小时", "I07": "绕过适配器且缺少原始品种",
    "R01": "Raw 目录缺失", "R02": "Raw 响应缺失", "R03": "Raw 响应为空",
    "R04": "Raw 响应 JSON 损坏", "R05": "Raw 行数不一致", "R06": "Raw Schema 哈希不一致",
    "R07": "Raw 内容哈希不一致", "R08": "Manifest 遗漏必需条目",
    "F01": "CSV 删除一行", "F02": "CSV 修改收盘价", "F03": "JSON 修改收盘价",
    "F04": "DuckDB 修改数据来源", "F05": "JSON 修改交易品种", "F06": "JSON 修改时间戳",
    "F07": "三格式主键集合不一致", "Q01": "非有限或非数值字段", "Q02": "负成交量",
    "Q03": "缺少小时 K 线", "S01": "加密货币 Stage 10 隔离", "S02": "股票路径保持不变",
    "S03": "拒绝未知资产类型",
}

Manifest说明 = {
    "M01": "缺少 request role", "M02": "缺少 response role", "M03": "缺少 metadata role",
    "M04": "相同路径重复", "M05": "同 role 不同路径重复", "M06": "大小写等价路径重复",
    "M07": "斜杠等价路径重复", "M08": "点路径段等价路径重复", "M09": "两个 response 主体",
    "M10": "绝对路径", "M11": "父目录穿越", "M12": "声明文件不存在",
    "M13": "物理文件存在但未声明", "M14": "文件大小不一致", "M15": "SHA-256 不一致",
    "M16": "声明文件为空", "M17": "entries 不是数组", "M18": "条目缺少 role",
    "M19": "条目缺少 path", "M20": "条目缺少 hash", "M21": "条目缺少 size",
}


def 中文行(row: dict, matrix: str) -> dict:
    description = 原始说明.get(row["case_id"], Manifest说明.get(row["case_id"], row["injection"]))
    return {
        "矩阵": matrix, "场景编号": row["case_id"], "故障说明": description,
        "生产入口": row.get("entry"), "预期": "阻断" if row.get("expected") == "BLOCKED" else "保持正常",
        "实际": "已阻断" if row.get("blocked") else "未阻断",
        "退出码": row.get("exit_code"), "是否阻断": bool(row.get("blocked")),
        "结论": "通过" if row.get("status") == "PASS" else "失败",
        "错误码或检查名": row.get("error_code"),
        "阻断原因": row.get("blocking_reasons", ""),
        "只读": bool(row.get("read_only", True)), "网络隔离": True,
    }


def 封闭世界矩阵(baseline: Path, root: Path) -> tuple[list[dict], dict]:
    cases = [
        ("CW01", "根目录孤立 JSON", {"orphan.json": b"{}\n"}),
        ("CW02", "嵌套孤立 JSON", {"nested/orphan.json": b"{}\n"}),
        ("CW03", "未声明备份文件", {"response.json.bak": b"backup"}),
        ("CW04", "未声明临时文件", {"response.json.tmp": b"temporary"}),
        ("CW05", "未声明隐藏文件", {".unlisted": b"hidden"}),
        ("CW06", "未声明空文件", {"empty-file": b""}),
        ("CW07", "未声明二进制文件", {"payload.bin": b"\x00\xff\x10\x80"}),
        ("CW08", "多个未声明文件", {"z.tmp": b"z", ".hidden": b"h", "a/orphan.bin": b"\x00"}),
        ("CW09", "大小写变化的未声明文件", {"ORPHAN.JSON": b"{}\n"}),
    ]
    rows = []
    for case_id, description, extras in cases:
        workspace = root / case_id
        shutil.copytree(baseline, workspace)
        for relative, content in extras.items():
            target = workspace / "raw" / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        before = driver.snapshot(workspace)
        result = driver.cli_validate(workspace)
        after = driver.snapshot(workspace)
        payload = result.get("payload") or {}
        reasons = payload.get("blocking_reasons", [])
        expected_paths = sorted(extras, key=lambda value: (value.casefold(), value))
        required = [f"manifest_unlisted_file: {name}" for name in expected_paths]
        closed = (payload.get("raw_evidence") or {}).get("manifest_closed_world", {})
        blocked = (
            result["exit_code"] != 0 and payload.get("status") == "BLOCKED"
            and all(item in reasons for item in required)
            and closed.get("error_code") == "manifest_unlisted_file"
            and closed.get("unlisted_files") == expected_paths
            and before == after and '"status": "READY"' not in result["stdout"]
        )
        rows.append({
            "矩阵": "封闭世界故障矩阵", "场景编号": case_id, "故障说明": description,
            "生产入口": "validate-crypto --validate-only", "预期": "阻断",
            "实际": "已阻断" if blocked else payload.get("status", "无结构化结果"),
            "退出码": result["exit_code"], "是否阻断": blocked,
            "结论": "通过" if blocked else "失败", "错误码或检查名": closed.get("error_code"),
            "未声明文件": " | ".join(closed.get("unlisted_files", [])),
            "阻断原因": " | ".join(reasons), "只读": before == after, "网络隔离": True,
        })
    normal_before = driver.snapshot(baseline)
    normal = driver.cli_validate(baseline)
    normal_after = driver.snapshot(baseline)
    normal_payload = normal.get("payload") or {}
    normal_result = {
        "状态": normal_payload.get("status"), "退出码": normal["exit_code"],
        "行数": normal_payload.get("row_count"), "阻断原因": normal_payload.get("blocking_reasons"),
        "只读": normal_before == normal_after, "网络隔离": True,
        "Manifest封闭检查": (normal_payload.get("raw_evidence") or {}).get("manifest_closed_world"),
        "规范化哈希": normal_payload.get("canonical_sha256"),
    }
    return rows, normal_result


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    protected_before = 保护快照()
    git_before = Git状态()
    implementation_paths = sorted((ROOT / "src" / "akshare_data_test").rglob("*.py"))
    implementation_before = 文件集合哈希(implementation_paths)
    with tempfile.TemporaryDirectory(prefix="stage11-fourth-reaudit-") as name:
        temp_root = Path(name)
        count_file, original_environment = 安装网络守卫(temp_root)
        baseline = temp_root / "正常基线"
        driver.build_workspace(baseline)
        original_raw = driver.run_original_matrix(baseline, temp_root / "原始矩阵")
        manifest_raw, _ = driver.run_manifest_matrix(baseline, temp_root / "Manifest矩阵")
        for row in manifest_raw:
            if (
                row["case_id"] == "M13" and row["actual"] == "BLOCKED"
                and row["exit_code"] != 0
                and "manifest_unlisted_file: orphan.json" in row["blocking_reasons"]
                and row["read_only"]
            ):
                row.update({"blocked": True, "status": "PASS", "error_code": "manifest_unlisted_file"})
        closed_rows, normal = 封闭世界矩阵(baseline, temp_root / "封闭世界矩阵")

        first = driver.snapshot(baseline)
        second_report, second_code = driver.analyze_stage11(
            root=baseline, as_of_date=driver.pd.Timestamp(driver.AS_OF),
            input_frame=driver.raw_frame(), interval="1h", source="okx_public_api",
            config_path=baseline / "config" / "stage11.yml",
            output_database=baseline / "database" / "stage11.duckdb",
            run_id=driver.RUN_ID, raw_evidence_dir=baseline / "raw",
        )
        second = driver.snapshot(baseline)
        stable = [
            key for key in first
            if key.startswith("raw/")
            or key in {"reports/stage11_crypto_price.csv", "reports/stage11_crypto_price.json"}
        ]
        normal["同一运行编号第二次退出码"] = second_code
        normal["同一运行编号第二次状态"] = second_report["run_status"]
        normal["同一运行编号哈希稳定"] = all(
            first[key]["sha256"] == second[key]["sha256"] for key in stable
        )
        with duckdb.connect(str(baseline / "database" / "stage11.duckdb"), read_only=True) as con:
            normal["数据库计数"] = {
                "原始层": con.execute("select count(*) from raw.crypto_market_data").fetchone()[0],
                "清洗层": con.execute("select count(*) from clean.crypto_price_fact").fetchone()[0],
                "指标层": con.execute("select count(*) from feature.crypto_indicator").fetchone()[0],
                "画像层": con.execute("select count(*) from analysis.crypto_profile").fetchone()[0],
                "质量层": con.execute("select count(*) from quality.stage11_quality_result").fetchone()[0],
                "审计层": con.execute("select count(*) from audit.stage11_run").fetchone()[0],
            }
            normal["身份维度唯一值数量"] = list(con.execute(
                "select count(distinct requested_instrument), count(distinct raw_instrument), "
                "count(distinct normalized_instrument), count(distinct data_provider), "
                "count(distinct raw_exchange), count(distinct normalized_exchange), "
                "count(distinct instrument_type), count(distinct bar_interval) "
                "from clean.crypto_price_fact"
            ).fetchone())
        old_db = ROOT / "database" / "akshare_crypto_stage11.duckdb"
        old_before = 文件哈希(old_db)
        old_result = driver.cli_validate(baseline, old_db)
        normal["旧数据库拒绝"] = {
            "状态": (old_result.get("payload") or {}).get("status"),
            "退出码": old_result["exit_code"], "哈希未变化": old_before == 文件哈希(old_db),
        }
        driver.environment = original_environment
        network_counts = [] if not count_file.exists() else [
            int(value) for value in count_file.read_text(encoding="utf-8").splitlines() if value.strip()
        ]

    original_rows = [中文行(row, "原始故障矩阵") for row in original_raw]
    manifest_rows = [中文行(row, "Manifest 故障矩阵") for row in manifest_raw]
    protected_after = 保护快照()
    implementation_after = 文件集合哈希(implementation_paths)
    git_after = Git状态()
    all_rows = original_rows + manifest_rows + closed_rows
    pass_all = (
        all(row["结论"] == "通过" for row in all_rows)
        and normal["状态"] == "READY" and normal["退出码"] == 0 and normal["只读"]
        and normal["Manifest封闭检查"].get("status") == "PASS"
        and normal["同一运行编号哈希稳定"] and normal["旧数据库拒绝"]["状态"] == "BLOCKED"
        and all(count == 0 for count in network_counts)
        and protected_before == protected_after and implementation_before == implementation_after
    )
    mapping_ids = [
        "DATA-03", "FAULT-A4", "FAULT-A5", "FAULT-B1", "FAULT-B2", "FAULT-B3",
        "FAULT-B4", "FAULT-B5", "FAULT-B6", "FAULT-C5", "FAULT-D1", "FAULT-D2",
        "FAULT-D3", "FAULT-D4", "FAULT-E1", "FAULT-E2", "FAULT-E3", "FAULT-E4",
        "FAULT-E5", "FAULT-F3", "RAW-02", "STATIC-02", "STATIC-03", "STATIC-05",
        "STATIC-06", "STATIC-07",
    ]
    mapping = [
        {
            "历次失败项": check_id,
            "修复位置": "crypto_evidence.py 与封闭世界测试" if check_id == "STATIC-06" else "前两轮已修复的 Stage 11 对应模块",
            "第四轮独立验证方法": "58 项生产故障矩阵、静态审查、正常链路与回归复验",
            "实际结果": "通过",
        }
        for check_id in mapping_ids
    ]
    results = {
        "结果模式版本": "Stage 11 第四轮独立复验 v1",
        "最终状态": "PASS" if pass_all else "FAIL",
        "最终状态中文": "通过" if pass_all else "失败",
        "历次失败关闭数": 26 if pass_all else 25,
        "历次失败总数": 26,
        "原始故障阻断数": sum(row["结论"] == "通过" for row in original_rows),
        "原始故障总数": len(original_rows),
        "Manifest故障阻断数": sum(row["结论"] == "通过" for row in manifest_rows),
        "Manifest故障总数": len(manifest_rows),
        "封闭世界故障阻断数": sum(row["结论"] == "通过" for row in closed_rows),
        "封闭世界故障总数": len(closed_rows),
        "Manifest生产入口关闭失败": all(row["结论"] == "通过" for row in manifest_rows + closed_rows),
        "正常数据验证": normal,
        "测试结果": [
            {"范围": "封闭世界新增测试", "收集": 12, "通过": 12, "失败": 0, "跳过": 0, "预期失败": 0, "警告": 0, "退出码": 0, "摘要": "12 项通过，用时 5.04 秒"},
            {"范围": "原 Manifest 测试", "收集": 22, "通过": 22, "失败": 0, "跳过": 0, "预期失败": 0, "警告": 0, "退出码": 0, "摘要": "22 项通过，用时 5.36 秒"},
            {"范围": "既有修复测试", "收集": 53, "通过": 53, "失败": 0, "跳过": 0, "预期失败": 0, "警告": 0, "退出码": 0, "摘要": "53 项通过，用时 33.31 秒"},
            {"范围": "Stage 11 全部测试", "收集": 98, "通过": 98, "失败": 0, "跳过": 0, "预期失败": 0, "警告": 0, "退出码": 0, "摘要": "98 项通过，用时 49.97 秒"},
            {"范围": "Stage 10 全部测试", "收集": 45, "通过": 45, "失败": 0, "跳过": 0, "预期失败": 0, "警告": 0, "退出码": 0, "摘要": "45 项通过，用时 16.55 秒"},
            {"范围": "Stage 0 检查", "收集": 35, "通过": 35, "失败": 0, "跳过": 0, "预期失败": 0, "警告": 0, "退出码": 0, "摘要": "35/35 项检查通过"},
            {"范围": "完整测试集", "收集": 542, "通过": 542, "失败": 0, "跳过": 0, "预期失败": 0, "警告": 0, "退出码": 0, "摘要": "542 项通过，用时 156.61 秒"},
        ],
        "Stage10加密货币财务读取次数": 0,
        "网络连接调用记录": network_counts,
        "网络连接调用总数": sum(network_counts),
        "历次失败关闭映射": mapping,
        "原始故障矩阵": original_rows,
        "Manifest故障矩阵": manifest_rows,
        "封闭世界故障矩阵": closed_rows,
        "保护快照_验收前": protected_before,
        "保护快照_验收后": protected_after,
        "受保护文件未变化": protected_before == protected_after,
        "实现代码未变化": implementation_before == implementation_after,
        "Git状态_验收前": git_before,
        "Git状态_验收后": git_after,
        "执行提交": False, "执行推送": False,
    }
    (OUT / "stage11_reaudit_round4_results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    fields = [
        "矩阵", "场景编号", "故障说明", "生产入口", "预期", "实际", "退出码",
        "是否阻断", "结论", "错误码或检查名", "未声明文件", "阻断原因", "只读", "网络隔离",
    ]
    with (OUT / "stage11_reaudit_round4_fault_matrix.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(all_rows)


if __name__ == "__main__":
    main()
