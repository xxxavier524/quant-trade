#!/usr/bin/env python3
"""AlphaPulse-A 6-Agent + 3-Gate 量化策略流水线 CLI。

用法:
    # 运行完整流水线（使用已有策略）
    python scripts/run_pipeline.py \
        --strategy B1 \
        --hypothesis "B1选股方案：6条件AND组合" \
        --data-dir /path/to/data/day \
        --start 2020-01-01 --end 2025-12-31

    # 批量测试多条假设
    python scripts/run_pipeline.py \
        --batch configs/batch_hypotheses.json \
        --data-dir /path/to/data/day

    # 查看历史实验
    python scripts/run_pipeline.py --list-best 10

    # 导出实验报告
    python scripts/run_pipeline.py --export-report

    # 干跑模式（跳过 Layer 2 验证）
    python scripts/run_pipeline.py --strategy B1 --quick

环境:
    source /Users/qiushixuan/cc/quantan trade/.venv/bin/activate
"""

import argparse
import json
import sys
import time
from pathlib import Path
from datetime import datetime

# 添加项目根目录
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import numpy as np


def setup_argparser():
    parser = argparse.ArgumentParser(
        description="AlphaPulse-A 6-Agent + 3-Gate 量化策略流水线",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # 运行模式
    parser.add_argument(
        "--strategy", type=str, default=None,
        choices=["B1", "BRICK", "NEEDLE"],
        help="使用已有策略运行流水线",
    )
    parser.add_argument(
        "--hypothesis", type=str, default="",
        help="策略假设描述（自然语言）",
    )
    parser.add_argument(
        "--batch", type=str, default=None,
        help="批量运行配置文件 (JSON)",
    )
    parser.add_argument(
        "--list-best", type=int, default=None, metavar="N",
        help="列出历史最优 N 个实验",
    )
    parser.add_argument(
        "--export-report", action="store_true",
        help="导出实验对比报告",
    )

    # 数据和回测参数
    parser.add_argument(
        "--data-dir", type=str, default=None,
        help="日线 CSV 数据目录（覆盖 settings.DATA_DIR）",
    )
    parser.add_argument("--start", type=str, default="2020-01-01")
    parser.add_argument("--end", type=str, default="2025-12-31")
    parser.add_argument("--capital", type=float, default=1_000_000)
    parser.add_argument("--sample", type=int, default=None,
                       help="随机抽样 N 只股票（加速测试）")

    # 流水线配置
    parser.add_argument("--dsr-trials", type=int, default=100,
                       help="DSR 多重测试次数")
    parser.add_argument("--dsr-sig", type=float, default=0.95,
                       help="DSR 显著性水平")
    parser.add_argument("--max-corr", type=float, default=0.70,
                       help="最大允许策略相关性")
    parser.add_argument("--max-dd", type=float, default=25.0,
                       help="最大允许回撤")
    parser.add_argument("--wf-train", type=int, default=3,
                       help="Walk-Forward 训练年数")
    parser.add_argument("--wf-test", type=int, default=1,
                       help="Walk-Forward 测试年数")

    # 加速标志
    parser.add_argument("--quick", action="store_true",
                       help="快速模式：跳过 Layer 2 验证 + 抽样 100 股票")
    parser.add_argument("--no-layer2", action="store_true",
                       help="跳过 Layer 2 验证（WF/CV/DSR）")

    # 输出
    parser.add_argument("--output", type=str, default=None,
                       help="结果输出 JSON 文件路径")
    parser.add_argument("--verbose", "-v", action="store_true",
                       help="详细输出")

    return parser


def load_stocks(data_dir: str, symbols: list[str] = None, sample: int = None,
                start: str = "2020-01-01", end: str = "2025-12-31",
                min_days: int = 365) -> dict:
    """加载股票日线 CSV 数据。

    Returns:
        dict: symbol -> DataFrame (OHLCV, DatetimeIndex)
    """
    data_path = Path(data_dir)
    if not data_path.exists():
        print(f"[ERROR] 数据目录不存在: {data_dir}")
        return {}

    files = list(data_path.glob("*.csv"))
    if symbols:
        sym_set = set(symbols)
        files = [f for f in files if f.stem in sym_set]

    if sample and len(files) > sample:
        import random
        random.seed(42)
        files = random.sample(files, sample)

    stocks = {}
    for f in files:
        symbol = f.stem
        try:
            df = pd.read_csv(f)
            # 日期索引解析
            first_col = df.columns[0]
            try:
                maybe_dates = pd.to_datetime(df[first_col])
                if len(maybe_dates.dropna()) > 0.8 * len(df):
                    df["date"] = maybe_dates
                    df = df.set_index("date")
            except Exception:
                if "date" in df.columns:
                    df["date"] = pd.to_datetime(df["date"])
                    df = df.set_index("date")

            if not isinstance(df.index, pd.DatetimeIndex):
                continue

            df = df[(df.index >= start) & (df.index <= end)]
            if len(df) >= min_days:
                stocks[symbol] = df.sort_index()
        except Exception as e:
            print(f"[WARN] 跳过 {symbol}: {e}")

    return stocks


def get_strategy_fn(strategy_name: str):
    """根据策略名称获取信号生成函数。"""
    if strategy_name == "B1":
        from alphapulse.strategies.b1_formula_strategy import generate_signals
        return generate_signals
    elif strategy_name == "BRICK":
        from alphapulse.strategies.brick_ultra_strategy import generate_signals
        return generate_signals
    elif strategy_name == "NEEDLE":
        from alphapulse.strategies.needle_enhanced import generate_signals
        return generate_signals
    else:
        return None


def run_single(args):
    """运行单策略流水线。"""
    from alphapulse.pipeline.orchestrator import PipelineOrchestrator, PipelineConfig
    from alphapulse.config.settings import DATA_DIR

    data_dir = args.data_dir or str(DATA_DIR)
    sample_n = args.sample or (100 if args.quick else None)

    print(f"[INFO] 加载数据: {data_dir}")
    stocks = load_stocks(data_dir, sample=sample_n,
                         start=args.start, end=args.end)
    print(f"[INFO] 已加载 {len(stocks)} 只股票")

    if not stocks:
        print("[ERROR] 无可用数据，请检查数据目录和采样设置。")
        return None

    # 获取策略函数
    strategy_fn = None
    strategy_name = args.strategy or "custom"
    if args.strategy:
        strategy_fn = get_strategy_fn(args.strategy)
        if strategy_fn is None:
            print(f"[ERROR] 策略 '{args.strategy}' 未找到")
            return None

    # 配置
    config = PipelineConfig(
        dsr_n_trials=args.dsr_trials,
        dsr_significance=args.dsr_sig,
        risk_max_correlation=args.max_corr,
        risk_max_drawdown=args.max_dd,
        initial_capital=args.capital,
        backtest_start=args.start,
        backtest_end=args.end,
        wf_train_years=args.wf_train,
        wf_test_years=args.wf_test,
    )

    hypothesis_text = args.hypothesis or f"已有策略 {args.strategy or 'custom'} 回测验证"

    orchestrator = PipelineOrchestrator(config)
    skip_layer2 = args.no_layer2 or args.quick

    print(f"\n[INFO] 开始流水线执行...")
    print(f"  策略: {strategy_name}")
    print(f"  假设: {hypothesis_text}")
    print(f"  股票: {len(stocks)} 只")
    print(f"  区间: {args.start} ~ {args.end}")
    print(f"  Layer2: {'跳过' if skip_layer2 else '完整'}")
    print()

    result = orchestrator.run(
        hypothesis_text=hypothesis_text,
        stocks=stocks,
        strategy_fn=strategy_fn,
        strategy_name=strategy_name,
        skip_layer2=skip_layer2,
    )

    result.print_summary()

    # 保存结果
    if args.output:
        out_path = Path(args.output)
    else:
        out_dir = Path(__file__).resolve().parent.parent / "reports" / "pipeline_results"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"pipeline_{strategy_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

    with open(out_path, "w") as f:
        json.dump(result.to_dict(), f, indent=2, default=str, ensure_ascii=False)
    print(f"[INFO] 结果已保存: {out_path}")

    return result


def run_batch(args):
    """批量运行多条假设。"""
    from alphapulse.pipeline.orchestrator import PipelineOrchestrator, PipelineConfig
    from alphapulse.config.settings import DATA_DIR

    batch_path = Path(args.batch)
    if not batch_path.exists():
        print(f"[ERROR] 批量配置文件不存在: {args.batch}")
        return

    with open(batch_path) as f:
        batch_config = json.load(f)

    hypotheses = batch_config.get("hypotheses", [])
    if not hypotheses:
        print("[ERROR] 配置文件中无 hypotheses 字段")
        return

    data_dir = args.data_dir or str(DATA_DIR)
    stocks = load_stocks(data_dir, sample=args.sample or 50,
                         start=args.start, end=args.end)
    print(f"[INFO] 批量模式：已加载 {len(stocks)} 只股票")
    print(f"[INFO] 共 {len(hypotheses)} 条假设")

    config = PipelineConfig(
        dsr_n_trials=args.dsr_trials,
        dsr_significance=args.dsr_sig,
        risk_max_correlation=args.max_corr,
        risk_max_drawdown=args.max_dd,
        initial_capital=args.capital,
        backtest_start=args.start,
        backtest_end=args.end,
        wf_train_years=args.wf_train,
        wf_test_years=args.wf_test,
    )

    orchestrator = PipelineOrchestrator(config)
    skip_layer2 = args.no_layer2 or args.quick

    results = orchestrator.run_batch(
        hypotheses=hypotheses,
        stocks=stocks,
        skip_layer2=skip_layer2,
    )

    # 打印批量汇总
    print("\n" + "=" * 70)
    print("  BATCH SUMMARY")
    print("=" * 70)
    passed = sum(1 for r in results if r.all_gates_passed)
    print(f"  Total: {len(results)} | Passed Gates: {passed} | Failed Gates: {len(results) - passed}")
    print("-" * 70)
    for r in results:
        status = "PASSED" if r.all_gates_passed else "FAILED"
        print(f"  [{status}] {r.summary.get('sharpe_ratio', 'N/A'):>6} SR  "
              f"{r.hypothesis_agent.get('data', {}).get('hypothesis_text', '')[:50]}")
    print("=" * 70)

    return results


def list_best(args):
    """列出历史最优实验。"""
    from alphapulse.pipeline.memory import StrategyMemory

    memory = StrategyMemory()
    best = memory.query(
        min_sharpe=0.3,
        sort_by="sharpe_ratio",
        limit=args.list_best or 10,
    )

    if not best:
        print("[INFO] 暂无实验记录。")
        return

    print("\n" + "=" * 70)
    print(f"  Top {len(best)} Experiments")
    print("=" * 70)
    for i, exp in enumerate(best):
        bt = exp.agents.get("backtest_agent", {}).get("data", {})
        gates_passed = exp.gates.get("all_passed", False)
        gate_icon = "PASSED" if gates_passed else "FAILED"
        print(f"  [{i+1}] {exp.experiment_id[:12]} | {gate_icon:>6} | "
              f"SR={bt.get('sharpe_ratio', 'N/A'):>6} | "
              f"Return={bt.get('annual_return', 'N/A'):>6}% | "
              f"DD={bt.get('max_drawdown', 'N/A'):>5}% | "
              f"WR={bt.get('win_rate', 'N/A'):>5}%")
    print("=" * 70)

    return best


def export_report(args):
    """导出实验报告。"""
    from alphapulse.pipeline.memory import StrategyMemory

    memory = StrategyMemory()
    path = memory.export_report()
    if path:
        print(f"[INFO] 报告已导出: {path}")
    else:
        print("[INFO] 无实验数据可导出。")


def main():
    parser = setup_argparser()
    args = parser.parse_args()

    print("AlphaPulse-A Pipeline v1.0")
    print(f"时间: {datetime.now().isoformat()}")
    print()

    # 查看历史
    if args.list_best:
        list_best(args)
        return

    # 导出报告
    if args.export_report:
        export_report(args)
        return

    # 批量模式
    if args.batch:
        run_batch(args)
        return

    # 单策略模式
    if args.strategy or args.hypothesis:
        result = run_single(args)
        if result is not None and result.status == "passed":
            print("\n[SUCCESS] 流水线执行完成，策略通过全部闸门验证。")
        elif result is not None:
            print(f"\n[DONE] 流水线执行完成，状态: {result.status}")
        return

    # 无参数
    parser.print_help()


if __name__ == "__main__":
    main()
