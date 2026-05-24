"""因子评分器：LightGBM模型用于因子组合和综合评分。

使用FACTOR_REGISTRY中的core类型因子作为特征，
用LightGBM训练对未来5日收益率的预测模型。
"""

import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler

from alphapulse.factors.factor_registry import FACTOR_REGISTRY, compute_factor


def _get_core_factor_names() -> list[str]:
    """获取所有type='core'的因子名称列表。"""
    return sorted([
        name for name, entry in FACTOR_REGISTRY.items()
        if entry.get("type") == "core"
    ])


class FactorScorer:
    """LightGBM因子评分器。

    用core类型因子作为特征，训练LightGBM回归模型预测股票未来5日收益率，
    输出综合评分用于排名选股。
    """

    def __init__(self):
        self.model = None
        self.factors: list[str] = []
        self.feature_names: list[str] = []
        self.feature_importance: dict[str, float] = {}
        self.scaler = StandardScaler()
        self._scaler_fitted = False

    def prepare_features(
        self,
        data_dict: dict[str, pd.DataFrame],
    ) -> tuple[pd.DataFrame, pd.Series, list[str]]:
        """对每只股票计算所有core因子值，构建特征矩阵X和标签y。

        对每只股票：
          - 计算所有core类型因子（shift(1)避免未来数据）
          - 标签 = 未来5日收益率: close.shift(-5) / close - 1
          - 取最后一条同时有因子值和标签的行

        Args:
            data_dict: symbol -> DataFrame (OHLCV, DatetimeIndex排序)

        Returns:
            X: pd.DataFrame (n_stocks x n_features)，因子特征
            y: pd.Series (n_stocks)，未来5日收益率
            symbols: 股票代码列表
        """
        if not self.factors:
            self.factors = _get_core_factor_names()

        rows = []
        labels = []
        symbols_out = []

        for symbol, df in data_dict.items():
            if len(df) < 50:  # 最少需要50个交易日
                continue

            try:
                factor_series = {}
                for fname in self.factors:
                    # 计算因子（每个bar都计算，对齐data.index）
                    result = compute_factor(fname, df)

                    if isinstance(result, pd.DataFrame):
                        # 多列输出（如wave_identifier），拆分为独立特征
                        for col in result.columns:
                            col_name = f"{fname}__{col}"
                            series_val = result[col].shift(1)  # 防未来数据
                            # 转换为float以便模型处理
                            factor_series[col_name] = series_val.astype(float)
                    else:
                        series_val = result.shift(1)  # 防未来数据
                        # bool -> float (True=1.0, False=0.0)
                        if series_val.dtype == bool:
                            factor_series[fname] = series_val.astype(float)
                        else:
                            factor_series[fname] = series_val.astype(float)

                # 标签: 未来5日收益率
                close = df["close"]
                label = close.shift(-5) / close - 1.0

                # 构建DataFrame，丢弃NaN行
                feat_df = pd.DataFrame(factor_series, index=df.index)
                valid = feat_df.notna().all(axis=1) & label.notna()

                if not valid.any():
                    continue

                # 取最后一个有效行（最新交易日）
                last_valid_idx = valid[valid].index[-1]
                row = feat_df.loc[last_valid_idx].values
                lab = label.loc[last_valid_idx]

                rows.append(row)
                labels.append(lab)
                symbols_out.append(symbol)

                # 记录特征名称（只需记录一次）
                if not self.feature_names and rows:
                    self.feature_names = list(feat_df.columns)

            except Exception:
                continue

        if not rows:
            raise ValueError("没有有效样本：所有股票的因子/标签均为NaN")

        X = pd.DataFrame(np.array(rows), index=symbols_out, columns=self.feature_names)
        y = pd.Series(np.array(labels), index=symbols_out, name="fwd_5d_return")

        return X, y, symbols_out

    def train(self, X: pd.DataFrame, y: pd.Series) -> dict:
        """训练LightGBM回归模型。

        LightGBM参数: n_estimators=200, max_depth=5, learning_rate=0.05
        早停: early_stopping_rounds=20
        验证集比例: 20%

        Args:
            X: 特征矩阵 (n_samples x n_features)
            y: 标签 (n_samples)

        Returns:
            dict: 训练结果 {'train_r2': ..., 'val_r2': ..., 'val_spearman': ...}
        """
        import lightgbm as lgb
        from sklearn.model_selection import train_test_split
        from scipy.stats import spearmanr

        # Z-score标准化
        if not self._scaler_fitted:
            X_scaled = self.scaler.fit_transform(X)
            self._scaler_fitted = True
        else:
            X_scaled = self.scaler.transform(X)

        # 划分训练/验证集
        X_train, X_val, y_train, y_val = train_test_split(
            X_scaled, y.values, test_size=0.2, random_state=42,
        )

        # LightGBM参数
        params = {
            "objective": "regression",
            "metric": "l2",
            "n_estimators": 200,
            "max_depth": 5,
            "learning_rate": 0.05,
            "num_leaves": 31,
            "verbosity": -1,
            "random_state": 42,
            "force_row_wise": True,
        }

        callbacks = [
            lgb.early_stopping(stopping_rounds=20, verbose=False),
            lgb.log_evaluation(period=0),
        ]

        self.model = lgb.LGBMRegressor(**params)
        self.model.fit(
            X_train, y_train,
            eval_set=[(X_val, y_val)],
            eval_metric="l2",
            callbacks=callbacks,
        )

        # 特征重要性
        importances = self.model.feature_importances_
        self.feature_importance = dict(
            sorted(
                zip(self.feature_names, importances),
                key=lambda x: x[1], reverse=True,
            )
        )

        # 训练/验证集性能
        y_train_pred = self.model.predict(X_train)
        y_val_pred = self.model.predict(X_val)

        train_r2 = 1 - np.sum((y_train - y_train_pred) ** 2) / np.sum(
            (y_train - y_train.mean()) ** 2
        )
        val_r2 = 1 - np.sum((y_val - y_val_pred) ** 2) / np.sum(
            (y_val - y_val.mean()) ** 2
        )
        val_spearman, _ = spearmanr(y_val, y_val_pred)

        return {
            "train_r2": train_r2,
            "val_r2": val_r2,
            "val_spearman": val_spearman,
            "n_samples": len(X),
            "n_features": len(self.feature_names),
        }

    def predict(self, data_dict: dict[str, pd.DataFrame]) -> pd.DataFrame:
        """预测所有股票的因子综合评分。

        使用训练好的LightGBM模型预测每只股票的未来收益，
        按预测分数降序排列。

        Args:
            data_dict: symbol -> DataFrame (OHLCV, DatetimeIndex排序)

        Returns:
            pd.DataFrame: [symbol, score, top_factors]
                score = 模型预测的未来收益（分数越高越好）
        """
        if self.model is None:
            raise RuntimeError("模型尚未训练，请先调用train()")

        X, _, symbols = self.prepare_features(data_dict)

        if len(X) == 0:
            return pd.DataFrame(columns=["symbol", "score", "top_factors"])

        X_scaled = self.scaler.transform(X)
        scores = self.model.predict(X_scaled)

        # 获取每只股票的Top 3因子贡献
        top3_factors = []
        if self.feature_importance:
            # 获取最重要的3个因子名称
            top3_names = list(self.feature_importance.keys())[:3]
            X_df = pd.DataFrame(X_scaled, index=symbols, columns=self.feature_names)
            for sym in symbols:
                row = X_df.loc[sym]
                top_vals = row[top3_names].abs().sort_values(ascending=False)
                factor_str = ", ".join(
                    f"{name}={val:.2f}" for name, val in top_vals.items()
                )
                top3_factors.append(factor_str)
        else:
            top3_factors = [""] * len(symbols)

        result = pd.DataFrame({
            "symbol": symbols,
            "score": scores,
            "top_factors": top3_factors,
        })
        result = result.sort_values("score", ascending=False).reset_index(drop=True)

        return result

    def get_top_factors(self, n: int = 10) -> list[tuple[str, float]]:
        """返回重要性最高的n个因子。

        Args:
            n: 返回因子数量

        Returns:
            list[(factor_name, importance)]
        """
        return list(self.feature_importance.items())[:n]
