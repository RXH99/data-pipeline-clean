"""
pipeline/converter.py — CSV → JSONL 转换器

核心类：CSVToJSONLConverter
流程：load() → [fill_missing()] → [select_columns()] → [add_record_id()] → export()

输出 JSONL 格式：
  第1行 → 元数据（以 #metadata 标记，包含行数、列数、转换时间）
  后面每行 → 一条记录（包含 record_id + data 字段）
"""

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any

import pandas as pd
import numpy as np


class CSVToJSONLConverter:
    """CSV → JSONL 转换器，支持清洗、筛选和元数据注入"""

    def __init__(self, input_path: str):
        self.input_path = Path(input_path)
        self.df: Optional[pd.DataFrame] = None
        self.metadata: Dict[str, Any] = {
            "converted_at": datetime.now().isoformat(),
            "source_file": self.input_path.name,
        }

    # ─── 第1步：加载数据 ────────────────────────────────
    def load(self, **kwargs) -> "CSVToJSONLConverter":
        """读取 CSV 文件"""
        self.df = pd.read_csv(self.input_path, **kwargs)
        self.metadata["row_count"] = len(self.df)
        self.metadata["column_count"] = len(self.df.columns)
        self.metadata["columns"] = list(self.df.columns)
        print(f"  [✓] 加载 {len(self.df)} 行, {len(self.df.columns)} 列")
        return self

    # ─── 第2步：填充缺失值（可选） ──────────────────────
    def fill_missing(self, strategy: dict) -> "CSVToJSONLConverter":
        """
        填充缺失值
        strategy = {"age": 0, "name": "unknown", "score": "mean"}
        支持: 固定值 / "mean" / "median" / "mode" / "drop"
        """
        before = self.df.isna().sum().sum()
        for col, method in strategy.items():
            if col not in self.df.columns:
                continue
            if method == "mean":
                self.df[col] = self.df[col].fillna(self.df[col].mean())
            elif method == "median":
                self.df[col] = self.df[col].fillna(self.df[col].median())
            elif method == "mode":
                mode_val = self.df[col].mode()
                self.df[col] = self.df[col].fillna(mode_val[0] if not mode_val.empty else 0)
            elif method == "drop":
                self.df = self.df.dropna(subset=[col])
            else:
                self.df[col] = self.df[col].fillna(method)
        after = self.df.isna().sum().sum()
        print(f"  [✓] 缺失值填充: {before} → {after}")
        return self

    # ─── 第3步：选列（可选） ────────────────────────────
    def select_columns(self, columns: List[str]) -> "CSVToJSONLConverter":
        """只保留指定的列"""
        valid = [c for c in columns if c in self.df.columns]
        self.df = self.df[valid]
        print(f"  [✓] 保留列: {valid}")
        return self

    # ─── 第4步：加唯一ID（可选） ────────────────────────
    def add_record_id(self, prefix: str = "REC") -> "CSVToJSONLConverter":
        """为每一行生成唯一ID，格式: REC-XXXXXXXX"""
        ids = [f"{prefix}-{uuid.uuid4().hex[:8].upper()}" for _ in range(len(self.df))]
        self.df.insert(0, "record_id", ids)
        print(f"  [✓] 添加 {len(ids)} 个唯一ID，示例: {ids[0]}")
        return self

    # ─── 第5步：导出 JSONL ──────────────────────────────
    def export(self, output_path: str) -> Path:
        """
        输出标准 JSONL 文件
        - 第1行: 元数据（以 #metadata 开头）
        - 后面每行: 一条数据记录
        """
        output = Path(output_path)
        output.parent.mkdir(exist_ok=True, parents=True)

        with open(output, "w", encoding="utf-8") as f:
            # 元数据行
            f.write(json.dumps({"#metadata": self.metadata}, ensure_ascii=False) + "\n")

            # 数据行
            for _, row in self.df.iterrows():
                record = {
                    "record_id": row.get("record_id", uuid.uuid4().hex),
                    "data": {k: (None if pd.isna(v) else v) for k, v in row.items() if k != "record_id"},
                }
                f.write(json.dumps(record, ensure_ascii=False) + "\n")

        size_kb = output.stat().st_size / 1024
        print(f"  [✓] 导出: {output} ({size_kb:.1f} KB, {len(self.df)} 行)")
        return output


# ─── 快捷函数：一行调用完成全部 ─────────────────────────
def quick_convert(input_csv: str, output_jsonl: str = "output/data.jsonl",
                  fill_strategy: Optional[dict] = None,
                  keep_cols: Optional[List[str]] = None,
                  add_ids: bool = True):
    """一键转换：加载 → 可选清洗 → 导出"""
    c = CSVToJSONLConverter(input_csv)
    c.load()
    if fill_strategy:
        c.fill_missing(fill_strategy)
    if keep_cols:
        c.select_columns(keep_cols)
    if add_ids:
        c.add_record_id()
    return c.export(output_jsonl)


# ─── 直接运行此文件时，生成示例数据并演示转换 ──────────
if __name__ == "__main__":
    # 生成有意义的示例数据（100条电商订单）
    np.random.seed(42)
    sample = pd.DataFrame({
        "order_id": [f"ORD-{i:04d}" for i in range(1, 101)],
        "product": np.random.choice(["Laptop", "Mouse", "Keyboard", "Monitor"], 100),
        "quantity": np.random.randint(1, 10, 100),
        "price": np.random.uniform(10, 2000, 100).round(2),
        "customer_rating": np.random.choice(
            [1, 2, 3, 4, 5, None], 100,
            p=[0.02, 0.03, 0.1, 0.3, 0.5, 0.05]  # 5% 缺失
        ),
    })
    sample.to_csv("examples/sample_orders.csv", index=False)
    print("[✓] 生成示例数据: examples/sample_orders.csv")

    # 演示转换：填充评分缺失值 → 选列 → 加ID → 导出
    quick_convert(
        "examples/sample_orders.csv",
        "output/orders.jsonl",
        fill_strategy={"customer_rating": "mean"},
        keep_cols=["order_id", "product", "quantity", "price", "customer_rating"],
    )