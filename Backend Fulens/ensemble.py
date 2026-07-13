"""
FuLens — Ensemble Model
Menggabungkan prediksi LSTM + XGBoost menjadi sinyal akhir.

Jalankan: python ensemble.py
"""

import warnings
warnings.filterwarnings("ignore")

import pandas as pd
import numpy as np
import joblib
import json
from datetime import datetime, timedelta
from colorama import init, Fore, Style

init(autoreset=True)
import config
from data_pipeline import load_processed_data
from features import build_feature_set, prepare_ml_dataset, prepare_lstm_dataset, get_feature_columns
from model_xgboost import load_xgb_model, predict_future as xgb_predict
from model_lstm import load_lstm_model, predict_lstm_future, TORCH_OK

def log(msg, level="INFO"):
    colors = {"INFO": Fore.CYAN, "OK": Fore.GREEN, "WARN": Fore.YELLOW, "ERR": Fore.RED}
    prefix = {"INFO": "●", "OK": "✓", "WARN": "⚠", "ERR": "✗"}
    print(f"{colors.get(level,'')}[{prefix.get(level,'·')}] {msg}{Style.RESET_ALL}")


# ─────────────────────────────────────────────────────────
#  ENSEMBLE PREDIKSI
# ─────────────────────────────────────────────────────────
def ensemble_predict(xgb_preds: dict, lstm_preds: dict,
                     current_price: float,
                     w_xgb: float = None, w_lstm: float = None) -> dict:
    """
    Gabungkan prediksi XGBoost + LSTM dengan weighted average.
    Jika salah satu tidak tersedia, gunakan yang ada saja.
    """
    w_xgb  = w_xgb  or config.ENSEMBLE_WEIGHTS["xgboost"]
    w_lstm = w_lstm or config.ENSEMBLE_WEIGHTS["lstm"]

    # Normalisasi bobot
    if not xgb_preds:  w_xgb = 0.0
    if not lstm_preds: w_lstm = 0.0
    total_w = w_xgb + w_lstm
    if total_w == 0:
        return {}
    w_xgb  /= total_w
    w_lstm /= total_w

    horizons = sorted(set(list(xgb_preds.keys()) + list(lstm_preds.keys())))
    results  = {}

    for h in horizons:
        prices = []
        weights = []

        if h in xgb_preds and w_xgb > 0:
            prices.append(xgb_preds[h]["predicted_price"])
            weights.append(w_xgb)

        if h in lstm_preds and w_lstm > 0:
            prices.append(lstm_preds[h]["predicted_price"])
            weights.append(w_lstm)

        if not prices:
            continue

        # Weighted average
        w_arr   = np.array(weights) / sum(weights)
        ens_price = float(np.dot(prices, w_arr))

        # Confidence interval ±1 std dari kedua model
        if len(prices) > 1:
            std_dev = np.std(prices)
        else:
            std_dev = ens_price * 0.015  # estimasi 1.5% jika hanya 1 model

        results[h] = {
            "horizon_days"   : h,
            "predicted_price": round(ens_price, 2),
            "lower_bound"    : round(ens_price - 1.96 * std_dev, 2),
            "upper_bound"    : round(ens_price + 1.96 * std_dev, 2),
            "change_usd"     : round(ens_price - current_price, 2),
            "change_pct"     : round((ens_price - current_price) / current_price * 100, 2),
            "signal"         : "BELI" if ens_price > current_price else "JUAL",
            "date"           : (datetime.now() + timedelta(days=h)).strftime("%Y-%m-%d"),
            "xgb_price"      : xgb_preds[h]["predicted_price"] if h in xgb_preds else None,
            "lstm_price"     : lstm_preds[h]["predicted_price"] if h in lstm_preds else None,
            "model_agreement": len(prices) > 1 and (
                (prices[0] > current_price) == (prices[1] > current_price)
            ),
        }

    return results


# ─────────────────────────────────────────────────────────
#  SINYAL TRADING LENGKAP
# ─────────────────────────────────────────────────────────
def generate_trading_signal(ensemble_preds: dict, current_price: float,
                             indicators_report=None) -> dict:
    """Hasilkan sinyal trading final dengan reasoning."""

    if not ensemble_preds:
        return {"signal": "NETRAL", "confidence": 0.0, "reasoning": []}

    # Ambil prediksi 1 hari dan 7 hari
    p1d  = ensemble_preds.get(1,  {})
    p7d  = ensemble_preds.get(7,  {})
    p30d = ensemble_preds.get(30, {})

    score     = 0.0
    reasoning = []

    # ── Skor dari prediksi ──
    if p1d:
        chg = p1d["change_pct"]
        if chg > 0.5:
            score += 2; reasoning.append(f"✅ Prediksi 1 hari: +{chg:.2f}% (Bullish)")
        elif chg < -0.5:
            score -= 2; reasoning.append(f"❌ Prediksi 1 hari: {chg:.2f}% (Bearish)")
        else:
            reasoning.append(f"➖ Prediksi 1 hari: {chg:+.2f}% (Netral)")

        if p1d.get("model_agreement"):
            score += 0.5; reasoning.append("✅ LSTM & XGBoost sepakat arah")
        else:
            score -= 0.5; reasoning.append("⚠️  LSTM & XGBoost tidak sepakat")

    if p7d:
        chg = p7d["change_pct"]
        if chg > 1.0:
            score += 1.5; reasoning.append(f"✅ Prediksi 7 hari: +{chg:.2f}% (Bullish)")
        elif chg < -1.0:
            score -= 1.5; reasoning.append(f"❌ Prediksi 7 hari: {chg:.2f}% (Bearish)")

    if p30d:
        chg = p30d["change_pct"]
        if chg > 2.0:
            score += 1; reasoning.append(f"✅ Prediksi 30 hari: +{chg:.2f}% (Bullish jangka menengah)")
        elif chg < -2.0:
            score -= 1; reasoning.append(f"❌ Prediksi 30 hari: {chg:.2f}% (Bearish jangka menengah)")

    # ── Tentukan sinyal ──
    max_score = 5.0
    confidence = min(abs(score) / max_score, 1.0)

    if score >= 2.5:
        signal = "BELI KUAT"
    elif score >= 1.0:
        signal = "BELI"
    elif score <= -2.5:
        signal = "JUAL KUAT"
    elif score <= -1.0:
        signal = "JUAL"
    else:
        signal = "NETRAL / TAHAN"

    return {
        "signal"    : signal,
        "score"     : round(score, 2),
        "confidence": round(confidence * 100, 1),
        "reasoning" : reasoning,
    }


# ─────────────────────────────────────────────────────────
#  PRINT LAPORAN LENGKAP
# ─────────────────────────────────────────────────────────
def print_ensemble_report(ensemble_preds, trading_signal, current_price,
                          w_xgb, w_lstm):
    SIG_COLOR = {
        "BELI": Fore.GREEN, "BELI KUAT": Fore.GREEN,
        "JUAL": Fore.RED,   "JUAL KUAT": Fore.RED,
        "NETRAL / TAHAN": Fore.YELLOW,
    }

    print("\n" + "═"*72)
    print(f"  {'═'*68}")
    print(f"  {'🏅  LAPORAN PREDIKSI ENSEMBLE — FULENS  🏅':^68}")
    print(f"  {'═'*68}")
    print("═"*72)

    # Header info
    print(f"\n  Tanggal Prediksi : {datetime.now().strftime('%d %b %Y, %H:%M')}")
    print(f"  Harga Emas Saat Ini : ${current_price:,.2f}")
    print(f"  Model              : XGBoost ({w_xgb*100:.0f}%) + LSTM ({w_lstm*100:.0f}%)")

    # Sinyal utama
    sig_clr = SIG_COLOR.get(trading_signal["signal"], Fore.YELLOW)
    print(f"\n  {'─'*68}")
    print(f"  SINYAL AKHIR  : {sig_clr}{'█'*3} {trading_signal['signal']} {'█'*3}{Style.RESET_ALL}")
    print(f"  Kepercayaan   : {trading_signal['confidence']:.1f}%")
    print(f"  {'─'*68}")

    # Reasoning
    print(f"\n  Dasar Analisis:")
    for r in trading_signal["reasoning"]:
        print(f"    {r}")

    # Tabel prediksi
    print(f"\n  {'─'*68}")
    print(f"  {'Horizon':<10} {'Tanggal':<13} {'Ensemble':>11} {'XGBoost':>10} {'LSTM':>10} {'Range 95%':>18} {'Δ%':>7}")
    print("  " + "─"*68)

    for h, p in ensemble_preds.items():
        clr  = Fore.GREEN if p["signal"] == "BELI" else Fore.RED
        icon = "▲" if p["signal"] == "BELI" else "▼"
        xgb_str  = f"${p['xgb_price']:,.0f}"  if p.get("xgb_price")  else "  N/A "
        lstm_str = f"${p['lstm_price']:,.0f}"  if p.get("lstm_price") else "  N/A "
        agree    = "✓" if p.get("model_agreement") else "✗"
        range_str = f"[{p['lower_bound']:,.0f}–{p['upper_bound']:,.0f}]"

        print(f"  {str(h)+' Hari':<10} {p['date']:<13} "
              f"{clr}${p['predicted_price']:>9,.2f}{Style.RESET_ALL} "
              f"{xgb_str:>10} {lstm_str:>10} "
              f"{range_str:>18} "
              f"{clr}{p['change_pct']:>+6.2f}%{Style.RESET_ALL} {agree}")

    print("\n  Keterangan: ✓ = Kedua model sepakat arah | ✗ = Berbeda arah")
    print("\n" + "═"*72 + "\n")


# ─────────────────────────────────────────────────────────
#  SIMPAN HASIL
# ─────────────────────────────────────────────────────────
def save_predictions(ensemble_preds, trading_signal, current_price):
    result = {
        "generated_at"  : datetime.now().isoformat(),
        "current_price" : current_price,
        "trading_signal": trading_signal,
        "predictions"   : ensemble_preds,
    }
    path = config.DATA_DIR / "latest_predictions.json"
    with open(path, "w") as f:
        json.dump(result, f, indent=2)
    log(f"Prediksi disimpan: {path}", "OK")
    return result


# ─────────────────────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("\n" + "═"*60)
    print("   ⚡ FuLens — Ensemble Prediction")
    print("═"*60 + "\n")

    # 1. Load data & features
    log("Memuat data dan fitur...", "INFO")
    df = load_processed_data()
    df = build_feature_set(df)
    current_price = float(df["gold_close"].iloc[-1])

    # 2. Load model XGBoost
    xgb_preds = {}
    try:
        xgb_model, scaler_X, scaler_y, feature_cols = load_xgb_model()
        xgb_preds, _ = xgb_predict(
            xgb_model, df, scaler_X, scaler_y, feature_cols,
            horizons=[1, 3, 7, 14, 30]
        )
        log("XGBoost loaded ✓", "OK")
    except FileNotFoundError:
        log("XGBoost belum ditraining. Jalankan: python model_xgboost.py", "WARN")

    # 3. Load model LSTM
    lstm_preds = {}
    if TORCH_OK:
        try:
            feat_cols    = joblib.load(config.MODEL_DIR / "feature_cols.pkl")
            scaler_X_    = joblib.load(config.MODEL_DIR / "scaler_X.pkl")
            scaler_y_    = joblib.load(config.MODEL_DIR / "scaler_y.pkl")
            lstm_model   = load_lstm_model(len(feat_cols))
            lstm_preds, _= predict_lstm_future(
                lstm_model, None, scaler_X_, scaler_y_,
                feat_cols, df, horizons=[1, 3, 7, 14, 30]
            )
            log("LSTM loaded ✓", "OK")
        except FileNotFoundError:
            log("LSTM belum ditraining. Jalankan: python model_lstm.py", "WARN")
        except Exception as e:
            log(f"LSTM error: {e}", "WARN")

    # 4. Ensemble
    w_xgb  = config.ENSEMBLE_WEIGHTS["xgboost"]
    w_lstm = config.ENSEMBLE_WEIGHTS["lstm"]

    ensemble_preds = ensemble_predict(xgb_preds, lstm_preds, current_price, w_xgb, w_lstm)

    if not ensemble_preds:
        log("Tidak ada model tersedia. Training dulu!", "ERR")
        exit(1)

    # 5. Sinyal trading
    trading_signal = generate_trading_signal(ensemble_preds, current_price)

    # 6. Tampilkan laporan
    print_ensemble_report(ensemble_preds, trading_signal, current_price, w_xgb, w_lstm)

    # 7. Simpan
    save_predictions(ensemble_preds, trading_signal, current_price)

    log("Ensemble selesai! Lanjut: python api_server.py (Phase 3)", "OK")
