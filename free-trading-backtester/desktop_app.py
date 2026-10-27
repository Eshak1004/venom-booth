"""Native Windows desktop interface for Venom Backtester.

Uses the same backtest_engine.py as the Streamlit web app.
"""
from __future__ import annotations

import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path
import tempfile
import webbrowser

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from backtest_engine import load_binance, load_csv, load_yahoo, run_backtest


PRESETS = {
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
    "Custom Yahoo ticker": "",
}


class VenomDesktopApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Venom Backtester — Desktop")
        self.root.geometry("1120x780")
        self.root.minsize(900, 620)
        self.csv_path: str | None = None
        self.last_result: pd.DataFrame | None = None
        self.last_trades: pd.DataFrame | None = None
        self.busy = False

        outer = ttk.Frame(root, padding=14)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text="Venom Backtester", font=("Segoe UI", 20, "bold")).pack(anchor="w")
        ttk.Label(
            outer,
            text="Desktop interface · historical research · no broker connection or live order execution",
        ).pack(anchor="w", pady=(0, 12))

        settings = ttk.LabelFrame(outer, text="Market data and strategy settings", padding=10)
        settings.pack(fill="x")
        self.source = tk.StringVar(value="Yahoo Finance")
        self.preset = tk.StringVar(value="Gold futures")
        self.ticker = tk.StringVar(value="GC=F")
        self.interval = tk.StringVar(value="15m")
        self.period = tk.StringVar(value="3mo")
        self.fast = tk.StringVar(value="10")
        self.slow = tk.StringVar(value="30")
        self.cash = tk.StringVar(value="10000")
        self.fee = tk.StringVar(value="0.10")
        self.slippage = tk.StringVar(value="0.02")
        self.allow_short = tk.BooleanVar(value=False)

        self._field(settings, "Data source", self.source, 0, 0, ["Yahoo Finance", "Binance", "CSV file"])
        self._field(settings, "Market preset", self.preset, 0, 2, list(PRESETS.keys()))
        self._field(settings, "Yahoo ticker / Binance symbol", self.ticker, 0, 4)
        self._field(settings, "Candle interval", self.interval, 1, 0,
                    ["1m", "3m", "5m", "15m", "30m", "60m", "1h", "2h", "4h", "1d", "1wk"])
        self._field(settings, "Yahoo period", self.period, 1, 2, ["1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y"])
        self._field(settings, "Fast SMA", self.fast, 1, 4)
        self._field(settings, "Slow SMA", self.slow, 2, 0)
        self._field(settings, "Starting balance", self.cash, 2, 2)
        self._field(settings, "Fee per side (%)", self.fee, 2, 4)
        self._field(settings, "Slippage per side (%)", self.slippage, 3, 0)
        ttk.Checkbutton(settings, text="Allow short positions", variable=self.allow_short).grid(
            row=3, column=2, columnspan=2, sticky="w", padx=6, pady=5
        )
        self.preset_box = next(
            child for child in settings.winfo_children()
            if isinstance(child, ttk.Combobox) and child.cget("textvariable") == str(self.preset)
        )
        self.preset_box.bind("<<ComboboxSelected>>", self._preset_changed)
        self.source_box = next(
            child for child in settings.winfo_children()
            if isinstance(child, ttk.Combobox) and child.cget("textvariable") == str(self.source)
        )
        self.source_box.bind("<<ComboboxSelected>>", self._source_changed)

        buttons = ttk.Frame(outer)
        buttons.pack(fill="x", pady=10)
        self.run_button = ttk.Button(buttons, text="Run backtest", command=self.run_clicked)
        self.run_button.pack(side="left")
        ttk.Button(buttons, text="Choose CSV…", command=self.choose_csv).pack(side="left", padx=8)
        ttk.Button(buttons, text="Open chart in browser", command=self.open_chart).pack(side="left")
        ttk.Button(buttons, text="Export results CSV", command=self.export_results).pack(side="left", padx=8)
        self.status = tk.StringVar(value="Ready. Choose a market and run a backtest.")
        ttk.Label(outer, textvariable=self.status).pack(anchor="w", pady=(0, 8))

        body = ttk.Panedwindow(outer, orient="vertical")
        body.pack(fill="both", expand=True)
        summary_frame = ttk.LabelFrame(body, text="Performance summary", padding=8)
        trades_frame = ttk.LabelFrame(body, text="Position segments (approximate)", padding=8)
        body.add(summary_frame, weight=1)
        body.add(trades_frame, weight=2)

        self.summary = tk.Text(summary_frame, height=8, wrap="word", font=("Consolas", 10))
        self.summary.pack(fill="both", expand=True)
        columns = ("entry", "exit", "side", "bars", "return")
        self.trade_table = ttk.Treeview(trades_frame, columns=columns, show="headings", height=10)
        for col, title, width in [
            ("entry", "Entry time (UTC)", 210),
            ("exit", "Exit time (UTC)", 210),
            ("side", "Side", 90),
            ("bars", "Bars", 70),
            ("return", "Return (%)", 100),
        ]:
            self.trade_table.heading(col, text=title)
            self.trade_table.column(col, width=width, anchor="w")
        scrollbar = ttk.Scrollbar(trades_frame, orient="vertical", command=self.trade_table.yview)
        self.trade_table.configure(yscrollcommand=scrollbar.set)
        self.trade_table.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        ttk.Label(
            outer,
            text="Educational software. Public data can be delayed or limited. Backtest results do not predict future performance.",
            wraplength=1000,
        ).pack(anchor="w", pady=(10, 0))

    def _field(self, parent, label, variable, row, column, values=None):
        frame = ttk.Frame(parent)
        frame.grid(row=row, column=column, sticky="ew", padx=6, pady=5)
        ttk.Label(frame, text=label).pack(anchor="w")
        if values:
            widget = ttk.Combobox(frame, textvariable=variable, values=values, state="readonly", width=23)
        else:
            widget = ttk.Entry(frame, textvariable=variable, width=25)
        widget.pack(fill="x", pady=(3, 0))
        parent.columnconfigure(column, weight=1)
        return widget

    def _preset_changed(self, _event=None):
        selected = self.preset.get()
        if selected in PRESETS and PRESETS[selected]:
            self.ticker.set(PRESETS[selected])

    def _source_changed(self, _event=None):
        if self.source.get() == "Binance":
            self.ticker.set("BTCUSDT")
            self.interval.set("15m")
        elif self.source.get() == "Yahoo Finance":
            self.ticker.set(PRESETS.get(self.preset.get(), "GC=F") or "GC=F")

    def choose_csv(self):
        path = filedialog.askopenfilename(
            title="Select OHLCV CSV",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if path:
            self.csv_path = path
            self.source.set("CSV file")
            self.status.set(f"Selected CSV: {Path(path).name}")

    def run_clicked(self):
        if self.busy:
            return
        config = {
            "source": self.source.get(),
            "ticker": self.ticker.get().strip(),
            "interval": self.interval.get(),
            "period": self.period.get(),
            "fast": self.fast.get(),
            "slow": self.slow.get(),
            "cash": self.cash.get(),
            "fee": self.fee.get(),
            "slippage": self.slippage.get(),
            "allow_short": self.allow_short.get(),
            "csv_path": self.csv_path,
        }
        self.busy = True
        self.run_button.configure(state="disabled")
        self.status.set("Loading market data and running backtest…")
        threading.Thread(target=self._run_worker, args=(config,), daemon=True).start()

    def _run_worker(self, config):
        try:
            source = config["source"]
            interval = config["interval"]
            ticker = config["ticker"]
            if source == "Binance":
                data = load_binance(ticker.upper(), interval, 1000)
                label = f"Binance {ticker.upper()} {interval}"
            elif source == "Yahoo Finance":
                data = load_yahoo(ticker, config["period"], interval)
                label = f"Yahoo Finance {ticker} {interval}"
            else:
                if not config["csv_path"]:
                    raise ValueError("Choose a CSV file first.")
                data = load_csv(config["csv_path"])
                label = f"CSV {Path(config['csv_path']).name}"

            fast, slow = int(config["fast"]), int(config["slow"])
            cash, fee, slip = float(config["cash"]), float(config["fee"]), float(config["slippage"])
            tested, metrics, trades = run_backtest(data, fast, slow, cash, fee, slip, config["allow_short"])
            self.root.after(0, lambda: self._show_result(label, data, tested, metrics, trades))
        except Exception as exc:
            self.root.after(0, lambda message=str(exc): self._show_error(message))

    def _show_error(self, message):
        self.busy = False
        self.run_button.configure(state="normal")
        self.status.set("Backtest failed.")
        messagebox.showerror("Could not run backtest", message)

    def _show_result(self, label, data, tested, metrics, trades):
        self.last_result, self.last_trades = tested, trades
        self.summary.delete("1.0", "end")
        lines = [f"Data: {label}", f"Candles: {len(data):,}",
                 f"Latest candle: {data.index[-1] if len(data) else 'N/A'}", ""]
        for key, value in metrics.items():
            if isinstance(value, (int, float, np.integer, np.floating)):
                lines.append(f"{key}: {value:,.3f}" if np.isfinite(value) else f"{key}: {value}")
            else:
                lines.append(f"{key}: {value}")
        lines += ["", "Notes: Sharpe annualization is approximate; profit factor is bar-based."]
        self.summary.insert("1.0", "\n".join(lines))
        for item in self.trade_table.get_children():
            self.trade_table.delete(item)
        if not trades.empty:
            for _, row in trades.tail(500).iterrows():
                self.trade_table.insert("", "end", values=(
                    str(row["Entry time"]), str(row["Exit time"]), row["Side"],
                    int(row["Bars"]), f"{row['Return (%)']:.3f}",
                ))
        self.status.set(f"Backtest complete · {len(data):,} candles · {label}")
        self.busy = False
        self.run_button.configure(state="normal")

    def open_chart(self):
        if self.last_result is None:
            messagebox.showinfo("No results yet", "Run a backtest first.")
            return
        df = self.last_result
        fig = go.Figure()
        fig.add_trace(go.Candlestick(
            x=df.index, open=df["Open"], high=df["High"], low=df["Low"], close=df["Close"], name="Price"
        ))
        fig.add_trace(go.Scatter(x=df.index, y=df["Fast MA"], name="Fast SMA"))
        fig.add_trace(go.Scatter(x=df.index, y=df["Slow MA"], name="Slow SMA"))
        fig.update_layout(title="Venom Backtester — Price and moving averages", xaxis_rangeslider_visible=False)
        path = Path(tempfile.gettempdir()) / "venom_backtester_chart.html"
        fig.write_html(str(path), include_plotlyjs=True)
        webbrowser.open(path.as_uri())

    def export_results(self):
        if self.last_result is None:
            messagebox.showinfo("No results yet", "Run a backtest first.")
            return
        path = filedialog.asksaveasfilename(
            title="Export backtest results",
            defaultextension=".csv",
            initialfile="venom_backtest_results.csv",
            filetypes=[("CSV files", "*.csv")],
        )
        if path:
            self.last_result.to_csv(path)
            messagebox.showinfo("Export complete", f"Saved results to:\n{path}")


if __name__ == "__main__":
    root = tk.Tk()
    app = VenomDesktopApp(root)
    root.mainloop()
