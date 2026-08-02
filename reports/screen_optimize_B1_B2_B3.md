# 纯选股成功率优化 — B1_B2_B3

样本 594 只 | 54 组参数 × 8 窗 | 口径: 信号后5日内收盘≥+5%（机会命中）
 | 稳健分 = 0.5×中位窗 + 0.5×最差窗；基线 = 同窗全体股票命中率

## Top 10（按稳健分）

| # | 稳健% | 中位% | 最差% | 基线中位% | 超额pp | 有效窗 | 总信号 | 参数 |
|---|---|---|---|---|---|---|---|---|
| 1 | 21.8 | 26.3 | 17.3 | 20.1 | +1.7 | 8 | 3585 | `{"j_threshold": 23, "pct_change_range": 3.0, "vol_mult_b2": 1.5, "min_conf_b1": 0.7}` |
| 2 | 21.7 | 26.0 | 17.4 | 20.2 | +1.5 | 8 | 3872 | `{"j_threshold": 23, "pct_change_range": 7.0, "vol_mult_b2": 1.5, "min_conf_b1": 0.7}` |
| 3 | 21.7 | 25.9 | 17.4 | 20.0 | +1.6 | 8 | 3829 | `{"j_threshold": 23, "pct_change_range": 5.0, "vol_mult_b2": 1.5, "min_conf_b1": 0.7}` |
| 4 | 21.6 | 26.3 | 16.9 | 20.2 | +1.4 | 8 | 3414 | `{"j_threshold": 18, "pct_change_range": 7.0, "vol_mult_b2": 1.5, "min_conf_b1": 0.7}` |
| 5 | 21.6 | 27.2 | 15.9 | 20.0 | +1.5 | 8 | 2972 | `{"j_threshold": 13, "pct_change_range": 7.0, "vol_mult_b2": 1.5, "min_conf_b1": 0.7}` |
| 6 | 21.5 | 26.1 | 16.9 | 19.9 | +1.6 | 8 | 3378 | `{"j_threshold": 18, "pct_change_range": 5.0, "vol_mult_b2": 1.5, "min_conf_b1": 0.7}` |
| 7 | 21.5 | 27.1 | 15.9 | 19.8 | +1.7 | 8 | 2936 | `{"j_threshold": 13, "pct_change_range": 5.0, "vol_mult_b2": 1.5, "min_conf_b1": 0.7}` |
| 8 | 21.2 | 26.0 | 16.4 | 20.0 | +1.2 | 8 | 3153 | `{"j_threshold": 18, "pct_change_range": 3.0, "vol_mult_b2": 1.5, "min_conf_b1": 0.7}` |
| 9 | 21.0 | 26.4 | 15.5 | 20.0 | +1.0 | 8 | 2736 | `{"j_threshold": 13, "pct_change_range": 3.0, "vol_mult_b2": 1.5, "min_conf_b1": 0.7}` |
| 10 | 20.9 | 27.4 | 14.3 | 20.6 | +0.2 | 7 | 2520 | `{"j_threshold": 23, "pct_change_range": 7.0, "vol_mult_b2": 2.0, "min_conf_b1": 0.7}` |

## 链式流程回测（每窗只用之前窗口信息选参）

| 验证窗 | 样本外成功率% | 信号数 | 当时选中参数 |
|---|---|---|---|
| 2022-07-01~2022-12-31 | — | 0 | `—` |
| 2023-01-01~2023-06-30 | 24.1 | 503 | `{"j_threshold": 23, "min_conf_b1": 0.7, "pct_change_range": 7.0, "vol_mult_b2": 2.0}` |
| 2023-07-01~2023-12-31 | 13.0 | 215 | `{"j_threshold": 23, "min_conf_b1": 0.7, "pct_change_range": 7.0, "vol_mult_b2": 3.0}` |
| 2024-01-01~2024-06-30 | 25.3 | 170 | `{"j_threshold": 23, "min_conf_b1": 0.7, "pct_change_range": 7.0, "vol_mult_b2": 1.5}` |
| 2024-07-01~2024-12-31 | 35.6 | 396 | `{"j_threshold": 18, "min_conf_b1": 0.7, "pct_change_range": 5.0, "vol_mult_b2": 1.5}` |
| 2025-01-01~2025-06-30 | 29.3 | 481 | `{"j_threshold": 18, "min_conf_b1": 0.7, "pct_change_range": 7.0, "vol_mult_b2": 1.5}` |
| 2025-07-01~2025-12-31 | 28.1 | 623 | `{"j_threshold": 18, "min_conf_b1": 0.7, "pct_change_range": 7.0, "vol_mult_b2": 1.5}` |
