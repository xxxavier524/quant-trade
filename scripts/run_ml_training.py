#!/usr/bin/env python3
"""AlphaPulse-A ML因子组合训练脚本。

使用LightGBM训练因子评分模型，用于因子组合和综合评分。

用法:
    python -W ignore -u scripts/run_ml_training.py
    python -W ignore -u scripts/run_ml_training.py --train-n 2000 --predict-n 500
"""

import argparse
import random
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from alphapulse.config.settings import DATA_DIR
from alphapulse.ml.factor_scorer import FactorScorer, _get_core_factor_names


def load_stocks(
    data_dir: str,
    n_sample: int = None,
    seed: int = 42,
    min_days: int = 250,
) -> dict[str, pd.DataFrame]:
    """从日线CSV目录加载股票数据。

    Args:
        data_dir: CSV日线数据目录
        n_sample: 随机抽样数量（None=全部）
        seed: 随机种子
        min_days: 最少交易日数

    Returns:
        dict: symbol -> DataFrame (DatetimeIndex)
    """
    data_path = Path(data_dir)
    if not data_path.exists():
        print(f"[ERROR] 数据目录不存在: {data_dir}")
        return {}

    files = list(data_path.glob("*.csv"))
    if n_sample and len(files) > n_sample:
        random.seed(seed)
        files = random.sample(files, n_sample)

    stocks = {}
    for f in files:
        symbol = f.stem
        try:
            df = pd.read_csv(f)
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

            df = df.sort_index()
            if len(df) >= min_days:
                stocks[symbol] = df
        except Exception as e:
            print(f"[WARN] 跳过 {symbol}: {e}")

    return stocks


def main():
    parser = argparse.ArgumentParser(description="AlphaPulse-A ML因子训练")
    parser.add_argument(
        "--data-dir", default=str(DATA_DIR),
        help=f"数据目录 (默认: {DATA_DIR})",
    )
    parser.add_argument(
        "--train-n", type=int, default=2000,
        help="训练用股票数量 (默认: 2000)",
    )
    parser.add_argument(
        "--predict-n", type=int, default=500,
        help="预测用股票数量 (0=全部剩余, 默认: 500)",
    )
    parser.add_argument(
        "--min-days", type=int, default=250,
        help="最少交易日数 (默认: 250)",
    )
    parser.add_argument(
        "--seed", type=int, default=42,
        help="随机种子 (默认: 42)",
    )
    args = parser.parse_args()

    core_factors = _get_core_factor_names()
    print(f"[INFO] Core因子 ({len(core_factors)}个): {core_factors}")

    # ================================================================
    # Step 1: 加载训练数据（2000只股票）
    # ================================================================
    print(f"\n{'='*60}")
    print(f"[Step 1] 加载训练数据: {args.data_dir}")
    print(f"{'='*60}")

    t0 = time.time()
    train_stocks = load_stocks(
        args.data_dir, n_sample=args.train_n, seed=args.seed,
        min_days=args.min_days,
    )
    # 记录已使用的股票代码，预测时排除
    used_symbols = set(train_stocks.keys())
    print(f"[INFO] 已加载 {len(train_stocks)} 只训练股票 (用时 {time.time()-t0:.1f}s)")

    if len(train_stocks) < 100:
        print(f"[ERROR] 训练股票数量不足 ({len(train_stocks)} < 100)，请检查数据目录")
        sys.exit(1)

    # ================================================================
    # Step 2: 计算core因子并构建特征/标签
    # ================================================================
    print(f"\n{'='*60}")
    print(f"[Step 2] 计算core因子并构建特征矩阵")
    print(f"{'='*60}")

    scorer = FactorScorer()
    t0 = time.time()
    X, y, symbols_train = scorer.prepare_features(train_stocks)
    elapsed = time.time() - t0
    print(f"[INFO] 特征矩阵: {X.shape[0]} 样本 x {X.shape[1]} 特征")
    print(f"[INFO] 特征列表: {list(X.columns)}")
    print(f"[INFO] 标签统计: mean={y.mean():.4f}, std={y.std():.4f}, "
          f"min={y.min():.4f}, max={y.max():.4f}")
    print(f"[INFO] 有效样本率: {X.shape[0]}/{len(train_stocks)} = "
          f"{X.shape[0]/len(train_stocks)*100:.1f}%")
    print(f"[INFO] 用时: {elapsed:.1f}s")

    if len(X) < 50:
        print(f"[ERROR] 有效样本不足 ({len(X)} < 50)，无法训练模型")
        sys.exit(1)

    # ================================================================
    # Step 3: 训练LightGBM模型
    # ================================================================
    print(f"\n{'='*60}")
    print(f"[Step 3] 训练LightGBM模型")
    print(f"{'='*60}")

    t0 = time.time()
    metrics = scorer.train(X, y)
    elapsed = time.time() - t0
    print(f"[INFO] 训练完成 (用时 {elapsed:.1f}s)")
    print(f"[INFO] 训练集 R²: {metrics['train_r2']:.4f}")
    print(f"[INFO] 验证集 R²: {metrics['val_r2']:.4f}")
    print(f"[INFO] 验证集 Spearman秩相关: {metrics['val_spearman']:.4f}")
    print(f"[INFO] 样本数: {metrics['n_samples']}, 特征数: {metrics['n_features']}")

    # ================================================================
    # Step 4: Top 10 因子重要性
    # ================================================================
    print(f"\n{'='*60}")
    print(f"[Step 4] Top 10 因子重要性")
    print(f"{'='*60}")
    print(f"{'因子名称':<35s} {'重要性':>10s}")
    print("-" * 47)
    for name, imp in scorer.get_top_factors(10):
        print(f"{name:<35s} {imp:10.4f}")

    # 输出完整重要性用于参考
    print(f"\n[INFO] 完整因子重要性排名:")
    for i, (name, imp) in enumerate(scorer.get_top_factors(len(scorer.feature_names))):
        bar = "█" * int(imp / max(scorer.feature_importance.values()) * 40)
        print(f"  {i+1:2d}. {name:<32s} {imp:.4f} {bar}")

    # ================================================================
    # Step 5: 训练集性能详细分析
    # ================================================================
    print(f"\n{'='*60}")
    print(f"[Step 5] 训练/验证集性能")
    print(f"{'='*60}")

    # 在训练数据上做交叉验证分位数分析
    from sklearn.model_selection import cross_val_score
    y_pred = scorer.model.predict(scorer.scaler.transform(X))
    # 按预测分数分10组，看实际收益
    pred_series = pd.Series(y_pred, index=symbols_train)
    y_series = y

    # 分位数分析
    quantiles = pd.qcut(pred_series, q=10, labels=False, duplicates="drop")
    print(f"\n  分位数收益分析 (预测分数从低到高):")
    print(f"  {'分位组':<8s} {'平均预测分':>12s} {'平均实际收益':>14s} {'样本数':>8s}")
    print(f"  {'-'*45}")
    for q in sorted(set(quantiles)):
        mask = quantiles == q
        if mask.sum() > 0:
            avg_pred = pred_series[mask].mean()
            avg_actual = y_series[mask].mean()
            print(f"  Q{q+1:<7d} {avg_pred:12.4f} {avg_actual:14.6f} {mask.sum():8d}")

    # Top/Bottom分位多空收益
    top_q = quantiles.max()
    bot_q = quantiles.min()
    top_return = y_series[quantiles == top_q].mean()
    bot_return = y_series[quantiles == bot_q].mean()
    long_short = top_return - bot_return
    print(f"\n  多空收益 (Top Q{top_q+1} - Bottom Q{bot_q+1}): {long_short:.6f} "
          f"(Top: {top_return:.6f}, Bottom: {bot_return:.6f})")

    # ================================================================
    # Step 6: 对剩余股票做预测
    # ================================================================
    print(f"\n{'='*60}")
    print(f"[Step 6] 对剩余股票做预测")
    print(f"{'='*60}")

    if args.predict_n > 0:
        # 加载预测用股票（排除训练用过的）
        all_files = list(Path(args.data_dir).glob("*.csv"))
        predict_files = [
            f for f in all_files if f.stem not in used_symbols
        ]
        if len(predict_files) > args.predict_n:
            random.seed(args.seed + 1)
            predict_files = random.sample(predict_files, args.predict_n)

        t0 = time.time()
        predict_stocks = {}
        for f in predict_files:
            symbol = f.stem
            try:
                df = pd.read_csv(f)
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

                if isinstance(df.index, pd.DatetimeIndex):
                    df = df.sort_index()
                    if len(df) >= args.min_days:
                        predict_stocks[symbol] = df
            except Exception:
                pass

        print(f"[INFO] 已加载 {len(predict_stocks)} 只预测股票 (用时 {time.time()-t0:.1f}s)")

        if predict_stocks:
            t0 = time.time()
            results = scorer.predict(predict_stocks)
            print(f"[INFO] 预测完成 (用时 {time.time()-t0:.1f}s)")

            # ================================================================
            # Step 7: Top 20 推荐股票
            # ================================================================
            print(f"\n{'='*60}")
            print(f"[Step 7] Top 20 推荐股票")
            print(f"{'='*60}")
            top20 = results.head(20)
            print(f"\n  {'排名':<6s} {'代码':<10s} {'预测分数':>10s} {'Top 3因子贡献'}")
            print(f"  {'-'*65}")
            for i, row in top20.iterrows():
                print(f"  {i+1:<6d} {row['symbol']:<10s} {row['score']:10.4f} "
                      f" {row['top_factors']}")

            # 预测分数统计
            print(f"\n  [INFO] 预测分数统计 (全部{len(results)}只):")
            print(f"    mean={results['score'].mean():.4f}, "
                  f"std={results['score'].std():.4f}")
            print(f"    min={results['score'].min():.4f}, "
                  f"max={results['score'].max():.4f}")
            print(f"    >0比例: {(results['score'] > 0).mean()*100:.1f}%")
    else:
        print(f"[INFO] 跳过预测 (--predict-n=0)")

    print(f"\n{'='*60}")
    print(f"[DONE] ML训练完成")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
