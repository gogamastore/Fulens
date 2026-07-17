"""Indikator teknikal berbasis pandas/numpy (tanpa dependensi TA eksternal)."""
import numpy as np
import pandas as pd


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50)


def macd(series: pd.Series, fast=12, slow=26, signal=9):
    macd_line = ema(series, fast) - ema(series, slow)
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    return macd_line, signal_line, macd_line - signal_line


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat([high - low, (high - prev_close).abs(),
                    (low - prev_close).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def stochastic(df: pd.DataFrame, k=14, d=3):
    low_min = df["low"].rolling(k).min()
    high_max = df["high"].rolling(k).max()
    k_line = 100 * (df["close"] - low_min) / (high_max - low_min)
    return k_line, k_line.rolling(d).mean()


def efficiency_ratio(close: pd.Series, period: int = 20) -> float:
    """Kaufman Efficiency Ratio: |gerak bersih| / total lintasan.
    ~0 = pasar choppy/ranging (cocok mean-reversion), ~1 = trending kuat."""
    if len(close) <= period:
        return 1.0
    seg = close.iloc[-(period + 1):]
    net = abs(float(seg.iloc[-1]) - float(seg.iloc[0]))
    path = float(seg.diff().abs().sum())
    return net / path if path > 0 else 0.0


def enrich(df: pd.DataFrame, atr_period: int = 14,
           vol_period: int = 20) -> pd.DataFrame:
    """Tambahkan semua indikator ke DataFrame OHLC."""
    out = df.copy()
    out["ema50"] = ema(out["close"], 50)
    out["ema200"] = ema(out["close"], 200)
    out["rsi"] = rsi(out["close"])
    out["macd"], out["macd_signal"], out["macd_hist"] = macd(out["close"])
    out["atr"] = atr(out, atr_period)
    out["stoch_k"], out["stoch_d"] = stochastic(out)
    # Rata-rata volume utk gerbang partisipasi mode scalping. Rate MT5 memberi
    # `tick_volume` (jumlah tick) — bukan volume riil, tapi proksi aktivitas yang
    # sah untuk gold/forex, di mana `real_volume` broker retail umumnya 0.
    if "tick_volume" in out.columns:
        out["vol_ma"] = out["tick_volume"].rolling(vol_period).mean()
    return out
