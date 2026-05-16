"""因子预处理流水线。

规格书4.3节：MAD去极值 → 缺失值填充 → Z-Score标准化 → 行业中性化(可选)
"""

import pandas as pd
import numpy as np


def mad_winsorize(series: pd.Series, n: float = 3.0) -> pd.Series:
    """MAD法去极值。

    MAD = median(|x - median|) * 1.4826（正态分布一致性因子）
    将超出 median ± n * MAD 的值截断。
    """
    median = series.median()
    mad = (series - median).abs().median() * 1.4826
    if mad == 0:
        return series
    upper = median + n * mad
    lower = median - n * mad
    return series.clip(lower, upper)


def z_score_normalize(series: pd.Series) -> pd.Series:
    """Z-Score标准化。"""
    std = series.std()
    if std == 0:
        return series - series.mean()
    return (series - series.mean()) / std


def fill_by_industry_mean(
    factor_df: pd.DataFrame,
    industry_map: dict | None = None,
) -> pd.DataFrame:
    """按行业均值填充缺失值。

    Args:
        factor_df: 行为股票代码，列为因子名
        industry_map: {symbol: industry_name} 或 None（用全市场均值）
    """
    filled = factor_df.copy()

    if industry_map is None or len(industry_map) == 0:
        return filled.fillna(filled.mean())

    for col in filled.columns:
        for industry in set(industry_map.values()):
            mask = pd.Series(
                [industry_map.get(str(idx), "") == industry for idx in filled.index],
                index=filled.index,
            )
            if mask.any():
                ind_mean = filled.loc[mask, col].mean()
                if not pd.isna(ind_mean):
                    filled.loc[mask & filled[col].isna(), col] = ind_mean

        # 仍缺失的，用全市场均值
        filled[col] = filled[col].fillna(filled[col].mean())

    return filled


def industry_neutralize(
    factor_df: pd.DataFrame,
    industry_map: dict,
) -> pd.DataFrame:
    """行业中性化：回归去除行业暴露。

    对每个因子做行业虚拟变量回归，取残差作为中性化后的因子值。
    """
    from sklearn.linear_model import LinearRegression

    industries = list(set(industry_map.values()))
    if len(industries) <= 1:
        return factor_df

    industry_dummies = pd.get_dummies(
        [industry_map.get(str(idx), "未知") for idx in factor_df.index]
    )
    industry_dummies.index = factor_df.index

    neutralized = factor_df.copy()
    for col in factor_df.columns:
        valid = factor_df[col].notna()
        if valid.sum() < len(industries) + 5:
            continue
        X = industry_dummies.loc[valid].values
        y = factor_df.loc[valid, col].values
        model = LinearRegression()
        model.fit(X, y)
        predicted = model.predict(industry_dummies.values)
        neutralized[col] = factor_df[col] - predicted

    return neutralized


def preprocess_factors(
    factor_df: pd.DataFrame,
    industry_map: dict | None = None,
    neutralize: bool = False,
    n_mad: float = 3.0,
) -> pd.DataFrame:
    """因子预处理主函数。

    Args:
        factor_df: 原始因子矩阵（行为股票，列为因子）
        industry_map: {symbol: industry} 映射
        neutralize: 是否行业中性化
        n_mad: MAD倍数

    Returns:
        预处理后的因子矩阵
    """
    processed = factor_df.copy()

    # Step 1 & 3: 对每列先MAD去极值再Z-Score
    for col in processed.columns:
        processed[col] = mad_winsorize(processed[col], n=n_mad)
        processed[col] = z_score_normalize(processed[col])

    # Step 2: 行业均值填充缺失值
    processed = fill_by_industry_mean(processed, industry_map)

    # Step 4: 行业中性化（可选）
    if neutralize and industry_map is not None and len(set(industry_map.values())) > 1:
        processed = industry_neutralize(processed, industry_map)

    return processed
