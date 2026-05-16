"""AlphaPulse-A 全局配置常量"""

import os

# === 路径 ===
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(PROJECT_ROOT, "data", "day")
BACKTEST_RESULTS_DIR = os.path.join(PROJECT_ROOT, "backtest_results")
REPORTS_DIR = os.path.join(PROJECT_ROOT, "reports")

# 通达信数据源（macOS 本地路径或移动硬盘挂载点）
TDX_SOURCE_DIRS = [
    os.path.expanduser("~/tdx/vipdoc"),           # 本地副本
    "/Volumes/quant_data/vipdoc",                  # 移动硬盘
    "/Volumes/Data/tdx/vipdoc",                    # 备用
]

# === 回测参数 ===
# 滑点：买入+0.1%，卖出-0.2%
SLIPPAGE_BUY = 0.001    # 0.1%
SLIPPAGE_SELL = 0.002   # 0.2%

# 手续费：万2.5，最低5元
COMMISSION_RATE = 0.00025
COMMISSION_MIN = 5.0

# 仓位限制：单票 ≤ 20%，最多持有5只
MAX_SINGLE_POSITION = 0.20
MAX_HOLDINGS = 5

# 初始资金
INITIAL_CAPITAL = 1_000_000  # 100万

# 回测时间范围
BACKTEST_START = "2020-01-01"
BACKTEST_END = "2025-12-31"

# === 因子默认参数 ===
FACTOR_PARAMS = {
    "N_STRUCT": {"min_leg_len": 5, "retrace_ratio": 0.618},
    "VOL_RED_GREEN": {"N": 20, "ratio_threshold": 1.3},
    "ABNORMAL_VOL": {"M": 60, "P": 20, "K": 2.0, "X": 3, "Y": 5},
    "VOL_CONT_SHRINK": {"shrink_ratio": 0.25, "recent_period": 5},
    "KDJ_J_LOW": {"j_threshold": 13},
    "WEEKLY_MA_BULL": {"ma_periods": [5, 10, 20]},
    "MACD_BULL_DEAD": {"fast": 12, "slow": 26, "signal": 9},
    "SHRINK_TO_ABNORMAL": {"ratio": 0.25},
}

# === 网格搜索范围 ===
GRID_SEARCH = {
    "shrink_ratio": [0.2, 0.25, 0.3, 0.4],
    "j_threshold": [8, 10, 13, 15],
    "K": [1.5, 2.0, 2.5, 3.0],
}
