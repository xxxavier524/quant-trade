"""Experimental quantitative factors from brokerage research.

Factors sourced from:
- 中金公司 (CICC): XGBoost factor screening, 220-factor system
- 华泰证券 (HTSC): Analyst revision, genetic programming factors
- 国泰君安 (GTJA): Earnings surprise, volatility factors
- 广发证券 (GF Securities): North-bound capital 2.0
- 东海证券: Capital flow big-order
- Academic: Fama-French, Barra CNE5/CNE6, IVOL puzzle
"""

from alphapulse.factors.experimental import (
    northbound_capital_flow,
    idiosyncratic_vol,
    turnover_uniformity,
    analyst_revision,
    capital_flow_big_order,
)

__all__ = [
    "northbound_capital_flow",
    "idiosyncratic_vol",
    "turnover_uniformity",
    "analyst_revision",
    "capital_flow_big_order",
]
