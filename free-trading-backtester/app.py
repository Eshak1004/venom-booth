from __future__ import annotations

from datetime import datetime, timezone
from io import StringIO
import time

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st
import yfinance as yf

st.set_page_config(page_title="Venom Backtester", page_icon="📈", layout="wide")

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


st.title("Venom Backtester")
st.caption("A free, open-source-style research tool for historical testing and near-real-time market data. Paper research only — not a broker or execution platform.")

with st.sidebar:
    st.header("1. Market data")
    source = st.selectbox("Data source", ["Binance (crypto)", "Yahoo Finance (stocks / gold)", "Upload CSV"])
    refresh = st.toggle("Auto-refresh data every 60 seconds", value=False)
    if source == "Binance (crypto)":
        symbol = st.text_input("Binance symbol", "BTCUSDT").strip().upper()
        interval = st.selectbox("Candle interval", ["1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "1d"], index=3)
        limit = st.slider("Candles to load (max 1,000)", 100, 1000, 500, 100)
    elif source == "Yahoo Finance (stocks / gold)":
        ticker = st.text_input("Yahoo ticker", "GC=F").strip()
        period = st.selectbox("Historical period", ["1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y"], index=4)
        interval = st.selectbox("Candle interval", ["1m", "2m", "5m", "15m", "30m", "60m", "1d", "1wk"], index=3)
    else:
        uploaded = st.file_uploader("Upload OHLCV CSV", type=["csv"])
        st.caption("Required columns: Date, Open, High, Low, Close. Volume is optional.")

    st.header("2. Strategy")
    fast = st.number_input("Fast SMA", min_value=2, max_value=200, value=10, step=1)
    slow = st.number_input("Slow SMA", min_value=3, max_value=500, value=30, step=1)
    allow_short = st.toggle("Allow short positions", value=False)
    starting_cash = st.number_input("Starting balance", min_value=100.0, value=10000.0, step=500.0)
    fee_pct = st.number_input("Fee per side (%)", min_value=0.0, max_value=2.0, value=0.1, step=0.01, format="%.3f")
    slippage_pct = st.number_input("Slippage per side (%)", min_value=0.0, max_value=2.0, value=0.02, step=0.01, format="%.3f")

if refresh:
    st.caption("Auto-refresh is enabled. The page reloads data every 60 seconds.")
    time.sleep(0.01)
    st.markdown('<meta http-equiv="refresh" content="60">', unsafe_allow_html=True)

try:
    if source == "Binance (crypto)":
        data = load_binance(symbol, interval, limit)
        source_label = f"Binance public market data · {symbol} · {interval}"
    elif source == "Yahoo Finance (stocks / gold)":
        data = load_yahoo(ticker, period, interval)
        source_label = f"Yahoo Finance · {ticker} · {interval}"
    else:
        if uploaded is None:
            st.info("Choose a data source in the sidebar. Upload a CSV or select a live data provider to begin.")
            st.stop()
        data = load_csv(uploaded)
        source_label = f"Uploaded CSV · {uploaded.name}"

    if len(data) < int(slow) + 2:
        st.warning(f"Only {len(data)} candles were loaded. Load at least {int(slow) + 2} candles for this SMA setup.")

    tested, metrics, trades = run_backtest(data, int(fast), int(slow), float(starting_cash),
                                           float(fee_pct), float(slippage_pct), allow_short)
    latest_time = data.index[-1]
    st.caption(f"Source: {source_label} | Latest candle: {latest_time} | Retrieved: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Strategy return", f"{metrics['Total return (%)']:.2f}%")
    c2.metric("Final balance", f"{metrics['Final equity']:,.2f}")
    c3.metric("Maximum drawdown", f"{metrics['Max drawdown (%)']:.2f}%")
    c4.metric("Approx. Sharpe", f"{metrics['Sharpe (approx.)']:.2f}")

    tab1, tab2, tab3 = st.tabs(["Chart & equity", "Performance", "Data & trades"])
    with tab1:
        price_fig = go.Figure()
        price_fig.add_trace(go.Candlestick(x=tested.index, open=tested["Open"], high=tested["High"], low=tested["Low"], close=tested["Close"], name="Price"))
        price_fig.add_trace(go.Scatter(x=tested.index, y=tested["Fast MA"], name=f"SMA {fast}", line={"width": 1.5}))
        price_fig.add_trace(go.Scatter(x=tested.index, y=tested["Slow MA"], name=f"SMA {slow}", line={"width": 1.5}))
        buys = tested[(tested["Signal"].diff() > 0)]
        sells = tested[(tested["Signal"].diff() < 0)]
        price_fig.add_trace(go.Scatter(x=buys.index, y=buys["Low"], mode="markers", name="Buy signal", marker={"symbol": "triangle-up", "size": 10}))
        price_fig.add_trace(go.Scatter(x=sells.index, y=sells["High"], mode="markers", name="Sell / exit", marker={"symbol": "triangle-down", "size": 10}))
        price_fig.update_layout(height=520, xaxis_rangeslider_visible=False, title="Price, moving averages and signals")
        st.plotly_chart(price_fig, use_container_width=True)

        equity_fig = go.Figure()
        equity_fig.add_trace(go.Scatter(x=tested.index, y=tested["Equity"], name="Strategy equity"))
        equity_fig.add_trace(go.Scatter(x=tested.index, y=tested["Buy & Hold"], name="Buy & hold", line={"dash": "dash"}))
        equity_fig.update_layout(height=350, title="Equity curve", yaxis_title="Account value")
        st.plotly_chart(equity_fig, use_container_width=True)

    with tab2:
        st.subheader("Backtest statistics")
        display_metrics = {k: (f"{v:.2f}%" if "(%)" in k else f"{v:,.2f}" if isinstance(v, float) and np.isfinite(v) else str(v)) for k, v in metrics.items()}
        st.dataframe(pd.DataFrame({"Metric": list(display_metrics.keys()), "Value": list(display_metrics.values())}), hide_index=True, use_container_width=True)
        st.caption("Sharpe is approximate and annualization is not timeframe-adjusted. Profit factor is bar-based, not a broker-grade trade-ledger statistic. Results are sensitive to fees, slippage, data quality, and strategy assumptions.")

    with tab3:
        st.subheader("Trade segments (approximate)")
        if trades.empty:
            st.info("No non-flat position segments were generated for this setup.")
        else:
            st.dataframe(trades, use_container_width=True, hide_index=True)
            st.download_button("Download trades CSV", trades.to_csv(index=False).encode("utf-8"), "trades.csv", "text/csv")
        st.subheader("Latest candles")
        st.dataframe(tested.tail(100).sort_index(ascending=False), use_container_width=True)
        st.download_button("Download backtest data CSV", tested.to_csv().encode("utf-8"), "backtest_data.csv", "text/csv")

except requests.RequestException as exc:
    st.error(f"Could not retrieve market data: {exc}. Check your internet connection or try again.")
except Exception as exc:
    st.error(f"Could not run the backtest: {exc}")

st.divider()
st.caption("Educational software, not financial advice. Free public data can be delayed, rate-limited, revised, or unavailable. Never assume backtest results predict future performance.")
