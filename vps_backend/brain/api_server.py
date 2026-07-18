"""
FuLens — API Server (FastAPI)
REST API untuk mengakses prediksi, indikator, dan data emas secara realtime.

Jalankan: python api_server.py
Akses   : http://localhost:8000
Docs    : http://localhost:8000/docs
"""

import warnings
warnings.filterwarnings("ignore")

import json
import asyncio
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

log = logging.getLogger("api_server")

import numpy as np
import pandas as pd
import joblib
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

import config
from data_pipeline import load_processed_data, run_pipeline, load_latest_price
from features import build_feature_set, get_feature_columns
# indicators/strategy tidak lagi dipanggil langsung dari sini — semua endpoint
# analisis lewat signal_engine supaya cuma ada SATU jalur keputusan.

# Multi-simbol (forex/crypto/komoditas) — TA + ML per simbol, multi-timeframe.
import symbols
import timeframes
import signal_engine
import backtest_engine
import market_data
import mt5_feed
import ml_symbol
from fastapi import BackgroundTasks

# Catatan: dulu ada `_use_engine()` yang mengecualikan emas/D1 ke rumus sendiri
# (ind_score×0.5 + pred_score×0.5) — skema pencampuran ketiga yang justru mengenai
# kombinasi default executor. Sudah dihapus; SEMUA simbol/timeframe kini lewat
# signal_engine (satu jalur keputusan: gerbang konfluensi).

# ─────────────────────────────────────────────────────────
#  CEK MODEL TERSEDIA
# ─────────────────────────────────────────────────────────
try:
    import xgboost as xgb
    XGB_OK = True
except ImportError:
    XGB_OK = False

try:
    import torch
    import torch.nn as nn
    TORCH_OK = True
    DEVICE = torch.device("cpu")
except ImportError:
    TORCH_OK = False


# ─────────────────────────────────────────────────────────
#  FASTAPI APP
# ─────────────────────────────────────────────────────────
app = FastAPI(
    title       = "FuLens API",
    description = "API Prediksi Harga Emas — LSTM + XGBoost Ensemble",
    version     = "1.0.0",
    docs_url    = "/docs",
    redoc_url   = "/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins     = ["*"],
    allow_credentials = True,
    allow_methods     = ["*"],
    allow_headers     = ["*"],
)

# ─────────────────────────────────────────────────────────
#  STATE GLOBAL (cache sederhana)
# ─────────────────────────────────────────────────────────
_cache = {
    "df"            : None,
    "df_features"   : None,
    "xgb_model"     : None,
    "lstm_model"    : None,
    "scaler_X"      : None,
    "scaler_y"      : None,
    "feature_cols"  : None,
    "last_update"   : None,
    "predictions"   : None,
    "indicators"    : None,
}

CACHE_TTL = 60  # detik


# ─────────────────────────────────────────────────────────
#  LOAD MODEL
# ─────────────────────────────────────────────────────────
def load_models():
    """Load semua model ke memori."""
    # Scaler & feature cols
    try:
        _cache["scaler_X"]     = joblib.load(config.MODEL_DIR / "scaler_X.pkl")
        _cache["scaler_y"]     = joblib.load(config.MODEL_DIR / "scaler_y.pkl")
        _cache["feature_cols"] = joblib.load(config.MODEL_DIR / "feature_cols.pkl")
    except FileNotFoundError:
        print("⚠ Scaler belum ada — jalankan model_xgboost.py dulu")
        return

    # XGBoost
    if XGB_OK:
        try:
            m = xgb.XGBRegressor()
            m.load_model(str(config.MODEL_DIR / "xgboost_model.json"))
            _cache["xgb_model"] = m
            print("✓ XGBoost loaded")
        except Exception as e:
            print(f"⚠ XGBoost load error: {e}")

    # LSTM
    if TORCH_OK:
        try:
            from model_lstm import GoldLSTM
            ckpt  = torch.load(str(config.MODEL_DIR / "lstm_model.pt"), map_location=DEVICE)
            model = GoldLSTM(ckpt["input_size"], ckpt["hidden_sizes"], ckpt["dropout"])
            model.load_state_dict(ckpt["model_state"])
            model.eval()
            _cache["lstm_model"] = model
            print("✓ LSTM loaded")
        except Exception as e:
            print(f"⚠ LSTM load error: {e}")


def _merge_live_gold_d1(df: pd.DataFrame) -> pd.DataFrame:
    """Sisipkan bar D1 emas TERBARU (yfinance live) ke df dari CSV.

    Emas+D1 memakai pipeline ML yang membaca `gold_processed.csv` statis — file itu
    hanya diperbarui saat `python data_pipeline.py` dijalankan, sehingga harga/teknikal
    D1 bisa tertinggal berhari-hari (mis. berhenti 12 Juni) padahal timeframe intraday
    yang live sudah terkini. Di sini kita ambil bar D1 live lalu:
      • perbarui bar terakhir yang sudah ada (candle hari berjalan bisa berubah), dan
      • tambahkan bar baru setelah tanggal terakhir CSV.
    Kolom fundamental (dxy/cpi/...) di baris baru di-ffill dari nilai terakhir agar
    fitur ML tetap terbentuk. Bila apa pun gagal, kembalikan df apa adanya (fallback
    ke perilaku lama). HANYA menyentuh tanggal ≥ bar terakhir CSV → histori lama utuh.
    """
    try:
        live = market_data.get_ohlc(symbols.DEFAULT, "D1")
        if live is None or len(live) == 0:
            return df
        live = live.copy()
        idx = pd.to_datetime(live.index)
        try:
            idx = idx.tz_localize(None)
        except (TypeError, AttributeError):
            pass
        live.index = idx.normalize()

        df = df.copy()
        gcols = ["gold_open", "gold_high", "gold_low", "gold_close", "gold_volume"]
        others = [c for c in df.columns if c not in gcols]
        cutoff = df.index.max()

        for ts, row in live[live.index >= cutoff].iterrows():
            if ts in df.index:                       # perbarui bar terakhir
                for c in gcols:
                    if c in df.columns and c in live.columns and not pd.isna(row[c]):
                        df.at[ts, c] = float(row[c])
            else:                                    # tambah bar baru
                new_row = {c: np.nan for c in df.columns}
                for c in gcols:
                    if c in live.columns and not pd.isna(row[c]):
                        new_row[c] = float(row[c])
                df.loc[ts] = new_row

        df = df.sort_index()
        if others:
            df[others] = df[others].ffill()          # fundamental ikut nilai terakhir
        return df
    except Exception as e:
        print(f"⚠ Refresh bar D1 emas gagal (pakai CSV): {e}")
        return df


def load_data_cache():
    """Load dan cache data + features."""
    now = datetime.now()
    if (_cache["last_update"] is None or
        (now - _cache["last_update"]).seconds > CACHE_TTL):
        try:
            df = load_processed_data()
            df = _merge_live_gold_d1(df)          # jaga bar D1 tetap terkini
            df_feat = build_feature_set(df)
            _cache["df"]          = df
            _cache["df_features"] = df_feat
            _cache["last_update"] = now
        except Exception as e:
            print(f"⚠ Cache update error: {e}")


# ─────────────────────────────────────────────────────────
#  HELPER PREDIKSI
# ─────────────────────────────────────────────────────────
def _make_predictions(horizons=[1, 3, 7, 14, 30]) -> dict:
    """Jalankan ensemble prediction dan return hasilnya."""
    df    = _cache.get("df_features")
    sX    = _cache.get("scaler_X")
    sy    = _cache.get("scaler_y")
    fcols = _cache.get("feature_cols")

    if df is None or sX is None or fcols is None:
        return {}

    cur = float(df["gold_close"].iloc[-1])

    # Bersihkan data
    last_data = df[fcols].copy().ffill().bfill()
    last_data = last_data.replace([np.inf, -np.inf], 0).fillna(0)

    def project(daily_ret, decay, h_list):
        results = {}
        for h in h_list:
            cum = 0.0; r = daily_ret
            for _ in range(h):
                cum += r; r *= decay
            price = float(np.clip(cur*(1+cum), cur*(1-0.005*h), cur*(1+0.005*h)))
            results[h] = round(price, 2)
        return results

    xgb_preds = lstm_preds = {}

    # XGBoost
    if _cache["xgb_model"] and len(last_data) > 0:
        try:
            row = sX.transform(last_data.iloc[-1:].values)
            p1  = float(sy.inverse_transform([[_cache["xgb_model"].predict(row)[0]]])[0][0])
            dr  = float(np.clip((p1 - cur) / cur, -0.03, 0.03))
            xgb_preds = project(dr, 0.60, horizons)
        except Exception as e:
            print(f"XGB predict error: {e}")

    # LSTM
    if _cache["lstm_model"] and len(last_data) > 0:
        try:
            lb  = min(config.LSTM_LOOKBACK, max(5, len(last_data) // 4))
            seq = sX.transform(last_data.values[-lb:])
            xt  = torch.FloatTensor(seq[np.newaxis]).to(DEVICE)
            with torch.no_grad():
                p1_s = _cache["lstm_model"](xt).cpu().numpy()[0]
            p1   = float(sy.inverse_transform([[p1_s]])[0][0])
            dr   = float(np.clip((p1 - cur) / cur, -0.025, 0.025))
            lstm_preds = project(dr, 0.80, horizons)
        except Exception as e:
            print(f"LSTM predict error: {e}")

    # Ensemble
    w_x = config.ENSEMBLE_WEIGHTS["xgboost"]
    w_l = config.ENSEMBLE_WEIGHTS["lstm"]
    results = {}
    for h in horizons:
        prices, weights = [], []
        if h in xgb_preds:  prices.append(xgb_preds[h]);  weights.append(w_x)
        if h in lstm_preds: prices.append(lstm_preds[h]); weights.append(w_l)
        if not prices:
            continue
        w_arr = np.array(weights) / sum(weights)
        ens   = float(np.dot(prices, w_arr))
        std   = np.std(prices) if len(prices) > 1 else ens * 0.015
        results[str(h)] = {
            "horizon_days"    : h,
            "date"            : (datetime.now() + timedelta(days=h)).strftime("%Y-%m-%d"),
            "predicted_price" : round(ens, 2),
            "lower_95"        : round(ens - 1.96 * std, 2),
            "upper_95"        : round(ens + 1.96 * std, 2),
            "change_usd"      : round(ens - cur, 2),
            "change_pct"      : round((ens - cur) / cur * 100, 2),
            "signal"          : "BELI" if ens > cur else "JUAL",
            "xgb_price"       : xgb_preds.get(h),
            "lstm_price"      : lstm_preds.get(h),
            "model_agreement" : bool(
                h in xgb_preds and h in lstm_preds and
                (xgb_preds[h] > cur) == (lstm_preds[h] > cur)
            ),
        }
    return {"current_price": cur, "predictions": results,
            "generated_at": datetime.now().isoformat()}


# ─────────────────────────────────────────────────────────
#  STARTUP
# ─────────────────────────────────────────────────────────
@app.on_event("startup")
async def startup():
    print("\n🏅 FuLens API Server starting...")
    load_models()
    load_data_cache()

    # Hangatkan cache OHLC di latar belakang. Tanpa ini, request PERTAMA untuk
    # tiap (simbol, timeframe) harus menunggu unduhan yfinance yang bisa puluhan
    # detik → proxy eksekutor timeout → 502. Prewarm menanggung biaya itu di awal,
    # saat belum ada yang menunggu. Simbol yang dieksekusi bot didahulukan.
    hot = ["XAUUSD", "EURUSD", "GBPUSD", "USDJPY", "XAGUSD",
           "AUDUSD", "BTCUSD", "ETHUSD"]
    pairs = [(s, tf) for s in hot for tf in timeframes.all_timeframes()]
    market_data.prewarm(pairs)
    print(f"● Prewarm cache berjalan di latar belakang ({len(pairs)} pasangan)...")

    print("✓ Server siap di http://localhost:8000")
    print("✓ Dokumentasi  : http://localhost:8000/docs\n")


# ─────────────────────────────────────────────────────────
#  ENDPOINTS
# ─────────────────────────────────────────────────────────

# ── ROOT ──────────────────────────────────────────────────
@app.get("/", tags=["Info"])
def root():
    return {
        "app"      : "FuLens — Gold Price Prediction API",
        "version"  : "1.0.0",
        "status"   : "running",
        "endpoints": {
            "price"      : "/api/v1/price",
            "predict"    : "/api/v1/predict",
            "indicators" : "/api/v1/indicators",
            "multitf"    : "/api/v1/indicators/multitimeframe",
            "fundamental": "/api/v1/fundamental",
            "history"    : "/api/v1/history",
            "signal"     : "/api/v1/signal",
            "refresh"    : "/api/v1/refresh",
            "docs"       : "/docs",
        }
    }


# ── HARGA REALTIME ────────────────────────────────────────
@app.get("/api/v1/price", tags=["Harga"])
def get_price(symbol: str = symbols.DEFAULT, timeframe: str = "D1"):
    """Harga terkini simbol (dari data EA bila ada, jika tidak yfinance)."""
    if not symbols.exists(symbol):
        raise HTTPException(400, f"Simbol tidak dikenal: {symbol}")
    data = signal_engine.price(symbol, timeframe)
    if not data:
        raise HTTPException(503, "Data belum tersedia")
    return data


# ── PREDIKSI AI ────────────────────────────────────────────
@app.get("/api/v1/predict", tags=["Prediksi"])
def get_prediction(horizons: str = "1,3,7,14,30", symbol: str = symbols.DEFAULT):
    """
    Prediksi harga menggunakan Ensemble LSTM + XGBoost (khusus EMAS).
    Simbol lain mengembalikan proyeksi berbasis sinyal teknikal.

    - **horizons**: hari ke depan, pisahkan dengan koma (contoh: 1,3,7,14,30)
    - **symbol**: simbol yang diprediksi (default XAUUSD)
    """
    if not symbols.exists(symbol):
        raise HTTPException(400, f"Simbol tidak dikenal: {symbol}")
    if symbols.normalize(symbol) != symbols.DEFAULT:
        s = signal_engine.signal(symbol)
        if not s:
            raise HTTPException(503, "Data belum tersedia")
        has_ml = ml_symbol.has_model(symbol, "D1")
        return {
            "symbol": s["symbol"],
            "current_price": s["current_price"],
            "predictions": {},          # ML arah-harga per-simbol (bukan level harga)
            "overall_signal": s["signal"],
            "generated_at": datetime.now().isoformat(),
            "model_info": {"xgboost_ready": has_ml, "lstm_ready": False,
                           "engine": s["source"],
                           "ml_probability": s.get("ml_probability")},
            "note": ("Prediksi level harga (LSTM+XGBoost) khusus emas. Simbol ini "
                     "memakai sinyal teknikal" + (" + ML arah." if has_ml else ".")),
        }

    load_data_cache()
    h_list = [int(x.strip()) for x in horizons.split(",") if x.strip().isdigit()]
    if not h_list:
        raise HTTPException(400, "Format horizons tidak valid. Contoh: 1,3,7,14,30")

    result = _make_predictions(h_list)
    if not result:
        raise HTTPException(503, "Model belum tersedia. Jalankan training dulu.")

    # Tentukan sinyal keseluruhan
    preds = result["predictions"]
    p1    = preds.get("1", {})
    p7    = preds.get("7", {})
    score = 0
    if p1.get("change_pct", 0) > 0.3:  score += 2
    elif p1.get("change_pct", 0) < -0.3: score -= 2
    if p7.get("change_pct", 0) > 1:    score += 1
    elif p7.get("change_pct", 0) < -1:  score -= 1

    overall = ("BELI KUAT" if score >= 2 else "BELI" if score > 0
               else "JUAL KUAT" if score <= -2 else "JUAL" if score < 0
               else "NETRAL")

    result["overall_signal"]  = overall
    result["model_info"] = {
        "xgboost_weight": config.ENSEMBLE_WEIGHTS["xgboost"],
        "lstm_weight"   : config.ENSEMBLE_WEIGHTS["lstm"],
        "xgboost_ready" : _cache["xgb_model"] is not None,
        "lstm_ready"    : _cache["lstm_model"] is not None,
    }
    return result


# ── INDIKATOR TEKNIKAL ─────────────────────────────────────
@app.get("/api/v1/indicators", tags=["Teknikal"])
def get_indicators(symbol: str = symbols.DEFAULT, timeframe: str = "D1",
                   mode: str = "auto"):
    """Nilai 4 komponen + status gerbang konfluensi.

    `mode`: "auto" (dipilih dari timeframe) / "scalping" / "swing".
    """
    if not symbols.exists(symbol):
        raise HTTPException(400, f"Simbol tidak dikenal: {symbol}")
    data = signal_engine.indicators(symbol, timeframe, mode)
    if not data:
        raise HTTPException(503, "Data belum tersedia")
    return data


# ── MULTI-TIMEFRAME ─────────────────────────────────────────
@app.get("/api/v1/indicators/multitimeframe", tags=["Teknikal"])
def get_multitimeframe(symbol: str = symbols.DEFAULT, timeframe: str = "D1"):
    """Setup per timeframe (15m hingga 1Y).

    Perhatikan flag `synthetic` di tiap baris: TF di bawah 1D datanya DIKARANG
    (data harian + noise acak) karena brain masih bersumber yfinance harian —
    lihat peringatan di indicators.TIMEFRAMES. Jangan dipakai untuk keputusan
    sampai EA MQL5 mengirim OHLC asli per timeframe.
    """
    if not symbols.exists(symbol):
        raise HTTPException(400, f"Simbol tidak dikenal: {symbol}")
    data = signal_engine.multitimeframe(symbol, timeframe)
    if not data:
        raise HTTPException(503, "Data belum tersedia")
    return data


# ── DATA FUNDAMENTAL ──────────────────────────────────────
@app.get("/api/v1/fundamental", tags=["Fundamental"])
def get_fundamental():
    """Data fundamental: DXY, VIX, yield, minyak, dll."""
    load_data_cache()
    df = _cache.get("df")
    if df is None:
        raise HTTPException(503, "Data belum tersedia")

    def safe_val(col, n=2):
        if col in df.columns:
            v = df[col].dropna()
            return round(float(v.iloc[-1]), n) if len(v) > 0 else None
        return None

    def safe_chg(col):
        if col in df.columns:
            s = df[col].dropna()
            if len(s) >= 2:
                return round(float((s.iloc[-1] - s.iloc[-2]) / s.iloc[-2] * 100), 2)
        return None

    return {
        "timestamp": str(df.index[-1].date()),
        "data": {
            "dxy"       : {"value": safe_val("dxy"),     "change_pct": safe_chg("dxy"),     "unit": "index",   "impact": "inverse"},
            "vix"       : {"value": safe_val("vix"),     "change_pct": safe_chg("vix"),     "unit": "index",   "impact": "positive"},
            "bond10y"   : {"value": safe_val("bond10y"), "change_pct": safe_chg("bond10y"), "unit": "%",       "impact": "inverse"},
            "oil_wti"   : {"value": safe_val("oil"),     "change_pct": safe_chg("oil"),     "unit": "USD/bbl", "impact": "positive"},
            "sp500"     : {"value": safe_val("sp500"),   "change_pct": safe_chg("sp500"),   "unit": "index",   "impact": "inverse"},
            "cpi"       : {"value": safe_val("cpi"),     "change_pct": safe_chg("cpi"),     "unit": "%",       "impact": "positive"},
            "fed_rate"  : {"value": safe_val("fed_rate"),"change_pct": safe_chg("fed_rate"),"unit": "%",       "impact": "inverse"},
        },
        "note": "impact = arah korelasi terhadap harga emas (positive=searah, inverse=berlawanan)"
    }


# ── HISTORY ───────────────────────────────────────────────
@app.get("/api/v1/history", tags=["Data"])
def get_history(days: int = 90, symbol: str = symbols.DEFAULT, timeframe: str = "D1"):
    """
    Data historis harga (OHLC).

    - **days**: jumlah bar ke belakang (default: 90)
    - **symbol**: simbol (default XAUUSD)
    - **timeframe**: M15/M30/H1/H4/D1/W1 (default D1)
    """
    if not symbols.exists(symbol):
        raise HTTPException(400, f"Simbol tidak dikenal: {symbol}")
    data = signal_engine.history(symbol, days, timeframe)
    if not data:
        raise HTTPException(503, "Data belum tersedia")
    return data


# ── SINYAL RINGKAS ─────────────────────────────────────────
@app.get("/api/v1/signal", tags=["Prediksi"])
def get_signal(symbol: str = symbols.DEFAULT, timeframe: str = "D1",
               mode: str = "auto"):
    """Sinyal trading ringkas untuk tampilan di app & eksekutor.

    `mode`: "auto" (dipilih dari timeframe) / "scalping" / "swing".
    """
    if not symbols.exists(symbol):
        raise HTTPException(400, f"Simbol tidak dikenal: {symbol}")
    data = signal_engine.signal(symbol, timeframe, mode)
    if not data:
        raise HTTPException(503, "Data belum tersedia")

    # Prediksi ensemble (emas D1 saja — hanya simbol ini yang punya model LSTM+
    # XGBoost terlatih). Dilampirkan sebagai INFORMASI untuk ditampilkan di app
    # dan masuk ke `reasons` executor. Ia TIDAK ikut menentukan arah maupun
    # confidence — itu tugas gerbang konfluensi + veto ml_symbol di signal_engine.
    if (symbols.normalize(symbol) == symbols.DEFAULT
            and timeframes.normalize(timeframe) == "D1"):
        try:
            load_data_cache()
            preds = _make_predictions([1, 7]).get("predictions", {})
            data["prediction_1d"] = preds.get("1", {}).get("change_pct")
            data["prediction_7d"] = preds.get("7", {}).get("change_pct")
        except Exception as e:
            log.warning("Prediksi ensemble gagal dilampirkan: %s", e)

    return data


# ── INGESTION OHLC DARI EA (mata) ──────────────────────────
class OhlcBar(BaseModel):
    time: float | str        # epoch detik atau ISO string
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


class OhlcPush(BaseModel):
    symbol: str
    timeframe: str
    bars: list[OhlcBar]


@app.post("/api/v1/ohlc", tags=["Data"])
def push_ohlc(payload: OhlcPush):
    """Terima bar OHLC yang didorong EA dari terminal MT5.

    Begitu data ini masuk, market_data.get_ohlc memilihnya lebih dulu daripada
    yfinance — seluruh otak (gerbang, S&R, ML) beralih ke harga broker asli.
    EA sebaiknya mengirim ≥150 bar tertutup terakhir agar indikator (squeeze
    percentile butuh 100, S&R butuh histori) punya cukup data.
    """
    if not symbols.exists(payload.symbol):
        raise HTTPException(400, f"Simbol tidak dikenal: {payload.symbol}")
    bars = [b.model_dump() for b in payload.bars]
    stored = mt5_feed.ingest(payload.symbol, payload.timeframe, bars)
    return {
        "symbol": symbols.normalize(payload.symbol),
        "timeframe": timeframes.normalize(payload.timeframe),
        "received": len(bars),
        "stored": stored,
    }


@app.get("/api/v1/ohlc/status", tags=["Data"])
def ohlc_status():
    """Key OHLC-EA yang terisi + umur & jumlah bar (untuk cek EA masih mengirim)."""
    return {"feeds": mt5_feed.status()}


# ── REFRESH DATA ───────────────────────────────────────────
@app.post("/api/v1/refresh", tags=["Admin"])
async def refresh_data(background_tasks: BackgroundTasks):
    """Paksa update data terbaru dari Yahoo Finance."""
    def _refresh():
        run_pipeline()
        load_data_cache()
    background_tasks.add_task(_refresh)
    return {"status": "refresh dimulai di background", "message": "Data akan diperbarui dalam ~30 detik"}


# ── DAFTAR SIMBOL ──────────────────────────────────────────
@app.get("/api/v1/symbols", tags=["Info"])
def get_symbols():
    """Daftar simbol yang didukung + status model ML (untuk selector di aplikasi)."""
    out = []
    for s in symbols.all_symbols():
        item = dict(s)
        item["ml"] = bool(s["ml"]) or ml_symbol.has_model(s["symbol"], "D1")
        out.append(item)
    return {"default": symbols.DEFAULT, "symbols": out}


@app.get("/api/v1/timeframes", tags=["Info"])
def get_timeframes():
    """Timeframe yang didukung (untuk dropdown di aplikasi)."""
    return {"default": timeframes.DEFAULT, "timeframes": timeframes.all_timeframes()}


# ── BACKTEST ───────────────────────────────────────────────
@app.get("/api/v1/backtest", tags=["Prediksi"])
def get_backtest(symbol: str = symbols.DEFAULT, timeframe: str = "D1",
                 days: int = 365, start: str | None = None,
                 end: str | None = None, strategy: str = "ta"):
    """Backtest per simbol (hybrid testing).

    - **timeframe**: M15/M30/H1/H4/D1/W1
    - **start/end**: 'YYYY-MM-DD' (opsional; jika kosong pakai `days` terakhir)
    - **strategy**: 'ta' (teknikal) atau 'ml' (XGBoost per simbol bila sudah dilatih)
    """
    if not symbols.exists(symbol):
        raise HTTPException(400, f"Simbol tidak dikenal: {symbol}")
    result = backtest_engine.run(symbol, timeframe, days, start, end, strategy)
    if not result:
        raise HTTPException(503,
            "Data tidak tersedia untuk parameter ini. Untuk timeframe intraday "
            "(M15/M30) Yahoo hanya menyediakan ~60 hari terakhir; pilih D1/W1 "
            "atau rentang tanggal yang lebih baru.")
    return result


# ── TRAIN ML PER SIMBOL ────────────────────────────────────
@app.post("/api/v1/train", tags=["Admin"])
def train_symbol(background_tasks: BackgroundTasks,
                 symbol: str = symbols.DEFAULT, timeframe: str = "D1"):
    """Latih ulang model ML per simbol (berjalan di background)."""
    if not symbols.exists(symbol):
        raise HTTPException(400, f"Simbol tidak dikenal: {symbol}")
    background_tasks.add_task(ml_symbol.train, symbol, timeframe)
    return {"status": "training dimulai di background",
            "symbol": symbols.normalize(symbol),
            "timeframe": timeframes.normalize(timeframe)}


# ── HEALTH CHECK ───────────────────────────────────────────
@app.get("/health", tags=["Info"])
def health():
    return {
        "status"     : "ok",
        "timestamp"  : datetime.now().isoformat(),
        "models"     : {
            "xgboost": _cache["xgb_model"] is not None,
            "lstm"   : _cache["lstm_model"] is not None,
        },
        "data_loaded": _cache["df"] is not None,
        "last_update": str(_cache["last_update"]) if _cache["last_update"] else None,
    }


# ─────────────────────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("\n" + "═"*60)
    print("   🏅 FuLens — API Server")
    print("═"*60)
    print(f"\n  URL    : http://localhost:{config.API_PORT}")
    print(f"  Docs   : http://localhost:{config.API_PORT}/docs")
    print(f"  Health : http://localhost:{config.API_PORT}/health")
    print("\n  Tekan Ctrl+C untuk berhenti\n")
    print("═"*60 + "\n")

    uvicorn.run(
        "api_server:app",
        host   = config.API_HOST,
        port   = config.API_PORT,
        reload = False,
        log_level = "info",
    )
