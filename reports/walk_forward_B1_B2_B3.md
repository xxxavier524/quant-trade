# Walk-Forward 报告 — B1_B2_B3

样本 792 只（seed=42）| 54 组参数 × 8 验证窗 | 口径: 信号后5个交易日内最高收盘 ≥ +5%

## 稳健参数 Top 10（0.5×中位窗 + 0.5×最差窗）

| # | robust | 中位 | 最差 | 最好 | 有效窗 | 总信号 | 参数 |
|---|---|---|---|---|---|---|---|
| 1 | 0.212 | 0.240 | 0.183 | 0.397 | 8 | 5007 | `{"j_threshold": 23, "pct_change_range": 7.0, "vol_mult_b2": 1.5, "min_conf_b1": 0.7}` |
| 2 | 0.210 | 0.237 | 0.182 | 0.392 | 8 | 4947 | `{"j_threshold": 23, "pct_change_range": 5.0, "vol_mult_b2": 1.5, "min_conf_b1": 0.7}` |
| 3 | 0.207 | 0.226 | 0.187 | 0.396 | 8 | 3774 | `{"j_threshold": 13, "pct_change_range": 7.0, "vol_mult_b2": 1.5, "min_conf_b1": 0.7}` |
| 4 | 0.207 | 0.236 | 0.177 | 0.394 | 8 | 4409 | `{"j_threshold": 18, "pct_change_range": 7.0, "vol_mult_b2": 1.5, "min_conf_b1": 0.7}` |
| 5 | 0.205 | 0.235 | 0.175 | 0.386 | 8 | 4357 | `{"j_threshold": 18, "pct_change_range": 5.0, "vol_mult_b2": 1.5, "min_conf_b1": 0.7}` |
| 6 | 0.205 | 0.224 | 0.185 | 0.386 | 8 | 3728 | `{"j_threshold": 13, "pct_change_range": 5.0, "vol_mult_b2": 1.5, "min_conf_b1": 0.7}` |
| 7 | 0.204 | 0.234 | 0.175 | 0.422 | 8 | 3510 | `{"j_threshold": 23, "pct_change_range": 7.0, "vol_mult_b2": 2.0, "min_conf_b1": 0.7}` |
| 8 | 0.204 | 0.232 | 0.175 | 0.374 | 8 | 4541 | `{"j_threshold": 23, "pct_change_range": 3.0, "vol_mult_b2": 1.5, "min_conf_b1": 0.7}` |
| 9 | 0.203 | 0.233 | 0.173 | 0.420 | 8 | 3482 | `{"j_threshold": 23, "pct_change_range": 5.0, "vol_mult_b2": 2.0, "min_conf_b1": 0.7}` |
| 10 | 0.203 | 0.226 | 0.181 | 0.378 | 8 | 3404 | `{"j_threshold": 13, "pct_change_range": 3.0, "vol_mult_b2": 1.5, "min_conf_b1": 0.7}` |

## 链式流程回测（每窗只用之前窗口的信息选参 → 该窗样本外成功率）

| 验证窗 | 样本外成功率 | 信号数 | 当时选中参数 |
|---|---|---|---|
| 2022-07-01~2022-12-31 | — | 0 | `—` |
| 2023-01-01~2023-06-30 | 22.7% | 867 | `{"j_threshold": 23, "min_conf_b1": 0.7, "pct_change_range": 7.0, "vol_mult_b2": 1.5}` |
| 2023-07-01~2023-12-31 | 17.7% | 571 | `{"j_threshold": 18, "min_conf_b1": 0.7, "pct_change_range": 7.0, "vol_mult_b2": 1.5}` |
| 2024-01-01~2024-06-30 | 20.9% | 273 | `{"j_threshold": 23, "min_conf_b1": 0.7, "pct_change_range": 7.0, "vol_mult_b2": 1.5}` |
| 2024-07-01~2024-12-31 | 39.7% | 594 | `{"j_threshold": 23, "min_conf_b1": 0.7, "pct_change_range": 7.0, "vol_mult_b2": 1.5}` |
| 2025-01-01~2025-06-30 | 25.3% | 637 | `{"j_threshold": 23, "min_conf_b1": 0.7, "pct_change_range": 7.0, "vol_mult_b2": 1.5}` |
| 2025-07-01~2025-12-31 | 28.6% | 955 | `{"j_threshold": 23, "min_conf_b1": 0.7, "pct_change_range": 7.0, "vol_mult_b2": 1.5}` |

**流程期望**: 链式样本外成功率 中位 24.0% / 最差 17.7%（这是该选参流程实盘可期待的无偏估计）