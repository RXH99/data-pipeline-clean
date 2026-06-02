"""
scripts/run_agent_demo.py — 全流程演示

一条命令跑完：
  python scripts/run_agent_demo.py

执行步骤：
  Step 1: CSV → JSONL 基础数据转换（输出 orders.jsonl）
  Step 2: 模拟 AI Agent 执行 bug 修复，记录交互轨迹（输出 agent_records.jsonl）
  Step 3: 一致性校验 + 质量报告（输出 quality_report.json）
"""

import sys
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline.converter import quick_convert
from agent_recorder.recorder import InteractionRecorder, ConsistencyValidator, record_to_jsonl
from agent_recorder.tasks import TASK_FIX_CSV_READER


# ═══════════════════════════════════════════════════════
# Step 1
# ═══════════════════════════════════════════════════════

def step1_csv_to_jsonl():
    print("\n" + "=" * 55)
    print("  Step 1: CSV → JSONL 数据转换")
    print("=" * 55)

    output = quick_convert(
        str(ROOT / "examples" / "sample_orders.csv"),
        str(ROOT / "output" / "orders.jsonl"),
        fill_strategy={"customer_rating": "mean"},
        keep_cols=["order_id", "product", "quantity", "price", "customer_rating"],
    )

    print("\n  JSONL 预览（前 3 行）:")
    with open(output, "r", encoding="utf-8") as f:
        for i, line in enumerate(f):
            if i >= 3:
                break
            parsed = json.loads(line)
            preview = json.dumps(parsed, ensure_ascii=False)
            print(f"    第{i+1}行: {preview[:120]}...")
    return output


# ═══════════════════════════════════════════════════════
# Step 2
# ═══════════════════════════════════════════════════════

def step2_agent_recording():
    print("\n" + "=" * 55)
    print("  Step 2: AI Agent 交互记录（模拟）")
    print("=" * 55)

    tasks_dir = ROOT / "tasks"
    task = TASK_FIX_CSV_READER

    # 清理旧文件
    for f in tasks_dir.glob("*"):
        if f.is_file():
            f.unlink()

    # 写入初始代码（强制 LF 换行）
    csv_file = tasks_dir / "csv_reader.py"
    csv_file.write_text(task.initial_code, encoding="utf-8", newline="\n")
    test_csv = tasks_dir / "test.csv"
    test_csv.write_text("a,b,c\n1,2,3\n\n4,5,6\n", encoding="utf-8", newline="\n")

    print(f"\n  [任务] {task.task_id}: {task.title}")

    # 提交到 Git 作为"初始状态"
    subprocess.run("git add tasks/", shell=True, cwd=ROOT, capture_output=True)
    subprocess.run('git commit -m "tmp: init task"', shell=True, cwd=ROOT, capture_output=True)

    # 初始化记录器
    recorder = InteractionRecorder(str(ROOT), task_id=task.task_id)
    recorder.snapshot_initial_state()

    # 模拟 AI 交互
    recorder.record("think", {"thought": "检查 csv_reader.py，发现空行时 IndexError"})
    recorder.record("read_file", {"file": "tasks/csv_reader.py", "content_preview": task.initial_code[:120]})

    # 写入修复代码
    csv_file.write_text(task.expected_code, encoding="utf-8", newline="\n")
    recorder.record("edit_file", {"file": "tasks/csv_reader.py", "change": "添加空行跳过逻辑"})

    # 验证
    verify = recorder.record_run(
        "cd tasks && python -c \"from csv_reader import read_csv_lines; "
        "data = read_csv_lines('test.csv'); print(f'OK: {len(data)} 行')\""
    )
    recorder.record("verify" if verify.get("exit_code") == 0 else "fix_error",
                    {"stdout": verify.get("stdout", ""), "stderr": verify.get("stderr", "")})

    # 结束
    record = recorder.finalize(task_type=task.task_type)
    jsonl_path = ROOT / "output" / "agent_records.jsonl"
    record_to_jsonl(record, str(jsonl_path))
    return record, jsonl_path


# ═══════════════════════════════════════════════════════
# Step 3
# ═══════════════════════════════════════════════════════

def step3_validate(record, jsonl_path):
    print("\n" + "=" * 55)
    print("  Step 3: 一致性校验（纯 Python）")
    print("=" * 55)

    # 执行校验（纯 Python，无需 git checkout + git apply）
    result = ConsistencyValidator.validate_from_record(record)
    status = "✓ 通过" if result["valid"] else "✗ 失败"
    print(f"  {status}")
    print(f"  原因: {result['reason']}")

    # 报告
    print("\n" + "=" * 55)
    print("  最终产出报告")
    print("=" * 55)

    steps = len(record["interaction_trajectory"]["steps"])
    has_diff = len(record["git_context"]["unified_diff"]) > 0

    print(f"  JSONL 文件:  {jsonl_path}")
    print(f"  记录ID:       {record['record_id']}")
    print(f"  任务类型:     {record['task_type']}")
    print(f"  交互步数:     {steps}")
    print(f"  有 UnifiedDiff: {'✓' if has_diff else '✗'}")
    print(f"  一致性校验:   {'✓' if result['valid'] else '✗'}")
    print(f"  JSONL 大小:   {jsonl_path.stat().st_size / 1024:.1f} KB")

    report = {
        "status": "passed" if result["valid"] else "failed",
        "record_id": record["record_id"],
        "validation": result,
        "summary": {"task_type": record["task_type"], "steps": steps,
                     "has_diff": has_diff, "has_env_info": True,
                     "total_duration_sec": record["interaction_trajectory"]["duration_seconds"]},
    }
    report_path = ROOT / "output" / "quality_report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"  质量报告:    {report_path}")
    return result["valid"]


# ═══════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════

if __name__ == "__main__":
    from datetime import datetime
    print("\n" + "🚀" * 14)
    print("  data-pipeline-clean 全流程演示")
    print(f"  开始时间: {datetime.now().isoformat()}")
    print("🚀" * 14)

    step1_csv_to_jsonl()
    record, jsonl_path = step2_agent_recording()
    passed = step3_validate(record, jsonl_path)

    icon = "🎉" if passed else "⚠️"
    print("\n" + "=" * 55)
    print(f"  {icon} 全流程{'已完成' if passed else '已完成（有失败项）'}")
    print("=" * 55)
    print(f"  产出文件:")
    print(f"    • output/orders.jsonl        — CSV 转换结果")
    print(f"    • output/agent_records.jsonl  — Agent 交互记录")
    print(f"    • output/quality_report.json  — 质量校验报告")
    print()
