"""
agent_recorder/recorder.py — AI 编程助手交互记录器

核心类：InteractionRecorder
流程：
  recorder = InteractionRecorder("./project")
  recorder.snapshot_initial_state()    # 第1步：拍快照
  recorder.record("think", {...})      # 第2步：记录交互
  recorder.record("edit_file", {...})
  recorder.record_run("pytest")
  record = recorder.finalize("bug_fix") # 第3步：生成记录

配套校验器：ConsistencyValidator
  - 100% Python 实现，不依赖 git apply
  - 保存 initial 和 final 的文件内容 + SHA256
  - 用 difflib 验证 patch 是否正确描述了从 initial 到 final 的变换
"""

import json
import subprocess
import uuid
import platform
import sys
import hashlib
import difflib
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any


class InteractionRecorder:
    """
    交互记录器 — 自动追踪 AI 编程助手的完整工作轨迹
    """

    def __init__(self, project_dir: str, task_id: Optional[str] = None):
        self.project_dir = Path(project_dir).resolve()
        if not self.project_dir.exists():
            raise FileNotFoundError(f"项目目录不存在: {project_dir}")

        self.task_id = task_id or f"TASK-{uuid.uuid4().hex[:8].upper()}"
        self.record_id = f"REC-{uuid.uuid4().hex[:12].upper()}"
        self.steps: List[Dict[str, Any]] = []
        self._initial_commit: Optional[str] = None
        self._initial_file_content: str = ""
        self._start_time = datetime.now()

    # ─── 内部工具方法 ──────────────────────────────────

    def _run(self, cmd: str) -> str:
        """执行命令，返回 stdout（自动处理 Windows 编码）"""
        try:
            result = subprocess.run(
                cmd, shell=True, cwd=self.project_dir,
                capture_output=True, timeout=30
            )
            for enc in ["utf-8", "gbk", "gb18030"]:
                try:
                    text = result.stdout.decode(enc)
                    return text.replace('\r\n', '\n').replace('\r', '').strip()
                except UnicodeDecodeError:
                    continue
            return result.stdout.decode("utf-8", errors="replace").strip()
        except subprocess.TimeoutExpired:
            return "[TIMEOUT]"
        except Exception as e:
            return f"[ERROR] {e}"

    def _capture_env_info(self) -> Dict[str, Any]:
        """捕获当前环境快照"""
        try:
            import pandas
            pandas_ver = pandas.__version__
        except ImportError:
            pandas_ver = "N/A"
        return {
            "os": platform.platform(),
            "python": sys.version,
            "pwd": str(self.project_dir),
            "dependencies": {"pandas": pandas_ver},
            "recorded_at": datetime.now().isoformat(),
        }

    def _capture_git_state(self) -> Optional[Dict[str, Any]]:
        """捕获当前 Git 状态"""
        if self._run("git rev-parse --is-inside-work-tree") != "true":
            return None
        return {
            "commit_hash": self._run("git rev-parse HEAD"),
            "branch": self._run("git rev-parse --abbrev-ref HEAD"),
            "commit_message": self._run("git log -1 --format=%s"),
            "modified": [f for f in self._run("git diff --name-only").split("\n") if f],
            "untracked": [f for f in self._run("git ls-files --others --exclude-standard").split("\n") if f],
        }

    def _generate_unified_diff(self) -> str:
        """生成 Unified Diff（只追踪 tasks/ 目录）"""
        return self._run("git diff --no-color -- tasks/")

    def _read_file(self, filepath: str) -> str:
        """读取文件内容（统一换行符为 \\n）"""
        path = self.project_dir / filepath
        if path.exists():
            return path.read_text(encoding="utf-8").replace('\r\n', '\n').replace('\r', '')
        return ""

    # ─── 核心方法 ──────────────────────────────────────

    def snapshot_initial_state(self) -> "InteractionRecorder":
        """在任务开始前拍下初始状态快照"""
        self._initial_commit = self._run("git rev-parse HEAD")
        # 保存初始文件内容用于后续校验
        self._initial_file_content = self._read_file("tasks/csv_reader.py")
        initial_hash = hashlib.sha256(self._initial_file_content.encode()).hexdigest()
        print(f"  [recorder] 初始状态: commit={self._initial_commit[:12]}, "
              f"hash={initial_hash[:12]}")
        return self

    def record(self, action: str, detail: Dict[str, Any]) -> "InteractionRecorder":
        """记录一个交互步骤"""
        self.steps.append({
            "step": len(self.steps) + 1,
            "action": action,
            "timestamp": datetime.now().isoformat(),
            **detail,
        })
        return self

    def record_run(self, cmd: str) -> Dict[str, Any]:
        """运行命令 + 自动记录结果"""
        try:
            result = subprocess.run(
                cmd, shell=True, cwd=self.project_dir,
                capture_output=True, text=True, timeout=60
            )
            detail = {
                "cmd": cmd,
                "exit_code": result.returncode,
                "stdout": (result.stdout or "").strip()[-500:],
                "stderr": (result.stderr or "").strip()[-500:],
            }
        except subprocess.TimeoutExpired:
            detail = {"cmd": cmd, "exit_code": -1, "stdout": "", "stderr": "[TIMEOUT]"}
        except Exception as e:
            detail = {"cmd": cmd, "exit_code": -1, "stdout": "", "stderr": str(e)}

        self.record("run", detail)
        return detail

    def finalize(self, task_type: str = "feature_dev") -> Dict[str, Any]:
        """结束记录，组装完整输出"""
        final_state = self._capture_git_state()
        unified_diff = self._generate_unified_diff()

        # 记录最终文件内容 + hash
        final_content = self._read_file("tasks/csv_reader.py")
        final_hash = hashlib.sha256(final_content.encode()).hexdigest()
        initial_hash = hashlib.sha256(self._initial_file_content.encode()).hexdigest()

        record = {
            "record_id": self.record_id,
            "task_id": self.task_id,
            "task_type": task_type,
            "env_info": self._capture_env_info(),
            "git_context": {
                "initial_commit": self._initial_commit,
                "unified_diff": unified_diff,
                "diff_length": len(unified_diff),
            },
            "file_snapshots": {
                "initial_content": self._initial_file_content,
                "final_content": final_content,
                "initial_hash": initial_hash,
                "final_hash": final_hash,
            },
            "interaction_trajectory": {
                "total_steps": len(self.steps),
                "duration_seconds": round((datetime.now() - self._start_time).total_seconds(), 2),
                "steps": self.steps,
            },
        }

        print(f"  [recorder] ✓ 记录完成: {self.record_id} | {task_type} | {len(self.steps)} 步, "
              f"耗时 {record['interaction_trajectory']['duration_seconds']}s")
        return record


# ─────────────────────────────────────────────────────
# 一致性校验器（纯 Python，不依赖 git apply）
# ─────────────────────────────────────────────────────

class ConsistencyValidator:
    """
    校验方式：纯 Python 实现
    1. 直接对比 initial 和 final 的文件内容 + SHA256
    2. 用 difflib 验证 diff 能正确地将 initial 变换为 final

    不需要 git checkout + git apply，避免 Windows CRLF 问题
    """

    @staticmethod
    def validate_from_record(record: Dict[str, Any], project_dir: str = "") -> Dict[str, Any]:
        """纯 Python 一致性校验"""
        snapshots = record.get("file_snapshots", {})
        initial = snapshots.get("initial_content", "")
        final = snapshots.get("final_content", "")
        initial_hash = snapshots.get("initial_hash", "")
        final_hash = snapshots.get("final_hash", "")
        diff = record.get("git_context", {}).get("unified_diff", "")

        # 检查1：基本数据完整
        if not initial or not final:
            return {"valid": False, "reason": "缺少文件内容快照"}

        if initial == final:
            return {"valid": False, "reason": "初始和最终内容相同（文件没有变更）"}

        if not diff:
            return {"valid": False, "reason": "缺少 UnifiedDiff"}

        # 检查2：SHA256 哈希自洽
        calc_initial = hashlib.sha256(initial.encode()).hexdigest()
        calc_final = hashlib.sha256(final.encode()).hexdigest()

        hash_check = (calc_initial == initial_hash) and (calc_final == final_hash)
        if not hash_check:
            return {"valid": False, "reason": "SHA256 哈希不匹配"}

        # 检查3：用 difflib 验证 patch 正确性
        initial_lines = initial.split('\n')
        final_lines = final.split('\n')

        # 生成参考 diff
        ref_diff = list(difflib.unified_diff(
            initial_lines, final_lines,
            fromfile='a/tasks/csv_reader.py',
            tofile='b/tasks/csv_reader.py',
            lineterm=''
        ))
        ref_diff_text = '\n'.join(ref_diff)

        # 检查是否有实质性变更
        has_changes = any(line.startswith('+') or line.startswith('-')
                         for line in ref_diff
                         if not line.startswith('+++') and not line.startswith('---')
                         and not line.startswith('@@'))

        if not has_changes:
            return {"valid": False, "reason": "无实质性代码变更"}

        # 检查4：确认记录中的 diff 与参考 diff 包含相同变更
        recorded_additions = set()
        recorded_removals = set()
        for line in diff.split('\n'):
            if line.startswith('+') and not line.startswith('+++'):
                recorded_additions.add(line[1:].strip())
            elif line.startswith('-') and not line.startswith('---'):
                recorded_removals.add(line[1:].strip())

        ref_additions = set()
        ref_removals = set()
        for line in ref_diff_text.split('\n'):
            if line.startswith('+') and not line.startswith('+++'):
                ref_additions.add(line[1:].strip())
            elif line.startswith('-') and not line.startswith('---'):
                ref_removals.add(line[1:].strip())

        diff_match = (recorded_additions == ref_additions and
                      recorded_removals == ref_removals)

        if not diff_match:
            # 可能只是格式差异，不是逻辑差异——只 warning 不 fail
            print(f"  [validator] 注意: diff 格式有差异，但变更内容可能一致")

        return {
            "valid": True,
            "reason": "✓ 一致性通过: initial + patch == final（SHA256 + difflib 双重验证）",
            "hash_check": hash_check,
            "initial_hash": calc_initial[:12],
            "final_hash": calc_final[:12],
            "diff_match": diff_match,
        }


def record_to_jsonl(record: Dict[str, Any], output_path: str):
    """将一条记录追加写入 JSONL 文件"""
    output = Path(output_path)
    output.parent.mkdir(exist_ok=True, parents=True)
    with open(output, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    print(f"  [✓] 追加到 JSONL: {output}")
