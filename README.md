# data-pipeline-clean

> AI 训练数据标准化流水线 — CSV 转换 → Agent 交互记录 → 一致性校验

---

## 项目背景

本项目的目标是构建一条**可复现、可审计的 AI 训练数据采集与处理流水线**，覆盖从原始数据清洗到 AI 编程助手交互日志标准化的完整链路。

核心场景对齐 **AI 数据训练师**岗位需求：
- 使用 AI 编程 Agent（模拟 Claude Code / CLINE 风格）执行真实开发任务
- 完整记录从需求分析、代码编辑、错误修复到测试验证的全流程交互轨迹
- 每条输出包含唯一标识符、任务类型、环境快照、Git 上下文（Unified Diff）和交互步骤
- 内置一致性校验：验证 `initial_state + patch == final_state`

---

## 目录结构

```
data-pipeline-clean/
│
├── pipeline/                      # 核心转换管道
│   ├── __init__.py
│   └── converter.py               # CSV → JSONL 转换器
│       ├── CSVToJSONLConverter    # 链式调用类（load → fill → select → export）
│       └── quick_convert()        # 一键转换快捷函数
│
├── agent_recorder/                # AI 交互记录器
│   ├── __init__.py
│   ├── recorder.py                # 自动追踪 Agent 交互全流程
│   │   ├── InteractionRecorder    # 记录器（环境快照 + Git状态 + 步骤追踪）
│   │   └── ConsistencyValidator   # 一致性校验器（SHA256 + difflib）
│   └── tasks.py                   # 预置任务模板（bug_fix / feature_dev）
│
├── scripts/                       # 一键运行脚本
│   └── run_agent_demo.py          # 全流程演示（3 步，自动执行）
│
├── tasks/                         # Agent 可执行的任务目录（运行时生成）
│
├── examples/                      # 示例数据
│   └── sample_orders.csv          # 电商订单示例（100行，含缺失值）
│
├── output/                        # 运行产出（gitignore 忽略）
│   ├── orders.jsonl               # CSV 转换结果
│   ├── agent_records.jsonl        # Agent 交互轨迹
│   └── quality_report.json        # 一致性校验报告
│
├── Dockerfile                     # 容器化可复现环境
├── docker-compose.yml             # 一键容器编排
├── requirements.txt               # Python 依赖
├── .gitignore
└── README.md
```

---

## 快速开始

### 本地运行

```bash
# 安装依赖
pip install pandas numpy pyyaml pydantic

# 运行全流程演示（3 步自动执行）
python scripts/run_agent_demo.py
```

### Docker 运行

```bash
docker compose up
```

---

## 全流程输出示例

一次运行产生三个文件：

### 1. `output/orders.jsonl` — CSV 数据转换结果

```jsonl
{"#metadata": {"converted_at": "2026-06-02T13:38:19", "source_file": "sample_orders.csv", "row_count": 100}}
{"record_id": "REC-4729DA36", "data": {"order_id": "ORD-0001", "product": "Keyboard", "quantity": 2, "price": 1995.5}}
```

### 2. `output/agent_records.jsonl` — Agent 交互轨迹

每条记录包含：
- `record_id` — 全局唯一标识符
- `task_id` / `task_type` — 任务编号与类型（bug_fix / feature_dev）
- `env_info` — 操作系统、Python 版本、依赖版本
- `git_context` — 初始 commit + Unified Diff
- `file_snapshots` — 初始文件内容 + 最终文件内容 + SHA256 哈希
- `interaction_trajectory` — 完整的交互步骤（思考→读文件→编辑→运行→验证）

### 3. `output/quality_report.json` — 质量校验报告

```json
{
  "status": "passed",
  "validation": {
    "valid": true,
    "reason": "✓ 一致性通过: initial + patch == final（SHA256 + difflib 双重验证）"
  }
}
```

---

## 架构设计

```
┌──────────────────────────────────────────────────┐
│              pipeline/converter.py               │
│  CSV → 缺失值填充 → 列筛选 → UUID注入 → JSONL   │
└──────────────────────┬───────────────────────────┘
                       ↓
┌──────────────────────────────────────────────────┐
│           agent_recorder/recorder.py              │
│                                                    │
│  1. snapshot_initial_state()                      │
│     ├─ 记录 Git commit hash                       │
│     ├─ 保存初始文件内容 + SHA256                   │
│     └─ 捕获环境快照                                │
│                                                    │
│  2. record() / record_run()                       │
│     ├─ 记录 "think" / "read_file" / "edit_file"   │
│     ├─ 记录 "run" / "verify" / "fix_error"        │
│     └─ 每一步带时间戳                              │
│                                                    │
│  3. finalize(task_type)                           │
│     ├─ 生成 Unified Diff                          │
│     └─ 输出完整 JSONL（含交互轨迹 + 文件快照）      │
│                                                    │
│  4. ConsistencyValidator.validate_from_record()   │
│     ├─ SHA256 哈希校验                            │
│     ├─ difflib 验证 patch 正确性                   │
│     └─ 不依赖 git apply（避免 Windows CRLF 问题）  │
└──────────────────────┬───────────────────────────┘
                       ↓
┌──────────────────────────────────────────────────┐
│              output/*.jsonl + quality_report      │
│  标准化 AI 训练数据 + 质量审计报告                 │
└──────────────────────────────────────────────────┘
```

---

## 关键技术决策

### 为什么不用现成转换库而自己写？
需要精确控制 JSONL 输出格式，确保每条记录包含完整的可复现闭环（Git 上下文 + 环境快照 + 交互轨迹），现成库无法满足。

### 一致性校验有什么价值？
AI 训练数据的质量生命线。如果一条 patch 不能干净地回放，说明采集的交互数据有损，训练出来的模型会学到错误的模式。

### Docker 的作用？
AI 训练数据采集最怕环境漂移——同一段代码在不同机器上行为不同。Docker 保证采集环境和回放环境完全一致。

---

## 预置任务

| 任务 ID | 类型 | 描述 |
|---------|------|------|
| TASK-001 | bug_fix | 修复 CSV 读取器空行崩溃（IndexError） |
| TASK-002 | feature_dev | 为 DataProcessor 实现 to_json 导出方法 |

---

## 岗位匹配

本项目核心技术点直接对应用于岗位的技能需求：

| 岗位要求 | 本项目对应 |
|----------|-----------|
| AI 训练数据构建 / JSONL 处理 | ✅ 标准化 JSONL 输出，含 metadata + 数据行 |
| 数据清洗与标准化 | ✅ CSV → JSONL 转换，缺失值处理，列筛选 |
| Docker 可复现环境 | ✅ Dockerfile + docker-compose.yml |
| Git / Unified Diff | ✅ git_context 包含完整 diff + commit 追溯 |
| 一致性校验 | ✅ initial + patch == final 闭环验证 |
| 技术文档撰写 | ✅ 本 README + 代码注释 + 质量报告 |

---

## License

MIT
