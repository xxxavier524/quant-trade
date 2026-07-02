"""ML 形态模型训练 CLI。

用法：
    python scripts/train_ml_model.py --sample 1500   # 约10-20分钟
"""

import argparse
import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from alphapulse.config.settings import DATA_DIR  # noqa: E402
from alphapulse.ml import pattern_model as pm  # noqa: E402
from validate_signal import load_universe  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=1500)
    ap.add_argument("--data-dir", default=DATA_DIR)
    args = ap.parse_args()

    t0 = time.monotonic()
    stocks = load_universe(Path(args.data_dir), args.sample, "9999-12-31")
    print(f"universe: {len(stocks)} 只")

    # 战法模拟参数：读 best_params 的调优止损口径（2026-07-02 网格：stop_pct=0.10）
    pb_kwargs = {}
    try:
        bp = json.loads((PROJECT_ROOT / "config" / "best_params.json").read_text())
        sp = bp.get("PLAYBOOK_B1B2B3", {}).get("stop_pct")
        if sp:
            pb_kwargs["B1B2B3"] = {"stop_pct": sp}
            print(f"B1B2B3 标签口径: stop_pct={sp}（best_params）")
    except Exception:
        pass

    print("构建训练集（战法交易特征化，较慢）...")
    train_df = pm.build_training_set(stocks, playbook_kwargs=pb_kwargs)
    print(f"  战法交易样本: {len(train_df)} 笔")
    train_df = pm.append_boost_samples(train_df, stocks)
    print(f"  并入连涨强化样本后: {len(train_df)} 笔")

    if len(train_df) < 1000:
        sys.exit("样本不足1000，加大 --sample")

    report = pm.train(train_df)
    print(f"\n===== 训练完成（{(time.monotonic()-t0)/60:.1f} 分钟）=====")
    print(json.dumps({k: v for k, v in report.items() if k != "features"},
                     ensure_ascii=False, indent=2))
    print(f"模型已存 {pm.MODEL_PATH}")


if __name__ == "__main__":
    main()
