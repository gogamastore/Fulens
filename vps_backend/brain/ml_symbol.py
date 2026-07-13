"""ML per simbol (XGBoost) — prediksi arah bar berikutnya.

Ringan & cepat dilatih (tree-based, tanpa GPU). Tiap simbol+timeframe punya
model sendiri di folder models/. Emas tetap punya ensemble LSTM+XGBoost terpisah;
modul ini untuk memberi 'otak ML' pada semua simbol lain (dan bisa juga emas).

Alur: ml_features → XGBClassifier(P naik) → dipakai signal_engine (blend) &
backtest_engine (strategi 'ml', train/test split).
"""
import json
import logging
from datetime import datetime

import numpy as np
import pandas as pd

import config
import market_data
import ml_features
import symbols as sym
import timeframes as tfmod

log = logging.getLogger("ml_symbol")

try:
    import xgboost as xgb
    XGB_OK = True
except ImportError:
    XGB_OK = False

_LOADED: dict[str, tuple] = {}   # key -> (model, feature_cols, meta)


def _key(symbol: str, tf: str) -> str:
    return f"{sym.normalize(symbol)}_{tfmod.normalize(tf)}"


def _model_path(symbol: str, tf: str):
    return config.MODEL_DIR / f"sym_{_key(symbol, tf)}_xgb.json"


def _meta_path(symbol: str, tf: str):
    return config.MODEL_DIR / f"sym_{_key(symbol, tf)}_meta.json"


def has_model(symbol: str, tf: str = "D1") -> bool:
    return _model_path(symbol, tf).exists() and _meta_path(symbol, tf).exists()


# ─────────────────────────────────────────────────────────
#  TRAINING
# ─────────────────────────────────────────────────────────
def train(symbol: str, tf: str = "D1", test_ratio: float = 0.2) -> dict | None:
    """Latih XGBoost untuk satu simbol+timeframe. Return metrik + simpan model."""
    if not XGB_OK:
        log.error("xgboost tidak tersedia")
        return None

    df = market_data.get_ohlc(symbol, tf)
    if df is None or len(df) < 260:
        log.warning("%s %s: data tidak cukup untuk training (%s baris)",
                    symbol, tf, 0 if df is None else len(df))
        return None

    X, y = ml_features.make_dataset(df)
    if len(X) < 200:
        log.warning("%s %s: sampel fitur kurang (%d)", symbol, tf, len(X))
        return None

    split = int(len(X) * (1 - test_ratio))
    X_tr, X_te = X.iloc[:split], X.iloc[split:]
    y_tr, y_te = y.iloc[:split], y.iloc[split:]

    model = xgb.XGBClassifier(
        n_estimators=300, max_depth=4, learning_rate=0.05,
        subsample=0.8, colsample_bytree=0.8, eval_metric="logloss",
        random_state=42, n_jobs=2,
    )
    model.fit(X_tr, y_tr)

    # Evaluasi di test (out-of-sample).
    proba = model.predict_proba(X_te)[:, 1]
    pred = (proba >= 0.5).astype(int)
    acc = float((pred == y_te.values).mean()) if len(y_te) else 0.0
    base = float(max(y_te.mean(), 1 - y_te.mean())) if len(y_te) else 0.0

    meta = {
        "symbol": sym.normalize(symbol),
        "timeframe": tfmod.normalize(tf),
        "features": list(X.columns),
        "n_train": int(len(X_tr)),
        "n_test": int(len(X_te)),
        "test_accuracy": round(acc, 4),
        "baseline": round(base, 4),
        "trained_at": datetime.now().isoformat(),
    }
    config.MODEL_DIR.mkdir(parents=True, exist_ok=True)
    model.save_model(str(_model_path(symbol, tf)))
    with open(_meta_path(symbol, tf), "w") as fh:
        json.dump(meta, fh, indent=2)
    _LOADED.pop(_key(symbol, tf), None)
    log.info("Model %s %s dilatih — akurasi test %.3f (baseline %.3f)",
             symbol, tf, acc, base)
    return meta


# ─────────────────────────────────────────────────────────
#  LOAD & PREDICT
# ─────────────────────────────────────────────────────────
def _load(symbol: str, tf: str):
    k = _key(symbol, tf)
    if k in _LOADED:
        return _LOADED[k]
    if not has_model(symbol, tf) or not XGB_OK:
        return None
    try:
        model = xgb.XGBClassifier()
        model.load_model(str(_model_path(symbol, tf)))
        meta = json.loads(_meta_path(symbol, tf).read_text())
        _LOADED[k] = (model, meta["features"], meta)
        return _LOADED[k]
    except Exception as e:
        log.warning("Gagal load model %s %s: %s", symbol, tf, e)
        return None


def meta(symbol: str, tf: str = "D1") -> dict | None:
    got = _load(symbol, tf)
    return got[2] if got else None


def predict_proba(symbol: str, tf: str, df: pd.DataFrame) -> pd.Series | None:
    """Probabilitas 'naik' per bar untuk df (dipakai backtest)."""
    got = _load(symbol, tf)
    if not got:
        return None
    model, feats, _ = got
    X = ml_features.build_features(df).reindex(columns=feats)
    X = X.replace([np.inf, -np.inf], np.nan).dropna()
    if X.empty:
        return None
    proba = model.predict_proba(X)[:, 1]
    return pd.Series(proba, index=X.index)


def predict_latest(symbol: str, tf: str = "D1") -> float | None:
    """Probabilitas 'naik' untuk bar terakhir (dipakai signal_engine)."""
    df = market_data.get_ohlc(symbol, tf)
    if df is None:
        return None
    s = predict_proba(symbol, tf, df)
    return float(s.iloc[-1]) if s is not None and len(s) else None
