"""Shared data loaders and backtesting engine for web and desktop interfaces."""
from __future__ import annotations

import numpy as np
import pandas as pd
import requests
import yfinance as yf

BINANCE_KLINES = "https://api.binance.com/api/v3/klines"


def load_binance(symbol: str, interval: str, limit: int) -> pd.DataFrame:
    """Fetch public OHLCV candles from Binance; no API key is required."""
    response = requests.get(
        BINANCE_KLINES,
        params={"symbol": symbol.upper(), "interval": interval, "limit": min(limit, 1000)},
        timeout=15,
    )
    response.raise_for_status()
    rows = response.json()
    if not rows:
        raise ValueError("Binance returned no candles for this symbol/interval.")
    columns = [
        "open_time", "Open", "High", "Low", "Close", "Volume", "close_time",
        "quote_volume", "trades", "taker_buy_base", "taker_buy_quote", "ignore",
    ]
    df = pd.DataFrame(rows, columns=columns)
    df["Date"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    for col in ["Open", "High", "Low", "Close", "Volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.set_index("Date")[["Open", "High", "Low", "Close", "Volume"]].dropna()


def load_yahoo(ticker: str, period: str, interval: str) -> pd.DataFrame:
    """Fetch free Yahoo Finance data. Intraday availability and delay vary by ticker."""
    df = yf.download(
        ticker,
        period=period,
        interval=interval,
        auto_adjust=False,
        progress=False,
        threads=False,
    )
    if df is None or df.empty:
        raise ValueError(
            "Yahoo Finance returned no data. Try another ticker or a supported period/interval."
        )
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    wanted = ["Open", "High", "Low", "Close", "Volume"]
    df = df[[c for c in wanted if c in df.columns]].copy()
    df.index = pd.to_datetime(df.index)
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    else:
        df.index = df.index.tz_convert("UTC")
    return df.dropna(subset=["Open", "High", "Low", "Close"])


def load_csv(upload) -> pd.DataFrame:
    df = pd.read_csv(upload)
    date_col = next((c for c in df.columns if c.lower() in {"date", "datetime", "timestamp", "time"}), None)
    if date_col is None:
        raise ValueError("CSV must contain a Date, Datetime, Timestamp, or Time column.")
    mapping = {c.lower(): c for c in df.columns}
    required = ["open", "high", "low", "close"]
    if not all(c in mapping for c in required):
        raise ValueError("CSV must contain Open, High, Low, and Close columns.")
    df = df.rename(columns={mapping[c]: c.title() for c in required})
    df["Date"] = pd.to_datetime(df[date_col], utc=True, errors="coerce")
    if "Volume" not in df.columns and "volume" in mapping:
        df["Volume"] = df[mapping["volume"]]
    if "Volume" not in df.columns:
        df["Volume"] = 0.0
    for col in ["Open", "High", "Low", "Close", "Volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.dropna(subset=["Date", "Open", "High", "Low", "Close"]).set_index("Date")[
        ["Open", "High", "Low", "Close", "Volume"]
    ].sort_index()


def run_backtest(data: pd.DataFrame, fast: int, slow: int, starting_cash: float,
                 fee_pct: float, slippage_pct: float, allow_short: bool) -> tuple[pd.DataFrame, dict, pd.DataFrame]:
    if fast >= slow:
        raise ValueError("The fast moving average must be smaller than the slow moving average.")
    df = data.copy().sort_index()
    df = df[~df.index.duplicated(keep="last")]
    df["Fast MA"] = df["Close"].rolling(fast, min_periods=fast).mean()
    df["Slow MA"] = df["Close"].rolling(slow, min_periods=slow).mean()
    raw = np.where(df["Fast MA"] > df["Slow MA"], 1, 0)
    if allow_short:
        raw = np.where(df["Fast MA"] < df["Slow MA"], -1, raw)
    df["Signal"] = raw
    # Shift by one candle so a signal calculated at a candle close cannot earn that same candle's return.
    df["Position"] = df["Signal"].shift(1).fillna(0)
    df["Market Return"] = df["Close"].pct_change().fillna(0)
    turnover = df["Position"].diff().abs().fillna(df["Position"].abs())
    friction = (fee_pct + slippage_pct) / 100.0
    df["Strategy Return"] = df["Position"] * df["Market Return"] - turnover * friction
    df["Equity"] = starting_cash * (1 + df["Strategy Return"]).cumprod()
    df["Buy & Hold"] = starting_cash * (1 + df["Market Return"]).cumprod()
    df["Peak"] = df["Equity"].cummax()
    df["Drawdown"] = df["Equity"] / df["Peak"] - 1

    valid = df["Strategy Return"].dropna()
    total_return = (df["Equity"].iloc[-1] / starting_cash - 1) * 100 if len(df) else 0.0
    max_dd = df["Drawdown"].min() * 100 if len(df) else 0.0
    periods = max(len(valid), 1)
    # Annualization is an approximation; actual periods per year depend on the selected timeframe.
    sharpe = 0.0
    if valid.std(ddof=1) and np.isfinite(valid.std(ddof=1)):
        sharpe = float(valid.mean() / valid.std(ddof=1) * np.sqrt(252))
    changes = df["Position"].diff().fillna(df["Position"]).ne(0)
    trades_count = int(changes.sum())
    gains = valid[valid > 0].sum()
    losses = abs(valid[valid < 0].sum())
    profit_factor = float(gains / losses) if losses > 0 else (float("inf") if gains > 0 else 0.0)
    metrics = {
        "Final equity": float(df["Equity"].iloc[-1]) if len(df) else starting_cash,
        "Total return (%)": float(total_return),
        "Max drawdown (%)": float(max_dd),
        "Sharpe (approx.)": float(sharpe),
        "Position changes": trades_count,
        "Profit factor (bar-based)": profit_factor,
        "Buy & hold return (%)": float((df["Buy & Hold"].iloc[-1] / starting_cash - 1) * 100) if len(df) else 0.0,
    }

    # Approximate completed trade list: returns accumulated during each non-flat position run.
    groups = (df["Position"] != df["Position"].shift()).cumsum()
    trade_rows = []
    for _, segment in df[df["Position"] != 0].groupby(groups[df["Position"] != 0]):
        trade_return = (1 + segment["Strategy Return"]).prod() - 1
        trade_rows.append({
            "Entry time": segment.index[0],
            "Exit time": segment.index[-1],
            "Side": "Long" if segment["Position"].iloc[0] > 0 else "Short",
            "Bars": len(segment),
            "Return (%)": round(float(trade_return * 100), 3),
        })
    trades = pd.DataFrame(trade_rows)
    return df, metrics, trades


