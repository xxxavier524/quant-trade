# Walk-Forward 报告 — BRICK_THREE_TYPES

样本 792 只（seed=42）| 36 组参数 × 8 验证窗 | 口径: 信号后5个交易日内最高收盘 ≥ +5%

## 稳健参数 Top 10（0.5×中位窗 + 0.5×最差窗）

| # | robust | 中位 | 最差 | 最好 | 有效窗 | 总信号 | 参数 |
|---|---|---|---|---|---|---|---|
| 1 | 0.239 | 0.260 | 0.218 | 0.576 | 8 | 11995 | `{"vol_mult_n_jump": 1.3, "vol_mult_breakout": 1.5, "consol_lookback": 5, "consol_max_amplitude": 15}` |
| 2 | 0.239 | 0.260 | 0.218 | 0.576 | 8 | 11995 | `{"vol_mult_n_jump": 1.5, "vol_mult_breakout": 1.5, "consol_lookback": 5, "consol_max_amplitude": 15}` |
| 3 | 0.239 | 0.260 | 0.218 | 0.576 | 8 | 11995 | `{"vol_mult_n_jump": 2.0, "vol_mult_breakout": 1.5, "consol_lookback": 5, "consol_max_amplitude": 15}` |
| 4 | 0.231 | 0.256 | 0.207 | 0.577 | 8 | 12227 | `{"vol_mult_n_jump": 1.3, "vol_mult_breakout": 1.5, "consol_lookback": 3, "consol_max_amplitude": 15}` |
| 5 | 0.231 | 0.256 | 0.207 | 0.577 | 8 | 12227 | `{"vol_mult_n_jump": 1.5, "vol_mult_breakout": 1.5, "consol_lookback": 3, "consol_max_amplitude": 15}` |
| 6 | 0.231 | 0.256 | 0.207 | 0.577 | 8 | 12227 | `{"vol_mult_n_jump": 2.0, "vol_mult_breakout": 1.5, "consol_lookback": 3, "consol_max_amplitude": 15}` |
| 7 | 0.230 | 0.252 | 0.207 | 0.573 | 8 | 14030 | `{"vol_mult_n_jump": 1.3, "vol_mult_breakout": 1.3, "consol_lookback": 5, "consol_max_amplitude": 15}` |
| 8 | 0.230 | 0.252 | 0.207 | 0.573 | 8 | 14030 | `{"vol_mult_n_jump": 1.5, "vol_mult_breakout": 1.3, "consol_lookback": 5, "consol_max_amplitude": 15}` |
| 9 | 0.230 | 0.252 | 0.207 | 0.573 | 8 | 14030 | `{"vol_mult_n_jump": 2.0, "vol_mult_breakout": 1.3, "consol_lookback": 5, "consol_max_amplitude": 15}` |
| 10 | 0.224 | 0.252 | 0.196 | 0.576 | 8 | 14469 | `{"vol_mult_n_jump": 1.3, "vol_mult_breakout": 1.3, "consol_lookback": 3, "consol_max_amplitude": 15}` |

## 链式流程回测（每窗只用之前窗口的信息选参 → 该窗样本外成功率）

| 验证窗 | 样本外成功率 | 信号数 | 当时选中参数 |
|---|---|---|---|
| 2022-07-01~2022-12-31 | — | 0 | `—` |
| 2023-01-01~2023-06-30 | 24.5% | 1805 | `{"consol_lookback": 3, "consol_max_amplitude": 15, "vol_mult_breakout": 1.5, "vol_mult_n_jump": 1.3}` |
| 2023-07-01~2023-12-31 | 20.6% | 1254 | `{"consol_lookback": 3, "consol_max_amplitude": 15, "vol_mult_breakout": 1.5, "vol_mult_n_jump": 1.3}` |
| 2024-01-01~2024-06-30 | 25.5% | 920 | `{"consol_lookback": 5, "consol_max_amplitude": 15, "vol_mult_breakout": 1.5, "vol_mult_n_jump": 1.3}` |
| 2024-07-01~2024-12-31 | 57.6% | 1584 | `{"consol_lookback": 5, "consol_max_amplitude": 15, "vol_mult_breakout": 1.5, "vol_mult_n_jump": 1.3}` |
| 2025-01-01~2025-06-30 | 27.0% | 1575 | `{"consol_lookback": 5, "consol_max_amplitude": 15, "vol_mult_breakout": 1.5, "vol_mult_n_jump": 1.3}` |
| 2025-07-01~2025-12-31 | 26.9% | 2221 | `{"consol_lookback": 5, "consol_max_amplitude": 15, "vol_mult_breakout": 1.5, "vol_mult_n_jump": 1.3}` |

**流程期望**: 链式样本外成功率 中位 26.2% / 最差 20.6%（这是该选参流程实盘可期待的无偏估计）