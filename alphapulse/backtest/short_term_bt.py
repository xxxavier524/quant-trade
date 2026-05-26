"""Short-term backtest focused on post-buy N-day performance."""
import pandas as pd
import numpy as np
import logging
from .bt_storage import init_db, insert_signal, insert_daily_track, insert_exit
logger = logging.getLogger(__name__)

def run_short_backtest(signal_df, stock_data, max_hold_days=20, stop_loss_pct=-10.0):
    """Run short-term backtest on a set of signals.
    signal_df: [symbol, name, strategy, date, signal_type, buy_price, sector, macro_level, score, grade]
    stock_data: {symbol: DataFrame with date, close, high, low, volume}
    Returns dict of strategy-level stats.
    """
    init_db()
    all_stats = {}
    for strategy in signal_df["strategy"].unique():
        strat_signals = signal_df[signal_df["strategy"] == strategy]
        signals_tracked = []
        for _, sig in strat_signals.iterrows():
            symbol = sig["symbol"]
            if symbol not in stock_data: continue
            df = stock_data[symbol]
            signal_date = str(sig["date"])[:10]
            buy_price = sig.get("buy_price", 10.0)
            df_dates = df["date"].astype(str).str[:10]
            idx = df_dates[df_dates == signal_date].index
            if len(idx) == 0: continue
            start_idx = idx[0]

            sid = insert_signal(sig["symbol"], sig.get("name",""), strategy, signal_date,
                                sig.get("signal_type",""), buy_price, sig.get("sector",""),
                                sig.get("macro_level",""), sig.get("score",0), sig.get("grade",""))

            peak_price = buy_price; exit_idx = None; exit_reason = "hold_max"; tracked = []
            for day_n in range(1, max_hold_days + 1):
                cur_idx = start_idx + day_n
                if cur_idx >= len(df): exit_idx = len(df)-1; exit_reason="end_of_data"; break
                row = df.iloc[cur_idx]
                ret_pct = (row["close"]/buy_price-1)*100
                peak_price = max(peak_price, row["high"])
                dd_pct = (row["low"]/peak_price-1)*100
                insert_daily_track(sid, day_n, str(row["date"])[:10], row["close"], row["high"], row["low"],
                                   round(ret_pct,4), round(dd_pct,4))
                tracked.append({"day_n": day_n, "return_pct": ret_pct, "drawdown_pct": dd_pct})
                if dd_pct <= stop_loss_pct: exit_idx=cur_idx; exit_reason="stop_loss"; break

            if exit_idx is None:
                exit_idx = start_idx + max_hold_days
                if exit_idx >= len(df): exit_idx = len(df)-1; exit_reason="end_of_data"
            total_return = (df.iloc[exit_idx]["close"]/buy_price-1)*100
            hold_days = exit_idx - start_idx
            insert_exit(sid, str(df.iloc[exit_idx]["date"])[:10], df.iloc[exit_idx]["close"],
                        exit_reason, round(total_return,4), hold_days)
            signals_tracked.append({"symbol": symbol, "buy_date": signal_date, "total_return": round(total_return,2),
                                    "hold_days": hold_days, "exit_reason": exit_reason})

        returns = [s["total_return"] for s in signals_tracked]
        win = [r for r in returns if r > 0]
        all_stats[strategy] = {"total_signals": len(signals_tracked),
            "win_rate": round(len(win)/len(returns)*100, 1) if returns else 0,
            "avg_return": round(np.mean(returns), 2) if returns else 0,
            "avg_hold_days": round(np.mean([s["hold_days"] for s in signals_tracked]), 1),
            "signals": signals_tracked} if signals_tracked else {"total_signals": 0, "win_rate": 0}
    return all_stats
