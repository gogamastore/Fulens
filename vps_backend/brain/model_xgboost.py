"""
FuLens — Model XGBoost
Training, evaluasi, dan prediksi menggunakan XGBoost.

Jalankan: python model_xgboost.py
"""

import warnings
warnings.filterwarnings("ignore")

import pandas as pd
import numpy as np
import joblib
import json
from datetime import datetime, timedelta
from colorama import init, Fore, Style
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import TimeSeriesSplit
import xgboost as xgb

init(autoreset=True)
import config
from data_pipeline import load_processed_data
from features import build_feature_set, prepare_ml_dataset, get_feature_columns

def log(msg, level="INFO"):
    colors = {"INFO": Fore.CYAN, "OK": Fore.GREEN, "WARN": Fore.YELLOW, "ERR": Fore.RED}
    prefix = {"INFO": "●", "OK": "✓", "WARN": "⚠", "ERR": "✗"}
    print(f"{colors.get(level,'')}[{prefix.get(level,'·')}] {msg}{Style.RESET_ALL}")


# ─────────────────────────────────────────────────────────
#  EVALUASI METRIK
# ─────────────────────────────────────────────────────────
def evaluate(y_true, y_pred, scaler_y, label=""):
    """Hitung dan tampilkan metrik evaluasi."""
    # Inverse transform ke harga asli
    y_true_real = scaler_y.inverse_transform(y_true.reshape(-1,1)).ravel()
    y_pred_real = scaler_y.inverse_transform(y_pred.reshape(-1,1)).ravel()

    mae   = mean_absolute_error(y_true_real, y_pred_real)
    rmse  = np.sqrt(mean_squared_error(y_true_real, y_pred_real))
    r2    = r2_score(y_true_real, y_pred_real)
    mape  = np.mean(np.abs((y_true_real - y_pred_real) / y_true_real.clip(min=1))) * 100
    acc   = 100 - mape

    # Akurasi arah (naik/turun)
    dir_true = np.sign(np.diff(y_true_real))
    dir_pred = np.sign(np.diff(y_pred_real))
    dir_acc  = np.mean(dir_true == dir_pred) * 100

    log(f"{'─'*40}", "INFO")
    log(f"Evaluasi {label}", "INFO")
    log(f"  MAE        : ${mae:,.2f}", "OK")
    log(f"  RMSE       : ${rmse:,.2f}", "OK")
    log(f"  R²         : {r2:.4f}", "OK")
    log(f"  MAPE       : {mape:.2f}%", "OK")
    log(f"  Akurasi    : {acc:.2f}%", "OK")
    log(f"  Akurasi Arah: {dir_acc:.2f}%", "OK")

    return {
        "mae": round(mae,2), "rmse": round(rmse,2),
        "r2": round(r2,4), "mape": round(mape,2),
        "accuracy": round(acc,2), "direction_accuracy": round(dir_acc,2)
    }


# ─────────────────────────────────────────────────────────
#  TRAINING XGBOOST
# ─────────────────────────────────────────────────────────
def train_xgboost(X_train, y_train, X_val, y_val, feature_cols):
    """Train XGBoost dengan early stopping."""
    log("Training XGBoost...", "INFO")

    params = config.XGBOOST_PARAMS.copy()
    params["early_stopping_rounds"] = 50
    params["eval_metric"] = "rmse"

    model = xgb.XGBRegressor(**params)
    model.fit(
        X_train, y_train,
        eval_set=[(X_val, y_val)],
        verbose=50,
    )

    best_iter = model.best_iteration
    log(f"Best iteration: {best_iter}", "OK")

    # Feature importance
    importance = model.feature_importances_
    feat_imp = sorted(
        zip(feature_cols, importance),
        key=lambda x: x[1], reverse=True
    )

    log("\nTop 15 Feature Importance:", "INFO")
    for i, (fname, imp) in enumerate(feat_imp[:15], 1):
        bar = "█" * int(imp * 300)
        print(f"  {i:2d}. {fname:<30} {imp:.4f} {bar}")

    return model, feat_imp


# ─────────────────────────────────────────────────────────
#  CROSS VALIDATION TIME SERIES
# ─────────────────────────────────────────────────────────
def cross_validate_xgb(X, y, n_splits=5):
    """Time-series cross validation."""
    log(f"Cross-validation ({n_splits} folds)...", "INFO")
    tscv   = TimeSeriesSplit(n_splits=n_splits)
    scores = []

    for fold, (tr_idx, val_idx) in enumerate(tscv.split(X), 1):
        X_tr, X_vl = X[tr_idx], X[val_idx]
        y_tr, y_vl = y[tr_idx], y[val_idx]

        m = xgb.XGBRegressor(**{k:v for k,v in config.XGBOOST_PARAMS.items()
                                  if k != "early_stopping_rounds"}, verbosity=0)
        m.fit(X_tr, y_tr)
        pred = m.predict(X_vl)
        mae  = mean_absolute_error(y_vl, pred)
        scores.append(mae)
        log(f"  Fold {fold}: MAE = {mae:.4f}", "OK")

    log(f"CV MAE: {np.mean(scores):.4f} ± {np.std(scores):.4f}", "OK")
    return scores


# ─────────────────────────────────────────────────────────
#  PREDIKSI MULTI-HORIZON
# ─────────────────────────────────────────────────────────
def predict_future(model, df_features, scaler_X, scaler_y, feature_cols,
                   horizons=[1, 3, 7, 14, 30]):
    """Prediksi harga untuk beberapa horizon ke depan."""
    log("Membuat prediksi ke depan...", "INFO")

    # Bersihkan data
    last_data = df_features[feature_cols].copy().ffill().bfill()
    last_data = last_data.replace([np.inf, -np.inf], 0).fillna(0)

    current_price = float(df_features["gold_close"].iloc[-1])
    predictions   = {}

    # Prediksi 1 hari (paling akurat — langsung dari fitur terakhir)
    last_row_scaled = scaler_X.transform(last_data.iloc[-1:].values)
    pred_1d_scaled  = model.predict(last_row_scaled)[0]
    pred_1d_price   = float(scaler_y.inverse_transform([[pred_1d_scaled]])[0][0])

    # Hitung return 1 hari yang diprediksi
    daily_return = (pred_1d_price - current_price) / current_price

    # Batasi return harian maks ±3% (realistis untuk emas)
    daily_return = np.clip(daily_return, -0.03, 0.03)

    # XGBoost: decay lebih cepat (lebih konservatif, berbasis fitur teknikal)
    DECAY = 0.60

    for h in horizons:
        # Return kumulatif dengan decay
        cumulative_return = 0.0
        r = daily_return
        for day in range(h):
            cumulative_return += r
            r *= DECAY  # return meluruh setiap hari

        final_price = current_price * (1 + cumulative_return)
        # Batasi perubahan maks: ±15% per 30 hari
        max_chg = 0.005 * h  # 0.5% per hari maksimal
        final_price = np.clip(
            final_price,
            current_price * (1 - max_chg),
            current_price * (1 + max_chg)
        )

        predictions[h] = {
            "horizon_days": h,
            "predicted_price": round(float(final_price), 2),
            "change_usd": round(float(final_price - current_price), 2),
            "change_pct": round(float((final_price - current_price) / current_price * 100), 2),
            "signal": "BELI" if final_price > current_price else "JUAL",
            "date": (datetime.now() + timedelta(days=h)).strftime("%Y-%m-%d"),
        }

    return predictions, current_price


def print_predictions(predictions, current_price):
    """Tampilkan tabel prediksi."""
    print("\n" + "═"*68)
    print(f"  {'PREDIKSI HARGA EMAS — XGBOOST':^64}")
    print(f"  {'Harga Saat Ini: $' + f'{current_price:,.2f}':^64}")
    print("═"*68)
    print(f"  {'Horizon':<12} {'Tanggal':<14} {'Prediksi':>12} {'Δ USD':>10} {'Δ %':>8}  Sinyal")
    print("  " + "─"*62)

    for h, p in predictions.items():
        clr = Fore.GREEN if p["signal"] == "BELI" else Fore.RED
        icon = "▲" if p["signal"] == "BELI" else "▼"
        print(f"  {str(h)+' Hari':<12} {p['date']:<14} "
              f"${p['predicted_price']:>10,.2f} "
              f"{p['change_usd']:>+10.2f} "
              f"{p['change_pct']:>+7.2f}%  "
              f"{clr}{icon} {p['signal']}{Style.RESET_ALL}")

    print("═"*68 + "\n")


# ─────────────────────────────────────────────────────────
#  SIMPAN & LOAD MODEL
# ─────────────────────────────────────────────────────────
def save_model(model, metrics, feat_imp):
    path = config.MODEL_DIR / "xgboost_model.json"
    model.save_model(str(path))

    meta = {
        "model_type"  : "XGBoost",
        "trained_at"  : datetime.now().isoformat(),
        "metrics"     : metrics,
        "top_features": [{"name": f, "importance": round(float(i),4)}
                         for f, i in feat_imp[:20]],
        "params"      : config.XGBOOST_PARAMS,
    }
    with open(config.MODEL_DIR / "xgboost_meta.json", "w") as f:
        json.dump(meta, f, indent=2)

    log(f"Model disimpan: {path}", "OK")


def load_xgb_model():
    path = config.MODEL_DIR / "xgboost_model.json"
    if not path.exists():
        raise FileNotFoundError("Model belum ditraining. Jalankan: python model_xgboost.py")
    model = xgb.XGBRegressor()
    model.load_model(str(path))
    scaler_X    = joblib.load(config.MODEL_DIR / "scaler_X.pkl")
    scaler_y    = joblib.load(config.MODEL_DIR / "scaler_y.pkl")
    feature_cols = joblib.load(config.MODEL_DIR / "feature_cols.pkl")
    return model, scaler_X, scaler_y, feature_cols


# ─────────────────────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("\n" + "═"*60)
    print("   🤖 FuLens — XGBoost Training")
    print("═"*60 + "\n")

    # 1. Load & feature engineering
    log("Memuat data...", "INFO")
    df = load_processed_data()
    df = build_feature_set(df)

    # 2. Siapkan dataset
    (X_train, X_val, X_test,
     y_train, y_val, y_test,
     scaler_X, scaler_y, feature_cols) = prepare_ml_dataset(df, "target_price_1d")

    # 3. Cross validation
    X_all = np.vstack([X_train, X_val])
    y_all = np.concatenate([y_train, y_val])
    cross_validate_xgb(X_all, y_all, n_splits=5)

    # 4. Training
    model, feat_imp = train_xgboost(X_train, y_train, X_val, y_val, feature_cols)

    # 5. Evaluasi
    val_pred  = model.predict(X_val)
    test_pred = model.predict(X_test)
    val_metrics  = evaluate(y_val,  val_pred,  scaler_y, "Validasi")
    test_metrics = evaluate(y_test, test_pred, scaler_y, "Test")

    # 6. Prediksi ke depan
    predictions, cur_price = predict_future(
        model, df, scaler_X, scaler_y, feature_cols,
        horizons=[1, 3, 7, 14, 30]
    )
    print_predictions(predictions, cur_price)

    # 7. Simpan
    save_model(model, {"validation": val_metrics, "test": test_metrics}, feat_imp)

    log("XGBoost selesai! Lanjut: python model_lstm.py", "OK")
