# Venom Backtester

A free Python/Streamlit trading research app for testing a simple moving-average crossover strategy against historical OHLCV candles. It can retrieve public Binance crypto candles, request Yahoo Finance data for supported tickers (including the gold futures symbol `GC=F` where available), or read a CSV file you provide.

This is an independent educational implementation of common backtesting workflows. It is **not a copied or reverse-engineered proprietary product**, and it is not a broker or trade execution system.

## Features

- Binance public candle data without an API key.
- Yahoo Finance historical market data through `yfinance` for supported stocks, forex symbols, commodities, and indices; availability and delay depend on ticker and interval.
- Presets for gold and silver futures, crude oil futures, EUR/USD, GBP/USD, USD/JPY, S&P 500, Nasdaq Composite, Apple, Microsoft, and Bitcoin USD, plus a custom Yahoo ticker option.
- CSV import for your own historical data.
- SMA crossover signals, optional short positions, and configurable starting balance, fees, and slippage.
- Candlestick chart, moving averages, signal markers, strategy equity curve, and buy-and-hold comparison.
- Return, approximate Sharpe ratio, maximum drawdown, position-change count, and downloadable CSV output.
- Optional page refresh every 60 seconds to request updated data.

## Run locally on Windows

Install Python 3.10 or newer, then open PowerShell in this folder.

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
streamlit run app.py
```

Streamlit will print a local address, usually `http://localhost:8501`. Open that address in your browser.

If PowerShell blocks activation, you can run the virtual environment's Python directly:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m streamlit run app.py
```

## Data source notes

### Binance (crypto)
Uses Binance's public REST kline endpoint. No private key is required. The app fetches up to 1,000 recent candles per request and refreshes by polling; this is not a WebSocket tick feed. Public endpoints may be rate-limited or regionally unavailable.

### Yahoo Finance (stocks and gold)
Uses `yfinance`, an unofficial community Python interface to Yahoo Finance. Free intraday history is limited, and the newest quote may be delayed. A ticker such as `GC=F` refers to gold futures, not the same instrument or price feed as every broker's XAU/USD CFD. Verify symbol, timezone, contract, session, and data rights before relying on results.

### CSV
Use columns named `Date` (or `Datetime`, `Timestamp`, or `Time`), `Open`, `High`, `Low`, `Close`, and optionally `Volume`. Rows should be in chronological order; the app sorts them by time.

## Strategy and assumptions

The starter strategy compares a fast simple moving average with a slow simple moving average. Signals are generated from candle closes and positions are shifted by one candle to reduce look-ahead bias. Fees and slippage are approximated as a percentage cost when position exposure changes.

This is a learning prototype, not a production-grade simulator. It does not yet model order-book spread, funding, swaps, margin, leverage, liquidation, partial fills, exchange outages, dividends, futures roll, or broker-specific contract specifications. The Sharpe annualization is approximate, and the displayed profit factor is bar-based rather than a formal closed-trade statistic. Validate calculations before using the tool for decisions.

## Free deployment

You can deploy the app on a free Streamlit Community Cloud account by selecting this GitHub repository, setting the app file path to `free-trading-backtester/app.py`, and using `free-trading-backtester/requirements.txt` as the dependency file if the deployment interface offers that option. Free service limits and policies may change.

## License

The project code is released under the MIT License in `LICENSE`. Market data remains subject to each provider's own terms; this license does not grant rights to redistribute market data.

## Disclaimer

For education and research only. Backtests can be misleading because of overfitting, incomplete data, unrealistic execution assumptions, and changing market conditions. Past performance does not guarantee future results. This app does not provide financial advice.
