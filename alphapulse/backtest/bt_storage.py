"""SQLite storage for short-term backtest results."""
import sqlite3
import pandas as pd
from pathlib import Path

DB_PATH = Path("backtest_results/short_term.db")

def get_conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL, name TEXT, strategy TEXT NOT NULL,
            signal_date TEXT NOT NULL, signal_type TEXT, buy_price REAL,
            sector TEXT, macro_level TEXT, score REAL, grade TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE IF NOT EXISTS daily_track (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            signal_id INTEGER NOT NULL REFERENCES signals(id),
            day_n INTEGER NOT NULL, trade_date TEXT NOT NULL,
            close REAL, high REAL, low REAL,
            return_pct REAL, drawdown_pct REAL,
            UNIQUE(signal_id, day_n)
        );
        CREATE TABLE IF NOT EXISTS exits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            signal_id INTEGER NOT NULL REFERENCES signals(id),
            exit_date TEXT NOT NULL, exit_price REAL,
            exit_reason TEXT, total_return REAL, hold_days INTEGER,
            UNIQUE(signal_id)
        );
        CREATE INDEX IF NOT EXISTS idx_signals_strategy ON signals(strategy);
        CREATE INDEX IF NOT EXISTS idx_signals_date ON signals(signal_date);
        CREATE INDEX IF NOT EXISTS idx_track_signal ON daily_track(signal_id);
    """)
    conn.commit(); conn.close()

def insert_signal(symbol, name, strategy, signal_date, signal_type, buy_price, sector, macro_level, score, grade):
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO signals (symbol,name,strategy,signal_date,signal_type,buy_price,sector,macro_level,score,grade) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        (symbol,name,strategy,signal_date,signal_type,buy_price,sector,macro_level,score,grade))
    conn.commit(); sid = cur.lastrowid; conn.close(); return sid

def insert_daily_track(signal_id, day_n, trade_date, close, high, low, return_pct, drawdown_pct):
    conn = get_conn()
    conn.execute("INSERT OR REPLACE INTO daily_track VALUES (NULL,?,?,?,?,?,?,?,?)",
                 (signal_id, day_n, trade_date, close, high, low, return_pct, drawdown_pct))
    conn.commit(); conn.close()

def insert_exit(signal_id, exit_date, exit_price, exit_reason, total_return, hold_days):
    conn = get_conn()
    conn.execute("INSERT OR REPLACE INTO exits VALUES (NULL,?,?,?,?,?,?)",
                 (signal_id, exit_date, exit_price, exit_reason, total_return, hold_days))
    conn.commit(); conn.close()

def query_strategy_stats(strategy, start_date=None, end_date=None):
    conn = get_conn()
    q = "SELECT s.*, e.exit_date, e.exit_price, e.exit_reason, e.total_return, e.hold_days FROM signals s LEFT JOIN exits e ON s.id=e.signal_id WHERE s.strategy=?"
    params = [strategy]
    if start_date: q += " AND s.signal_date>=?"; params.append(start_date)
    if end_date: q += " AND s.signal_date<=?"; params.append(end_date)
    q += " ORDER BY s.signal_date DESC"
    df = pd.read_sql_query(q, conn, params=params); conn.close(); return df

def query_daily_track(signal_id):
    conn = get_conn()
    df = pd.read_sql_query("SELECT * FROM daily_track WHERE signal_id=? ORDER BY day_n", conn, params=[signal_id])
    conn.close(); return df
