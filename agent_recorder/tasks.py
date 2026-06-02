"""
agent_recorder/tasks.py — 预置的 Agent 任务模板

每个任务包含：
  - task_id / task_type: 标识信息
  - title / description: 需求文档（模拟给 AI 的任务描述）
  - initial_code: 初始代码（含 bug 或 stub）
  - expected_code: 正确的代码（用于闭环验证）
  - verification_cmd: 验证命令
"""

from dataclasses import dataclass


@dataclass
class AgentTask:
    """一个可被 AI Agent 执行的任务"""
    task_id: str
    task_type: str         # "bug_fix" | "feature_dev"
    title: str
    description: str
    initial_code: str
    expected_code: str
    verification_cmd: str  # 验证命令，返回码 0 表示通过


# ─── 任务1: Bug修复 — CSV读取器空行崩溃 ────────────────
TASK_FIX_CSV_READER = AgentTask(
    task_id="TASK-001",
    task_type="bug_fix",
    title="修复 CSV 读取器空行崩溃",
    description="""
## Bug 描述
csv_reader.py 在读取包含空行的 CSV 文件时抛出 IndexError。
原因：空行经过 strip 后为空字符串，split(',') 返回 ['']，
访问 parts[1]、parts[2] 时越界。

## 复现步骤
1. 创建包含空行的 CSV: "a,b,c\\n1,2,3\\n\\n4,5,6"
2. 调用 read_csv_lines() → 报错 IndexError

## 期望行为
跳过空行，正常读取非空行数据。
""",
    initial_code="""def read_csv_lines(filepath):
    result = []
    with open(filepath, 'r') as f:
        for line in f:
            parts = line.strip().split(',')
            result.append({
                'col1': parts[0],
                'col2': parts[1],
                'col3': parts[2],
            })
    return result
""",
    expected_code="""def read_csv_lines(filepath):
    result = []
    with open(filepath, 'r') as f:
        for line in f:
            stripped = line.strip()
            if not stripped:
                continue
            parts = stripped.split(',')
            result.append({
                'col1': parts[0],
                'col2': parts[1],
                'col3': parts[2],
            })
    return result
""",
    verification_cmd="python -c \"from csv_reader import read_csv_lines; d = read_csv_lines('test.csv'); assert len(d) == 2, f'Expected 2 rows, got {len(d)}'\"",
)


# ─── 任务2: 功能开发 — 添加 JSON 导出 ──────────────────
TASK_ADD_JSON_EXPORT = AgentTask(
    task_id="TASK-002",
    task_type="feature_dev",
    title="为 DataProcessor 添加 to_json 方法",
    description="""
## 需求
DataProcessor 类的 to_json() 目前只有占位符，请完整实现。

## 要求
1. 支持 indent 参数控制缩进
2. 支持 ensure_ascii 控制中文是否转义
3. overwrite=True 时直接覆盖；False 且文件已存在则报错
4. 自动创建父目录

## 使用示例
p = DataProcessor({"name": "张三"})
path = p.to_json("output/test.json", indent=2, overwrite=True)
""",
    initial_code="""import json

class DataProcessor:
    def __init__(self, data):
        self.data = data

    def to_json(self, filepath, indent=2, overwrite=False):
        # TODO: implement
        raise NotImplementedError
""",
    expected_code="""import json
from pathlib import Path

class DataProcessor:
    def __init__(self, data):
        self.data = data

    def to_json(self, filepath, indent=2, overwrite=False):
        path = Path(filepath)
        if path.exists() and not overwrite:
            raise FileExistsError(f"{filepath} 已存在，请设置 overwrite=True")
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(self.data, f, ensure_ascii=False, indent=indent)
        return str(path)
""",
    verification_cmd="python -c \"from processor import DataProcessor; p = DataProcessor({'a': 1}); print(p.to_json('test_out.json', overwrite=True))\"",
)