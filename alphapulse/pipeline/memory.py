"""策略记忆 / 实验跟踪模块。

功能:
- 记录每次完整的流水线运行结果
- 持久化到 JSON 文件
- 查询历史实验（按夏普、胜率、Gate 通过情况过滤）
- 生成实验对比报告

设计原则:
- 轻量级: 纯 JSON 存储，无需数据库
- 可追溯: 每个实验有唯一 ID + 时间戳
- 可比较: 支持多维度筛选和排序
"""

import json
import os
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

import numpy as np
import pandas as pd


@dataclass
class ExperimentRecord:
    """单次实验的完整记录。"""
    experiment_id: str = ""
    started_at: str = ""
    completed_at: str = ""
    hypothesis: dict = field(default_factory=dict)
    status: str = "running"  # running, completed, failed
    agents: dict[str, dict] = field(default_factory=dict)
    gates: dict[str, dict] = field(default_factory=dict)
    validation: dict = field(default_factory=dict)
    summary: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "experiment_id": self.experiment_id,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "hypothesis": self.hypothesis,
            "status": self.status,
            "agents": self.agents,
            "gates": self.gates,
            "validation": self.validation,
            "summary": self.summary,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ExperimentRecord":
        return cls(
            experiment_id=d.get("experiment_id", ""),
            started_at=d.get("started_at", ""),
            completed_at=d.get("completed_at", ""),
            hypothesis=d.get("hypothesis", {}),
            status=d.get("status", "unknown"),
            agents=d.get("agents", {}),
            gates=d.get("gates", {}),
            validation=d.get("validation", {}),
            summary=d.get("summary", {}),
        )


class StrategyMemory:
    """策略实验记忆存储。

    存储所有流水线运行记录，支持:
    - 写: record(result) -> experiment_id
    - 读: query(...) -> records
    - 对比: compare(ids) -> DataFrame
    - 排名: rank(by='sharpe') -> records
    """

    def __init__(self, storage_path: str = ""):
        """初始化记忆存储。

        Args:
            storage_path: 存储目录路径，默认 'reports/pipeline_memory/'
        """
        if not storage_path:
            import os
            storage_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                "reports", "pipeline_memory",
            )
        self.storage_path = storage_path
        self.records: dict[str, ExperimentRecord] = {}
        self._load()

    def record(self, experiment: ExperimentRecord) -> str:
        """记录一次实验。"""
        if not experiment.experiment_id:
            experiment.experiment_id = f"exp_{int(time.time()*1000)}_{os.urandom(4).hex()}"

        self.records[experiment.experiment_id] = experiment
        self._persist()
        return experiment.experiment_id

    def get(self, experiment_id: str) -> Optional[ExperimentRecord]:
        """获取指定实验记录。"""
        return self.records.get(experiment_id)

    def query(
        self,
        status: Optional[str] = None,
        min_sharpe: Optional[float] = None,
        min_win_rate: Optional[float] = None,
        all_gates_passed: Optional[bool] = None,
        sort_by: str = "sharpe_ratio",
        limit: int = 50,
    ) -> list[ExperimentRecord]:
        """查询实验记录。

        Args:
            status: 筛选实验状态 (completed, failed, running)
            min_sharpe: 最低年化夏普比率
            min_win_rate: 最低胜率 (%)
            all_gates_passed: 是否要求通过全部闸门
            sort_by: 排序字段 (sharpe_ratio, win_rate, total_return, max_drawdown)
            limit: 返回结果上限

        Returns:
            排序后的实验记录列表
        """
        results = []
        for exp in self.records.values():
            if status and exp.status != status:
                continue

            summary = exp.summary
            backtest = exp.agents.get("backtest_agent", {}).get("data", {})

            sharpe = backtest.get("sharpe_ratio", 0)
            win_rate = backtest.get("win_rate", 0)

            if min_sharpe is not None and sharpe < min_sharpe:
                continue
            if min_win_rate is not None and win_rate < min_win_rate:
                continue
            if all_gates_passed:
                if not exp.gates.get("all_passed", False):
                    continue

            results.append(exp)

        # 排序
        sort_key_map = {
            "sharpe_ratio": lambda e: e.agents.get("backtest_agent", {}).get("data", {}).get("sharpe_ratio", 0),
            "win_rate": lambda e: e.agents.get("backtest_agent", {}).get("data", {}).get("win_rate", 0),
            "total_return": lambda e: e.agents.get("backtest_agent", {}).get("data", {}).get("total_return", 0),
            "max_drawdown": lambda e: -abs(e.agents.get("backtest_agent", {}).get("data", {}).get("max_drawdown", 0)),
        }
        key_fn = sort_key_map.get(sort_by, sort_key_map["sharpe_ratio"])
        results.sort(key=key_fn, reverse=True)

        return results[:limit]

    def compare(self, experiment_ids: list[str]) -> pd.DataFrame:
        """比较多个实验的绩效指标。

        Args:
            experiment_ids: 实验 ID 列表

        Returns:
            DataFrame: 每行一个实验，列为指标
        """
        rows = []
        for eid in experiment_ids:
            exp = self.records.get(eid)
            if exp is None:
                continue
            bt = exp.agents.get("backtest_agent", {}).get("data", {})
            gates = exp.gates
            row = {
                "experiment_id": eid[:12],
                "status": exp.status,
                "total_return": bt.get("total_return"),
                "annual_return": bt.get("annual_return"),
                "max_drawdown": bt.get("max_drawdown"),
                "sharpe_ratio": bt.get("sharpe_ratio"),
                "calmar_ratio": bt.get("calmar_ratio"),
                "sortino_ratio": bt.get("sortino_ratio"),
                "win_rate": bt.get("win_rate"),
                "total_trades": bt.get("total_trades"),
                "profit_loss_ratio": bt.get("profit_loss_ratio"),
                "gates_passed": gates.get("all_passed", False),
                "degradation_ratio": exp.validation.get("degradation_ratio"),
            }
            rows.append(row)

        return pd.DataFrame(rows)

    def rank(self, by: str = "sharpe_ratio", top_n: int = 10) -> pd.DataFrame:
        """对所有已完成实验排名。

        Args:
            by: 排名依据
            top_n: 返回前 N 名

        Returns:
            DataFrame: 排名表
        """
        completed = [e for e in self.records.values() if e.status == "completed"]
        return self.compare([e.experiment_id for e in completed])

    def stats(self) -> dict:
        """返回实验记忆的统计摘要。"""
        total = len(self.records)
        completed = sum(1 for e in self.records.values() if e.status == "completed")
        failed = sum(1 for e in self.records.values() if e.status == "failed")
        gated = sum(1 for e in self.records.values() if e.gates.get("all_passed", False))

        sharpes = []
        for e in self.records.values():
            sr = e.agents.get("backtest_agent", {}).get("data", {}).get("sharpe_ratio", 0)
            sharpes.append(sr)

        return {
            "total_experiments": total,
            "completed": completed,
            "failed": failed,
            "gates_passed": gated,
            "best_sharpe": max(sharpes) if sharpes else 0,
            "mean_sharpe": round(float(np.mean(sharpes)), 4) if sharpes else 0,
            "median_sharpe": round(float(np.median(sharpes)), 4) if sharpes else 0,
        }

    def _persist(self):
        """持久化到磁盘。"""
        os.makedirs(self.storage_path, exist_ok=True)
        filepath = os.path.join(self.storage_path, "experiments.json")
        data = {
            eid: exp.to_dict() for eid, exp in self.records.items()
        }
        # 写入临时文件再 rename，保证原子性
        tmp_path = filepath + ".tmp"
        with open(tmp_path, "w") as f:
            json.dump(data, f, indent=2, default=str, ensure_ascii=False)
        os.replace(tmp_path, filepath)

    def _load(self):
        """从磁盘加载记录。"""
        filepath = os.path.join(self.storage_path, "experiments.json")
        if os.path.exists(filepath):
            try:
                with open(filepath) as f:
                    data = json.load(f)
                self.records = {
                    eid: ExperimentRecord.from_dict(exp)
                    for eid, exp in data.items()
                }
            except (json.JSONDecodeError, KeyError):
                self.records = {}

    def clear(self):
        """清空所有记录（慎用）。"""
        self.records = {}
        self._persist()

    def export_report(self, output_path: str = "") -> str:
        """导出实验对比 Markdown 报告。

        Returns:
            报告文件路径
        """
        df = self.rank()
        if df.empty:
            return ""

        if not output_path:
            output_path = os.path.join(self.storage_path, "experiment_report.md")

        lines = [
            "# Pipeline 实验报告",
            "",
            f"生成时间: {datetime.now().isoformat()}",
            f"总实验数: {len(self.records)}",
            "",
            "## 实验排行榜",
            "",
            "| ID | 年化收益 | 最大回撤 | 夏普 | Calmar | Sortino | 胜率 | 交易数 | Gate全过 | 退化率 |",
            "|----|----------|----------|------|--------|---------|------|--------|----------|--------|",
        ]

        for _, row in df.head(30).iterrows():
            lines.append(
                f"| {row['experiment_id']} "
                f"| {row['annual_return']}% "
                f"| {row['max_drawdown']}% "
                f"| {row['sharpe_ratio']} "
                f"| {row['calmar_ratio']} "
                f"| {row['sortino_ratio']} "
                f"| {row['win_rate']}% "
                f"| {row['total_trades']} "
                f"| {row['gates_passed']} "
                f"| {row.get('degradation_ratio', '-')} |"
            )

        lines.append("")
        lines.append("## 统计摘要")
        stats = self.stats()
        lines.append(f"- 总实验: {stats['total_experiments']}")
        lines.append(f"- 已完成: {stats['completed']}")
        lines.append(f"- 失败: {stats['failed']}")
        lines.append(f"- 通过全部Gate: {stats['gates_passed']}")
        lines.append(f"- 最佳夏普: {stats['best_sharpe']}")
        lines.append(f"- 平均夏普: {stats['mean_sharpe']}")
        lines.append(f"- 中位夏普: {stats['median_sharpe']}")

        report = "\n".join(lines)
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w") as f:
            f.write(report)

        return output_path
