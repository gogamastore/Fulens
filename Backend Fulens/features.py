"""
FuLens — Feature Engineering
Menyiapkan semua fitur (teknikal + fundamental) untuk training model ML.

Jalankan: python features.py
"""

import warnings
warnings.filterwarnings("ignore")

import pandas as pd
import numpy as np
from sklearn.preprocessing import RobustScaler
import joblib
from colorama import init, Fore, Style
from pathlib import Path

init(autoreset=True)
import config

def log(msg, level="INFO"):
    colors = {"INFO": Fore.CYAN, "OK": Fore.GREEN, "WARN": Fore.YELLOW, "ERR": Fore.RED}
    prefix = {"INFO": "●", "OK": "✓", "WARN": "⚠", "ERR": "✗"}
    print(f"{colors.get(level,'')}[{prefix.get(level,'·')}] {msg}{Style.RESET_ALL}")


# ─────────────────────────────────────────────────────────
#  KALKULASI INDIKATOR (inline, tanpa import TechnicalAnalyzer)
# ─────────────────────────────────────────────────────────
def _ema(s, n): return s.ewm(span=n, adjust=False).mean()
def _sma(s, n): return s.rolling(n).mean()

def add_technical_features(df: pd.DataFrame) -> pd.DataFrame:
    """Tambahkan semua indikator teknikal sebagai kolom fitur."""
    c = df["gold_close"]
    h = df.get("gold_high", c)
    l = df.get("gold_low",  c)
    v = df.get("gold_volume", pd.Series(np.ones(len(df)), index=df.index))
    p = config.INDICATOR_PARAMS

    # ── Trend ──────────────────────────────────────────────
    df["f_ema20"]  = _ema(c, 20)
    df["f_ema50"]  = _ema(c, 50)
    df["f_ema200"] = _ema(c, 200)
    df["f_sma50"]  = _sma(c, 50)
    df["f_sma200"] = _sma(c, 200)

    # Price vs MA (jarak relatif)
    df["f_price_vs_ema20"]  = (c - df["f_ema20"])  / df["f_ema20"]
    df["f_price_vs_ema50"]  = (c - df["f_ema50"])  / df["f_ema50"]
    df["f_price_vs_ema200"] = (c - df["f_ema200"]) / df["f_ema200"]
    df["f_ema20_vs_ema50"]  = (df["f_ema20"] - df["f_ema50"]) / df["f_ema50"]

    # ── MACD ───────────────────────────────────────────────
    ema_fast  = _ema(c, p["MACD_FAST"])
    ema_slow  = _ema(c, p["MACD_SLOW"])
    macd_line = ema_fast - ema_slow
    macd_sig  = _ema(macd_line, p["MACD_SIGNAL"])
    df["f_macd"]      = macd_line
    df["f_macd_sig"]  = macd_sig
    df["f_macd_hist"] = macd_line - macd_sig
    df["f_macd_norm"] = df["f_macd"] / c  # normalized

    # ── RSI ────────────────────────────────────────────────
    delta = c.diff()
    gain  = delta.clip(lower=0).ewm(com=13, adjust=False).mean()
    loss  = (-delta.clip(upper=0)).ewm(com=13, adjust=False).mean()
    df["f_rsi"] = 100 - (100 / (1 + gain / loss.replace(0, np.nan)))
    df["f_rsi_norm"] = (df["f_rsi"] - 50) / 50  # normalized -1 to 1

    # ── Bollinger Bands ────────────────────────────────────
    bb_mid = _sma(c, 20)
    bb_std = c.rolling(20).std()
    bb_up  = bb_mid + 2 * bb_std
    bb_lo  = bb_mid - 2 * bb_std
    df["f_bb_pct_b"] = (c - bb_lo) / (bb_up - bb_lo).replace(0, np.nan)
    df["f_bb_width"] = (bb_up - bb_lo) / bb_mid

    # ── Stochastic ────────────────────────────────────────
    lo14 = l.rolling(14).min()
    hi14 = h.rolling(14).max()
    df["f_stoch_k"] = 100 * (c - lo14) / (hi14 - lo14).replace(0, np.nan)
    df["f_stoch_d"] = _sma(df["f_stoch_k"], 3)

    # ── ATR ───────────────────────────────────────────────
    tr = pd.concat([h-l, (h-c.shift()).abs(), (l-c.shift()).abs()], axis=1).max(axis=1)
    df["f_atr"]      = _ema(tr, 14)
    df["f_atr_norm"] = df["f_atr"] / c

    # ── CCI ───────────────────────────────────────────────
    tp = (h + l + c) / 3
    df["f_cci"] = (tp - _sma(tp, 20)) / (0.015 * tp.rolling(20).std())

    # ── Williams %R ───────────────────────────────────────
    df["f_wr"] = -100 * (h.rolling(14).max() - c) / (h.rolling(14).max() - l.rolling(14).min()).replace(0, np.nan)

    # ── ADX ───────────────────────────────────────────────
    dm_p = (h.diff()).clip(lower=0)
    dm_m = (-l.diff()).clip(lower=0)
    dm_p = dm_p.where(dm_p > dm_m, 0)
    dm_m = dm_m.where(dm_m > dm_p, 0)
    atr14 = df["f_atr"]
    di_p  = 100 * _ema(dm_p, 14) / atr14.replace(0, np.nan)
    di_m  = 100 * _ema(dm_m, 14) / atr14.replace(0, np.nan)
    dx    = 100 * (di_p - di_m).abs() / (di_p + di_m).replace(0, np.nan)
    df["f_adx"]    = _sma(dx, 14)
    df["f_di_plus"]  = di_p
    df["f_di_minus"] = di_m

    # ── Momentum & ROC ────────────────────────────────────
    df["f_roc5"]  = c.pct_change(5)
    df["f_roc10"] = c.pct_change(10)
    df["f_roc20"] = c.pct_change(20)
    df["f_mom10"] = c - c.shift(10)

    # ── OBV ───────────────────────────────────────────────
    df["f_obv"]      = (np.sign(c.diff()) * v).fillna(0).cumsum()
    df["f_obv_norm"] = df["f_obv"].pct_change(5)

    # ── Volatilitas historis ───────────────────────────────
    df["f_vol_5d"]  = c.pct_change().rolling(5).std()
    df["f_vol_20d"] = c.pct_change().rolling(20).std()

    # ── Candlestick features ───────────────────────────────
    df["f_body"]       = (c - df.get("gold_open", c)) / c
    df["f_upper_wick"] = (h - c.clip(lower=df.get("gold_open", c))) / c
    df["f_lower_wick"] = (c.clip(upper=df.get("gold_open", c)) - l) / c

    log(f"Fitur teknikal: {len([col for col in df.columns if col.startswith('f_')])} kolom", "OK")
    return df


def add_fundamental_features(df: pd.DataFrame) -> pd.DataFrame:
    """Normalisasi dan tambahkan fitur fundamental."""

    fund_cols = ["dxy", "vix", "bond10y", "oil", "sp500",
                 "cpi", "fed_rate", "unemployment", "gdp", "m2"]

    for col in fund_cols:
        if col in df.columns:
            # Perubahan pct (lebih informatif dari level absolut)
            df[f"f_{col}_chg"]   = df[col].pct_change()
            df[f"f_{col}_chg5"]  = df[col].pct_change(5)
            df[f"f_{col}_chg20"] = df[col].pct_change(20)
            # Level relatif (z-score rolling 60 hari)
            roll_mean = df[col].rolling(60).mean()
            roll_std  = df[col].rolling(60).std()
            df[f"f_{col}_zscore"] = (df[col] - roll_mean) / roll_std.replace(0, np.nan)

    # Korelasi emas-DXY (inverse biasanya)
    if "dxy" in df.columns:
        df["f_gold_dxy_corr"] = df["gold_close"].rolling(20).corr(df["dxy"])

    fund_feats = [c for c in df.columns if c.startswith("f_") and
                  any(f in c for f in fund_cols)]
    log(f"Fitur fundamental: {len(fund_feats)} kolom", "OK")
    return df


def add_lag_features(df: pd.DataFrame) -> pd.DataFrame:
    """Tambahkan lag features (nilai masa lalu)."""
    for lag in [1, 2, 3, 5, 10, 20]:
        df[f"f_close_lag{lag}"]    = df["gold_close"].shift(lag)
        df[f"f_return_lag{lag}"]   = df["gold_close"].pct_change().shift(lag)
        df[f"f_rsi_lag{lag}"]      = df.get("f_rsi", pd.Series()).shift(lag) if "f_rsi" in df.columns else np.nan
    log(f"Lag features ditambahkan (lag 1,2,3,5,10,20)", "OK")
    return df


def add_time_features(df: pd.DataFrame) -> pd.DataFrame:
    """Tambahkan fitur waktu (seasonality)."""
    df["f_day_of_week"]  = df.index.dayofweek / 6.0          # 0-1
    df["f_day_of_month"] = df.index.day / 31.0
    df["f_month"]        = df.index.month / 12.0
    df["f_quarter"]      = df.index.quarter / 4.0
    # Sine/cosine encoding untuk siklus
    df["f_month_sin"] = np.sin(2 * np.pi * df.index.month / 12)
    df["f_month_cos"] = np.cos(2 * np.pi * df.index.month / 12)
    df["f_dow_sin"]   = np.sin(2 * np.pi * df.index.dayofweek / 5)
    df["f_dow_cos"]   = np.cos(2 * np.pi * df.index.dayofweek / 5)
    log("Fitur waktu (seasonality) ditambahkan", "OK")
    return df


# ─────────────────────────────────────────────────────────
#  TARGET VARIABLES
# ─────────────────────────────────────────────────────────
def add_targets(df: pd.DataFrame) -> pd.DataFrame:
    """Tambahkan variabel target untuk training."""
    c = df["gold_close"]

    # Regresi: harga besok
    df["target_price_1d"]  = c.shift(-1)
    df["target_price_3d"]  = c.shift(-3)
    df["target_price_7d"]  = c.shift(-7)
    df["target_price_14d"] = c.shift(-14)
    df["target_price_30d"] = c.shift(-30)

    # Klasifikasi: naik/turun (1/0)
    df["target_dir_1d"]  = (c.shift(-1)  > c).astype(int)
    df["target_dir_3d"]  = (c.shift(-3)  > c).astype(int)
    df["target_dir_7d"]  = (c.shift(-7)  > c).astype(int)

    # Return pct
    df["target_ret_1d"]  = c.pct_change(-1) * -1
    df["target_ret_7d"]  = c.pct_change(-7) * -1

    log("Target variables ditambahkan (1d/3d/7d/14d/30d)", "OK")
    return df


# ─────────────────────────────────────────────────────────
#  SCALING & SPLIT
# ─────────────────────────────────────────────────────────
def get_feature_columns(df: pd.DataFrame) -> list:
    """Ambil semua kolom fitur (prefix f_)."""
    return [c for c in df.columns if c.startswith("f_")]


def prepare_ml_dataset(df: pd.DataFrame, target_col: str = "target_price_1d"):
    """
    Siapkan X, y untuk training.
    Returns: X_train, X_val, X_test, y_train, y_val, y_test, scaler_X, scaler_y
    """
    feature_cols = get_feature_columns(df)

    # Hapus KOLOM yang >50% NaN (bukan hapus baris)
    needed = feature_cols + [target_col]
    df_sub = df[needed].copy()
    thresh = int(len(df_sub) * 0.5)
    df_sub = df_sub.dropna(axis=1, thresh=thresh)

    # Forward-fill sisa NaN kecil, lalu drop baris yang masih NaN
    df_sub = df_sub.ffill().bfill()
    df_clean = df_sub.dropna()

    # Update feature_cols sesuai kolom yang tersisa
    feature_cols = [c for c in df_clean.columns if c.startswith("f_")]
    log(f"Fitur setelah filter NaN: {len(feature_cols)} kolom, {len(df_clean)} baris", "OK")

    X = df_clean[feature_cols].values
    y = df_clean[target_col].values

    # Bersihkan inf dan nilai ekstrem
    X = np.where(np.isinf(X), np.nan, X)
    col_medians = np.nanmedian(X, axis=0)
    for j in range(X.shape[1]):
        mask = np.isnan(X[:, j])
        X[mask, j] = col_medians[j]
    # Clip outlier ekstrem (±10 std)
    X = np.clip(X, -1e9, 1e9)

    # Split: 70% train, 15% val, 15% test (tanpa shuffle — time series!)
    n      = len(X)
    i_val  = int(n * 0.70)
    i_test = int(n * 0.85)

    X_train, y_train = X[:i_val],  y[:i_val]
    X_val,   y_val   = X[i_val:i_test], y[i_val:i_test]
    X_test,  y_test  = X[i_test:], y[i_test:]

    # Scaling (RobustScaler tahan outlier)
    scaler_X = RobustScaler()
    scaler_y = RobustScaler()

    X_train = scaler_X.fit_transform(X_train)
    X_val   = scaler_X.transform(X_val)
    X_test  = scaler_X.transform(X_test)

    y_train = scaler_y.fit_transform(y_train.reshape(-1,1)).ravel()
    y_val   = scaler_y.transform(y_val.reshape(-1,1)).ravel()
    y_test  = scaler_y.transform(y_test.reshape(-1,1)).ravel()

    # Simpan scaler
    scaler_path = config.MODEL_DIR / "scaler_X.pkl"
    scaler_y_path = config.MODEL_DIR / "scaler_y.pkl"
    joblib.dump(scaler_X, scaler_path)
    joblib.dump(scaler_y, scaler_y_path)
    joblib.dump(feature_cols, config.MODEL_DIR / "feature_cols.pkl")

    log(f"Dataset: Train={len(X_train)} | Val={len(X_val)} | Test={len(X_test)}", "OK")
    log(f"Fitur: {len(feature_cols)} kolom", "OK")
    log(f"Scaler disimpan di: {config.MODEL_DIR}", "OK")

    return X_train, X_val, X_test, y_train, y_val, y_test, scaler_X, scaler_y, feature_cols


def prepare_lstm_dataset(X_train, X_val, X_test, lookback: int = None):
    """Reshape dataset menjadi 3D untuk LSTM: (samples, timesteps, features)."""
    lb = lookback or config.LSTM_LOOKBACK

    def make_sequences(X, lb):
        if len(X) <= lb:
            return np.array([]).reshape(0, lb, X.shape[1])
        seqs = np.array([X[i-lb:i] for i in range(lb, len(X))])
        return seqs

    X_tr_seq = make_sequences(X_train, lb)
    X_vl_seq = make_sequences(X_val,   lb)
    X_ts_seq = make_sequences(X_test,  lb)

    log(f"LSTM sequences: Train={X_tr_seq.shape} | Val={X_vl_seq.shape} | Test={X_ts_seq.shape}", "OK")
    return X_tr_seq, X_vl_seq, X_ts_seq


# ─────────────────────────────────────────────────────────
#  PIPELINE UTAMA
# ─────────────────────────────────────────────────────────
def build_feature_set(df: pd.DataFrame) -> pd.DataFrame:
    """Jalankan semua feature engineering sekaligus."""
    log("Membangun feature set lengkap...")
    df = add_technical_features(df)
    df = add_fundamental_features(df)
    df = add_lag_features(df)
    df = add_time_features(df)
    df = add_targets(df)

    feat_cols = get_feature_columns(df)
    log(f"Total fitur: {len(feat_cols)}", "OK")

    # Simpan feature dataset
    out_path = config.PROCESSED_DIR / "gold_features.csv"
    df.to_csv(out_path)
    log(f"Feature dataset disimpan: {out_path}", "OK")
    return df


# ─────────────────────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────────────────────
if __name__ == "__main__":
    from data_pipeline import load_processed_data

    print("\n" + "═"*60)
    print("   🔬 FuLens — Feature Engineering")
    print("═"*60 + "\n")

    df = load_processed_data()
    df = build_feature_set(df)

    feat_cols = get_feature_columns(df)
    print(f"\n  Total baris data  : {len(df)}")
    print(f"  Total fitur (X)   : {len(feat_cols)}")
    print(f"  Target tersedia   : target_price_1d/3d/7d/14d/30d")
    print(f"\n  Daftar fitur:")
    for i, c in enumerate(feat_cols, 1):
        print(f"    {i:3d}. {c}")
    print()
