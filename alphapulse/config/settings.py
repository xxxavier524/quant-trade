"""AlphaPulse-A 全局配置常量"""

import os

# === 路径 ===
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# 2026-07-10 用户决定：日线主存储放回外接盘；内置盘 data/day 仅为迁移期旧副本，勿再读写。
# 临时切换用环境变量 ALPHAPULSE_DATA_DIR 覆盖。
DATA_DIR = os.environ.get(
    "ALPHAPULSE_DATA_DIR",
    "/Volumes/Mac-480g外接/quantan_data/day",
)
# 外接盘有掉线史（2026-07-04 曾因此迁盘）。卷未挂载时任何 makedirs 都会在内置盘生成
# 同名假目录、后续数据静默写错位置，故缺盘必须在 import 时快速失败。
if not os.path.isdir(DATA_DIR):
    raise RuntimeError(
        f"数据目录不可用: {DATA_DIR} —— 外接盘未挂载？接盘后重试，或设 ALPHAPULSE_DATA_DIR 临时切换"
    )
# K线包含合并预处理：仅知行超短信号用合并后K线生成（生产AB 2026-07-12：
# 成功率+4.4pp、z=6.79、平均5日收益+0.72%→+1.40%，见 reports/ab_kline_merge_prod.md）。
# 砖型图AB未过门槛(Δ+1.5pp,z=1.76)不启用。改 False 即回退原始K线。
KLINE_MERGE_ZHIXING = True

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

# ===== AlphaPulse v3.0 settings (appended) =====
DATA_SOURCES_PRIORITY = ["akshare", "baostock", "pytdx", "yfinance"]
MAX_CONCURRENT_WORKERS = 3
REQUEST_INTERVAL_RANGE = (0.5, 1.5)
CIRCUIT_BREAKER_FAILS = 5
CIRCUIT_BREAKER_PAUSE_SEC = 600
SINGLE_STOCK_TIMEOUT_SEC = 30
GLOBAL_SCREEN_TIMEOUT_MIN = 30

MACRO_SCORE_THRESHOLDS = {
    "bull": 80, "slightly_bull": 60, "neutral": 40, "slightly_bear": 20
}
SELECTION_TOP_PCT = 0.5
DIAGNOSIS_WEIGHTS = {
    "technical": 30, "volume": 20, "pattern": 20, "risk": 15, "sector": 15
}
DIAGNOSIS_GRADE_THRESHOLDS = {"S": 85, "A": 70, "B": 55, "C": 40}

AUTO_RESEARCH_START_HOUR = 3
AUTO_RESEARCH_END_HOUR = 5.5
AUTO_RESEARCH_IMPROVEMENT_RATIO = 1.05
AUTO_RESEARCH_SNAPSHOT_KEEP = 3

def _env_or_dotenv(key: str) -> str:
    """环境变量优先，其次项目根 .env（gitignored，与 DEEPSEEK_API_KEY 同处）。"""
    v = os.environ.get(key, "")
    if v:
        return v
    try:
        for line in open(os.path.join(PROJECT_ROOT, ".env")):
            line = line.strip()
            if line.startswith(f"{key}="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    return ""


# 飞书群机器人 webhook：配置在 .env（FEISHU_WEBHOOK_URL=https://open.feishu.cn/...）
# 机器人安全设置用自定义关键词 "AlphaPulse"（所有推送消息统一带此前缀）
FEISHU_WEBHOOK_URL = _env_or_dotenv("FEISHU_WEBHOOK_URL")
VIBE_TRADING_URL = "http://localhost:8899"
STREAMLIT_PORT = 8501
SQLITE_DB_PATH = "backtest_results/short_term.db"
