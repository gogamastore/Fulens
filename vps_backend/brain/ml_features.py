"""Fitur ML generik berbasis harga (lintas simbol).

Berbeda dari features.py (khusus emas + fundamental), modul ini hanya memakai
OHLCV sehingga berlaku untuk forex/crypto/komoditas. Dipakai ml_symbol.py untuk
melatih XGBoost per simbol.
"""
import numpy as np
import pandas as pd


def _ema(s: pd.Series, span: int) -> pd.Series:
    return s.ewm(span=span, adjust=False).mean()


def _rsi(s: pd.Series, period: int = 14) -> pd.Series:
    delta = s.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50)


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    """Tambahkan kolom fitur teknikal ke df (kolom `gold_*`)."""
    o, h, l, c = (df["gold_open"], df["gold_high"], df["gold_low"], df["gold_close"])
    v = df.get("gold_volume", pd.Series(0, index=df.index))
    f = pd.DataFrame(index=df.index)

    # Return & momentum
    for n in (1, 3, 5, 10, 20):
        f[f"ret_{n}"] = c.pct_change(n)
    f["logret_1"] = np.log(c / c.shift(1))
    f["mom_10"] = c - c.shift(10)

    # EMA & rasio harga
    ema10, ema20, ema50, ema200 = _ema(c, 10), _ema(c, 20), _ema(c, 50), _ema(c, 200)
    f["px_ema10"] = c / ema10 - 1
    f["px_ema20"] = c / ema20 - 1
    f["px_ema50"] = c / ema50 - 1
    f["ema20_50"] = ema20 / ema50 - 1
    f["ema50_200"] = ema50 / ema200 - 1

    # RSI & MACD
    f["rsi"] = _rsi(c)
    macd = _ema(c, 12) - _ema(c, 26)
    macd_sig = _ema(macd, 9)
    f["macd"] = macd / c
    f["macd_hist"] = (macd - macd_sig) / c

    # Volatilitas & range
    tr = pd.concat([h - l, (h - c.shift(1)).abs(), (l - c.shift(1)).abs()],
                   axis=1).max(axis=1)
    f["atr_pct"] = tr.ewm(alpha=1 / 14, adjust=False).mean() / c
    f["vol_10"] = c.pct_change().rolling(10).std()
    f["vol_20"] = c.pct_change().rolling(20).std()
    f["range_pct"] = (h - l) / c

    # Stochastic
    ll = l.rolling(14).min()
    hh = h.rolling(14).max()
    stoch_k = 100 * (c - ll) / (hh - ll).replace(0, np.nan)
    f["stoch_k"] = stoch_k
    f["stoch_d"] = stoch_k.rolling(3).mean()

    # Volume (jika ada)
    f["vol_chg"] = v.pct_change().replace([np.inf, -np.inf], 0) if v.abs().sum() > 0 else 0.0

    # Lag return
    for n in (1, 2, 3, 5):
        f[f"lag_ret_{n}"] = c.pct_change().shift(n)

    return f.replace([np.inf, -np.inf], np.nan)


def feature_columns(f: pd.DataFrame) -> list[str]:
    return list(f.columns)


def make_dataset(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    """Return (X, y). y = 1 jika close bar berikutnya naik, else 0."""
    f = build_features(df)
    c = df["gold_close"]
    y = (c.shift(-1) > c).astype(int)
    data = f.copy()
    data["_y"] = y
    data = data.dropna()
    return data.drop(columns=["_y"]), data["_y"]
