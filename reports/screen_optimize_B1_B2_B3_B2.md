# 纯选股成功率优化 — B1_B2_B3[B2]

样本 785 只 | 54 组参数 × 8 窗 | 口径: 信号后5日内收盘≥+5%（机会命中）
 | 稳健分 = 0.5×中位窗 + 0.5×最差窗；基线 = 同窗全体股票命中率

## Top 10（按稳健分）

| # | 稳健% | 中位% | 最差% | 基线中位% | 超额pp | 有效窗 | 总信号 | 参数 |
|---|---|---|---|---|---|---|---|---|
| 1 | 23.4 | 26.7 | 20.2 | 20.5 | +3.0 | 8 | 2420 | `{"j_threshold": 18, "pct_change_range": 5.0, "vol_mult_b2": 2.0, "min_conf_b1": 0.0}` |
| 2 | 23.4 | 26.7 | 20.2 | 20.5 | +3.0 | 8 | 2420 | `{"j_threshold": 18, "pct_change_range": 5.0, "vol_mult_b2": 2.0, "min_conf_b1": 0.7}` |
| 3 | 23.4 | 26.6 | 20.2 | 20.3 | +3.1 | 8 | 2053 | `{"j_threshold": 13, "pct_change_range": 5.0, "vol_mult_b2": 2.0, "min_conf_b1": 0.0}` |
| 4 | 23.4 | 26.6 | 20.2 | 20.3 | +3.1 | 8 | 2053 | `{"j_threshold": 13, "pct_change_range": 5.0, "vol_mult_b2": 2.0, "min_conf_b1": 0.7}` |
| 5 | 23.3 | 26.6 | 20.1 | 20.5 | +2.8 | 8 | 2436 | `{"j_threshold": 18, "pct_change_range": 7.0, "vol_mult_b2": 2.0, "min_conf_b1": 0.0}` |
| 6 | 23.3 | 26.6 | 20.1 | 20.5 | +2.8 | 8 | 2436 | `{"j_threshold": 18, "pct_change_range": 7.0, "vol_mult_b2": 2.0, "min_conf_b1": 0.7}` |
| 7 | 23.3 | 26.4 | 20.2 | 20.4 | +2.9 | 8 | 2066 | `{"j_threshold": 13, "pct_change_range": 7.0, "vol_mult_b2": 2.0, "min_conf_b1": 0.0}` |
| 8 | 23.3 | 26.4 | 20.2 | 20.4 | +2.9 | 8 | 2066 | `{"j_threshold": 13, "pct_change_range": 7.0, "vol_mult_b2": 2.0, "min_conf_b1": 0.7}` |
| 9 | 23.2 | 25.9 | 20.6 | 20.5 | +2.7 | 8 | 3676 | `{"j_threshold": 18, "pct_change_range": 5.0, "vol_mult_b2": 1.5, "min_conf_b1": 0.0}` |
| 10 | 23.2 | 25.9 | 20.6 | 20.5 | +2.7 | 8 | 3676 | `{"j_threshold": 18, "pct_change_range": 5.0, "vol_mult_b2": 1.5, "min_conf_b1": 0.7}` |

## 链式流程回测（每窗只用之前窗口信息选参）

| 验证窗 | 样本外成功率% | 信号数 | 当时选中参数 |
|---|---|---|---|
| 2022-07-01~2022-12-31 | — | 0 | `—` |
| 2023-01-01~2023-06-30 | 28.5 | 253 | `{"j_threshold": 23, "min_conf_b1": 0.0, "pct_change_range": 5.0, "vol_mult_b2": 3.0}` |
| 2023-07-01~2023-12-31 | 13.2 | 159 | `{"j_threshold": 23, "min_conf_b1": 0.0, "pct_change_range": 7.0, "vol_mult_b2": 3.0}` |
| 2024-01-01~2024-06-30 | 25.4 | 122 | `{"j_threshold": 13, "min_conf_b1": 0.0, "pct_change_range": 5.0, "vol_mult_b2": 2.0}` |
| 2024-07-01~2024-12-31 | 35.6 | 202 | `{"j_threshold": 13, "min_conf_b1": 0.0, "pct_change_range": 5.0, "vol_mult_b2": 2.0}` |
| 2025-01-01~2025-06-30 | 27.2 | 268 | `{"j_threshold": 13, "min_conf_b1": 0.0, "pct_change_range": 5.0, "vol_mult_b2": 2.0}` |
| 2025-07-01~2025-12-31 | 31.8 | 365 | `{"j_threshold": 13, "min_conf_b1": 0.0, "pct_change_range": 5.0, "vol_mult_b2": 2.0}` |