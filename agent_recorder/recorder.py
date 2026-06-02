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

输出 JSONL 包含：
  - record_id: 唯一标识符
  - task_id / task_type: 任务信息
  - env_info: 操作系统 / Python版本 / 依赖版本
  - git_context: initial_state + UnifiedDiff + final_state
  - interaction_trajectory: 完整交互步骤

配套校验器：ConsistencyValidator
  - 验证 initial_state + patch == final_state
"""

import json
import os
import subprocess
import uuid
import platform
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any


class InteractionRecorder:
    """
    交互记录器 — 自动追踪 AI 编程助手的完整工作轨迹

    关键设计：
    - 模仿 Claude Code 的交互日志格式，逐步骤记录
    - 每条记录包含完整的可复现信息
    - 与环境无关：换台机器只要 Git 历史在就能复现
    """

    def __init__(self, project_dir: str, task_id: Optional[str] = None):
        """
        初始化记录器
        - project_dir: 要记录的项目目录（需要是 Git 仓库）
        - task_id: 可选的任务编号，不传会自动生成
        """
        self.project_dir = Path(project_dir).resolve()
        if not self.project_dir.exists():
            raise FileNotFoundError(f"项目目录不存在: {project_dir}")

        self.task_id = task_id or f"TASK-{uuid.uuid4().hex[:8].upper()}"
        self.record_id = f"REC-{uuid.uuid4().hex[:12].upper()}"
        self.steps: List[Dict[str, Any]] = []
        self._initial_commit: Optional[str] = None
        self._start_time = datetime.now()

    # ──────────────────────────────────────────────
    # 内部方法：捕获环境 & Git 信息
    # ──────────────────────────────────────────────

    def _capture_env_info(self) -> Dict[str, Any]:
        """捕获当前环境的快照（操作系统、Python、关键依赖版本）"""
        # 尝试获取 pandas 版本，不强制依赖
        try:
            import pandas
            pandas_ver = pandas.__version__
        except ImportError:
            pandas_ver = "N/A"

        return {
            "os": platform.platform(),                # 如 Windows-10-10.0.19041-SP0
            "python": sys.version,                     # 如 3.9.13
            "pwd": str(self.project_dir),              # 项目绝对路径
            "dependencies": {"pandas": pandas_ver},
            "recorded_at": datetime.now().isoformat(), # 记录时间
        }

    def _run(self, cmd: str) -> str:
        """执行一条 shell 命令，返回 stdout——兼容中文 Windows 编码"""
        try:
            result = subprocess.run(
                cmd, shell=True, cwd=self.project_dir,
                capture_output=True, timeout=30   # 去掉 text=True，拿到 raw bytes
            )
            # 优先 utf-8 解码，失败时用系统编码（GBK）兜底
            for enc in ["utf-8", "gbk", "gb18030"]:
                try:
                    return result.stdout.decode(enc).strip()
                except UnicodeDecodeError:
                    continue
            return result.stdout.decode("utf-8", errors="replace").strip()
        except subprocess.TimeoutExpired:
            return "[TIMEOUT]"
        except Exception as e:
            return f"[ERROR] {e}"

    def _capture_git_state(self) -> Optional[Dict[str, Any]]:
        """
        捕获完整的 Git 状态
        包括当前 commit、分支、文件变更列表
        """
        # 检查是否是 Git 仓库
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
        """只生成 tasks/ 目录的 Unified Diff"""
        return self._run("git diff --no-color -- tasks/")

# ──────────────────────────────────────────────
    # 核心方法：初始化、记录步骤、结束输出
    # ──────────────────────────────────────────────

    def snapshot_initial_state(self) -> "InteractionRecorder":
        """
        【必须先调用】在任务开始前拍下初始状态快照

        原理：记录当前 commit hash 作为回滚锚点，
        后续一致性校验会用到这个点。
        """
        self._initial_commit = self._run("git rev-parse HEAD")
        print(f"  [recorder] 初始状态: commit={self._initial_commit[:12]}")
        return self

    def record(self, action: str, detail: Dict[str, Any]) -> "InteractionRecorder":
        """
        记录一个交互步骤

        参数:
          action: 动作类型 → "read_file" | "edit_file" | "run" | "fix_error" | "think" | "verify"
          detail: 动作详情（不同动作传不同字段）

        示例:
          record("think", {"thought": "检查到bug原因"})
          record("edit_file", {"file": "main.py", "change": "加了空行判断"})
          record_run("pytest")  ← 快捷方法
        """
        self.steps.append({
            "step": len(self.steps) + 1,
            "action": action,
            "timestamp": datetime.now().isoformat(),
            **detail,
        })
        return self

    def record_run(self, cmd: str) -> Dict[str, Any]:
        """
        快捷方法：运行一条命令 + 自动记录结果

        返回 detail 字典，包含 cmd / exit_code / stdout / stderr
        """
        try:
            result = subprocess.run(
                cmd, shell=True, cwd=self.project_dir,
                capture_output=True, text=True, timeout=60
            )
            detail = {
                "cmd": cmd,
                "exit_code": result.returncode,
                "stdout": result.stdout.strip()[-500:],    # 截断，避免单条记录太大
                "stderr": result.stderr.strip()[-500:],
            }
        except subprocess.TimeoutExpired:
            detail = {"cmd": cmd, "exit_code": -1, "stdout": "", "stderr": "[TIMEOUT]"}
        except Exception as e:
            detail = {"cmd": cmd, "exit_code": -1, "stdout": "", "stderr": str(e)}

        self.record("run", detail)
        return detail

    def finalize(self, task_type: str = "feature_dev") -> Dict[str, Any]:
        """
        结束记录，组装完整输出

        参数:
          task_type: "bug_fix" | "feature_dev" | "refactor"

        返回完整的记录字典，包含：
        - record_id / task_id / task_type（标识信息）
        - env_info（环境快照）
        - git_context（初始状态 + UnifiedDiff + 最终状态）
        - interaction_trajectory（完整交互步骤）
        """
        # 捕获当前（最终）状态
        final_state = self._capture_git_state()
        unified_diff = self._generate_unified_diff()

        record = {
            "record_id": self.record_id,
            "task_id": self.task_id,
            "task_type": task_type,
            "env_info": self._capture_env_info(),
            "git_context": {
                "initial_commit": self._initial_commit,
                "initial_state": final_state,          # 记录当前作为上下文锚点
                "final_state": final_state,
                "unified_diff": unified_diff,
                "diff_length": len(unified_diff),
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
# 一致性校验器
# ─────────────────────────────────────────────────────

class ConsistencyValidator:
    """
    校验核心逻辑：initial_state + patch == final_state

    原理：
    1. 用 git stash 暂存当前工作区
    2. git checkout 到初始 commit
    3. git apply patch
    4. 验证应用后工作区是否干净（说明 patch 一致）
    5. 恢复现场（回到原分支 + 恢复 stash）
    """

    @staticmethod
    def validate_from_record(record: Dict[str, Any], project_dir: str) -> Dict[str, Any]:
        git_ctx = record.get("git_context", {})
        initial_commit = git_ctx.get("initial_commit")
        diff = git_ctx.get("unified_diff", "")

        if not initial_commit or not diff:
            return {"valid": False, "reason": "缺少 initial_commit 或 unified_diff"}

        project = Path(project_dir)
        patch_file = project / f".tmp_{record['record_id']}.patch"
        # 用 UTF-8 无 BOM 写 patch，换行统一为 LF
        clean_diff = diff.replace('\r\n', '\n')
        with open(patch_file, 'w', encoding='utf-8', newline='\n') as f:
            f.write(clean_diff)

        # 暂存当前工作区
        stash_result = subprocess.run(
            "git stash push -m 'consistency_check'",
            shell=True, cwd=project_dir, capture_output=True, text=True
        )
        current_branch = subprocess.run(
            "git rev-parse --abbrev-ref HEAD",
            shell=True, cwd=project_dir, capture_output=True, text=True
        ).stdout.strip()

        try:
            # checkout 到初始 commit
            subprocess.run(
                f"git checkout {initial_commit}",
                shell=True, cwd=project_dir, capture_output=True, text=True, check=True
            )
            print(f"  [validator] checkout 到初始 commit: {initial_commit[:12]}")

            # 应用 patch
            apply_result = subprocess.run(
                f"git apply {patch_file}",
                shell=True, cwd=project_dir, capture_output=True, text=True
            )
            if apply_result.returncode != 0:
                return {"valid": False, "reason": f"Patch 应用失败: {apply_result.stderr}"}

            # 验证：apply 后应该没有未提交变更
            check_diff = subprocess.run(
                "git diff --stat",
                shell=True, cwd=project_dir, capture_output=True, text=True
            )
            is_clean = check_diff.stdout.strip() == ""

            return {
                "valid": is_clean,
                "reason": "✓ initial + patch == final" if is_clean else "Apply 后仍有差异",
            }

        finally:
            # 恢复现场：回到原来分支 + 恢复 stash + 删临时文件
            subprocess.run(f"git checkout {current_branch}", shell=True, cwd=project_dir,
                         capture_output=True, text=True)
            if stash_result.returncode == 0 and "No local changes" not in stash_result.stdout:
                subprocess.run("git stash pop", shell=True, cwd=project_dir,
                             capture_output=True, text=True)
            if patch_file.exists():
                patch_file.unlink()


# ─────────────────────────────────────────────────────
# 快捷工具函数
# ─────────────────────────────────────────────────────

def record_to_jsonl(record: Dict[str, Any], output_path: str):
    """将一条记录追加写入 JSONL 文件"""
    output = Path(output_path)
    output.parent.mkdir(exist_ok=True, parents=True)
    with open(output, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    print(f"  [✓] 追加到 JSONL: {output}")