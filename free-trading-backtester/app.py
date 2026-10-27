from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st
from streamlit_autorefresh import st_autorefresh

st.set_page_config(page_title="Venom Backtester", page_icon="📈", layout="wide")

from backtest_engine import load_binance, load_csv, load_yahoo, run_backtest
st.title("Venom Backtester")
st.caption("A free, open-source-style research tool for historical testing and near-real-time market data. Paper research only — not a broker or execution platform.")

with st.sidebar:
    st.header("1. Market data")
    source = st.selectbox("Data source", ["Binance (crypto)", "Yahoo Finance (stocks / forex / commodities / indices)", "Upload CSV"])
    refresh = st.toggle("Auto-refresh data every 60 seconds", value=False)
    if source == "Binance (crypto)":
        symbol = st.text_input("Binance symbol", "BTCUSDT").strip().upper()
        interval = st.selectbox("Candle interval", ["1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "1d"], index=3)
        limit = st.slider("Candles to load (max 1,000)", 100, 1000, 500, 100)
    elif source == "Yahoo Finance (stocks / forex / commodities / indices)":
        presets = {
            "Gold futures": "GC=F",
            "Silver futures": "SI=F",
            "Crude oil futures": "CL=F",
            "EUR/USD forex": "EURUSD=X",
            "GBP/USD forex": "GBPUSD=X",
            "USD/JPY forex": "JPY=X",
            "S&P 500 index": "^GSPC",
            "Nasdaq Composite index": "^IXIC",
            "Apple stock": "AAPL",
            "Microsoft stock": "MSFT",
            "Bitcoin USD": "BTC-USD",
            "Custom ticker": "",
        }
        preset = st.selectbox("Market / instrument", list(presets.keys()), index=0)
        if preset == "Custom ticker":
            ticker = st.text_input("Yahoo Finance ticker", "GC=F").strip()
        else:
            ticker = presets[preset]
            st.caption(f"Selected Yahoo Finance symbol: {ticker}")
        period = st.selectbox("Historical period", ["1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y"], index=2)
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
    st.caption("Auto-refresh is enabled. Market data is requested again every 60 seconds.")
    st_autorefresh(interval=60_000, key="market_data_refresh")

try:
    if source == "Binance (crypto)":
        data = load_binance(symbol, interval, limit)
        source_label = f"Binance public market data · {symbol} · {interval}"
    elif source == "Yahoo Finance (stocks / forex / commodities / indices)":
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
