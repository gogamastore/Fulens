"""Backtest per simbol untuk 'hybrid testing' dari aplikasi Flutter.

Mendukung:
  • timeframe (M15..W1),
  • rentang tanggal (start/end) atau N hari terakhir,
  • strategi: 'ta'  = confluence teknikal (EMA/MACD/RSI),
             'ml'  = memakai model XGBoost per simbol (jika sudah dilatih).

Mengembalikan metrik + kurva ekuitas untuk chart.
"""
import logging

import numpy as np
import pandas as pd

import market_data
import ml_symbol
import symbols as sym
import timeframes as tfmod

log = logging.getLogger("backtest")


def _ema(s: pd.Series, span: int) -> pd.Series:
    return s.ewm(span=span, adjust=False).mean()


def _rsi(s: pd.Series, period: int = 14) -> pd.Series:
    delta = s.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50)


def _ta_position(c: pd.Series) -> pd.Series:
    ema50, ema200 = _ema(c, 50), _ema(c, 200)
    macd = _ema(c, 12) - _ema(c, 26)
    macd_hist = macd - _ema(macd, 9)
    rsi = _rsi(c)
    sig = pd.Series(0, index=c.index)
    sig[(ema50 > ema200) & (macd_hist > 0) & (rsi > 50)] = 1
    sig[(ema50 < ema200) & (macd_hist < 0) & (rsi < 50)] = -1
    return sig.replace(0, np.nan).ffill().fillna(0)


def _ml_position(symbol: str, tf: str, df: pd.DataFrame) -> pd.Series | None:
    proba = ml_symbol.predict_proba(symbol, tf, df)
    if proba is None:
        return None
    pos = pd.Series(0.0, index=proba.index)
    pos[proba > 0.55] = 1
    pos[proba < 0.45] = -1
    return pos.replace(0, np.nan).ffill().fillna(0).reindex(df.index).fillna(0)


def _metrics(symbol: str, tf: str, df: pd.DataFrame, pos: pd.Series,
             strategy: str) -> dict:
    c = df["gold_close"]
    ret = c.pct_change().fillna(0)
    strat = pos.shift(1).fillna(0) * ret
    equity = (1 + strat).cumprod()

    total_return = float(equity.iloc[-1] - 1) * 100 if len(equity) else 0.0
    bh = float(c.iloc[-1] / c.iloc[0] - 1) * 100 if len(c) else 0.0

    # Pecah menjadi trade (segmen posisi konstan & tidak nol).
    trades: list[float] = []
    cur_pos, seg = 0.0, 1.0
    for p, r in zip(pos.shift(1).fillna(0), strat):
        if p != cur_pos:
            if cur_pos != 0:
                trades.append((seg - 1) * 100)
            cur_pos, seg = p, 1.0
        if p != 0:
            seg *= (1 + r)
    if cur_pos != 0:
        trades.append((seg - 1) * 100)

    wins = [t for t in trades if t > 0]
    losses = [t for t in trades if t <= 0]
    n = len(trades)
    gross_win, gross_loss = sum(wins), abs(sum(losses))
    pf = round(gross_win / gross_loss, 2) if gross_loss > 0 else (999.0 if gross_win > 0 else 0.0)

    cummax = equity.cummax()
    dd = (equity / cummax - 1) if len(equity) else pd.Series([0.0])
    max_dd = round(float(dd.min()) * 100, 1) if len(dd) else 0.0

    step = max(1, len(equity) // 120)
    curve = [{"date": str(idx), "equity": round(float(v), 4)}
             for idx, v in zip(equity.index[::step], equity.values[::step])]

    return {
        "symbol": sym.normalize(symbol),
        "timeframe": tfmod.normalize(tf),
        "strategy": strategy,
        "bars": len(df),
        "start": str(df.index[0]) if len(df) else None,
        "end": str(df.index[-1]) if len(df) else None,
        "total_return_pct": round(total_return, 2),
        "buy_hold_pct": round(bh, 2),
        "trades": n,
        "win_rate": round(len(wins) / n * 100, 1) if n else 0.0,
        "avg_win_pct": round(sum(wins) / len(wins), 2) if wins else 0.0,
        "avg_loss_pct": round(sum(losses) / len(losses), 2) if losses else 0.0,
        "profit_factor": pf,
        "max_drawdown_pct": max_dd,
        "equity_curve": curve,
    }


def run(symbol: str, tf: str = "D1", days: int = 365,
        start: str | None = None, end: str | None = None,
        strategy: str = "ta") -> dict | None:
    df = market_data.get_ohlc(symbol, tf, start=start, end=end)

    # Fallback: data intraday sering tak cukup (batas histori Yahoo ~60 hari
    # untuk M15/M30). Bila kurang, gunakan D1 agar backtest tetap berjalan.
    fallback_note = ""
    if (df is None or len(df) < 60) and tfmod.normalize(tf) != "D1":
        tf = "D1"
        df = market_data.get_ohlc(symbol, tf, start=start, end=end)
        fallback_note = (" Timeframe intraday tak cukup data (batas Yahoo) → "
                         "backtest memakai D1.")

    if df is None or len(df) < 60:
        return None

    # Jika tanpa rentang tanggal, batasi N bar terakhir (setelah warm-up indikator).
    if not (start or end):
        df = df.tail(min(days + 200, len(df)))

    strategy = (strategy or "ta").lower()
    note = "Strategi confluence teknikal (EMA50/200 + MACD + RSI), close-to-close."
    pos = None
    if strategy == "ml":
        if ml_symbol.has_model(symbol, tf):
            pos = _ml_position(symbol, tf, df)
            note = ("Strategi ML (XGBoost per simbol). Catatan: rentang yang tumpang "
                    "tindih dengan data latih bersifat in-sample; lihat akurasi test model.")
        if pos is None:
            strategy = "ta"
            note = "Model ML belum ada untuk simbol/timeframe ini — fallback ke teknikal."

    if pos is None:
        pos = _ta_position(df["gold_close"])

    result = _metrics(symbol, tf, df, pos, strategy)
    result["note"] = note + fallback_note
    ml_meta = ml_symbol.meta(symbol, tf)
    if ml_meta:
        result["ml_test_accuracy"] = ml_meta.get("test_accuracy")
    return result
