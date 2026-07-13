"""
FuLens — Konfigurasi Utama
Isi API keys kamu di sini setelah daftar gratis.
"""

import os
from pathlib import Path

# ─────────────────────────────────────────
#  API KEYS  (isi setelah daftar gratis)
# ─────────────────────────────────────────
FRED_API_KEY        = "4f3bb9f175399d1ba3c210c01dba5415 "        # https://fred.stlouisfed.gov
ALPHA_VANTAGE_KEY   = "6S8A2T5MNA6K2FRC"    # https://alphavantage.co
# Yahoo Finance tidak perlu key

# ─────────────────────────────────────────
#  SIMBOL & TICKER
# ─────────────────────────────────────────
GOLD_TICKER     = "GC=F"      # Gold Futures (Yahoo Finance)
DXY_TICKER      = "DX-Y.NYB"  # Dollar Index
OIL_TICKER      = "CL=F"      # Crude Oil WTI
SP500_TICKER    = "^GSPC"     # S&P 500
VIX_TICKER      = "^VIX"      # VIX Fear Index
BOND10Y_TICKER  = "^TNX"      # US 10Y Treasury Yield

# FRED Series IDs (data fundamental dari Federal Reserve)
FRED_SERIES = {
    "CPI"           : "CPIAUCSL",   # Consumer Price Index
    "PPI"           : "PPIACO",     # Producer Price Index
    "FED_RATE"      : "FEDFUNDS",   # Federal Funds Rate
    "UNEMPLOYMENT"  : "UNRATE",     # Tingkat Pengangguran
    "GDP"           : "GDP",        # Gross Domestic Product
    "M2"            : "M2SL",       # Money Supply M2
    "REAL_RATE"     : "REAINTRATREARAT10Y",  # Real Interest Rate
}

# ─────────────────────────────────────────
#  PARAMETER DATA
# ─────────────────────────────────────────
LOOKBACK_DAYS   = 730    # Ambil 2 tahun data historis
PREDICTION_DAYS = 30     # Prediksi 30 hari ke depan
UPDATE_INTERVAL = 60     # Update data setiap 60 detik

# ─────────────────────────────────────────
#  PARAMETER MODEL AI
# ─────────────────────────────────────────
LSTM_LOOKBACK       = 90     # LSTM melihat 90 hari ke belakang
LSTM_EPOCHS         = 100    # Epoch training
LSTM_BATCH_SIZE     = 32
LSTM_UNITS          = [128, 64, 32]   # Layer units
LSTM_DROPOUT        = 0.2

XGBOOST_PARAMS = {
    "n_estimators"    : 500,
    "max_depth"       : 6,
    "learning_rate"   : 0.01,
    "subsample"       : 0.8,
    "colsample_bytree": 0.8,
    "random_state"    : 42,
}

ENSEMBLE_WEIGHTS = {
    "lstm"    : 0.60,   # LSTM lebih unggul untuk time-series
    "xgboost" : 0.40,
}

# ─────────────────────────────────────────
#  PARAMETER INDIKATOR TEKNIKAL
# ─────────────────────────────────────────
INDICATOR_PARAMS = {
    "RSI_PERIOD"        : 14,
    "MACD_FAST"         : 12,
    "MACD_SLOW"         : 26,
    "MACD_SIGNAL"       : 9,
    "BB_PERIOD"         : 20,
    "BB_STD"            : 2,
    "EMA_SHORT"         : 20,
    "EMA_MED"           : 50,
    "EMA_LONG"          : 200,
    "SMA_SHORT"         : 50,
    "SMA_LONG"          : 200,
    "STOCH_K"           : 14,
    "STOCH_D"           : 3,
    "ATR_PERIOD"        : 14,
    "CCI_PERIOD"        : 20,
    "WILLIAMS_PERIOD"   : 14,
    "ADX_PERIOD"        : 14,
    "ICHIMOKU_9"        : 9,
    "ICHIMOKU_26"       : 26,
    "ICHIMOKU_52"       : 52,
}

# ─────────────────────────────────────────
#  PATHS
# ─────────────────────────────────────────
BASE_DIR        = Path(__file__).parent
DATA_DIR        = BASE_DIR / "data"
RAW_DIR         = DATA_DIR / "raw"
PROCESSED_DIR   = DATA_DIR / "processed"
MODEL_DIR       = BASE_DIR / "models"
LOG_DIR         = BASE_DIR / "logs"

# Buat folder otomatis jika belum ada
for d in [RAW_DIR, PROCESSED_DIR, MODEL_DIR, LOG_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# ─────────────────────────────────────────
#  API SERVER
# ─────────────────────────────────────────
# FuLens kini jadi "otak" internal di belakang gateway eksekutor.
# Hanya diakses oleh backend eksekutor (localhost), TIDAK diekspos ke internet.
# Flutter tidak lagi bicara langsung ke port ini — semua lewat gateway :8000.
API_HOST    = "127.0.0.1"   # loopback: hanya proses lokal di VPS yang bisa akses
API_PORT    = 8500          # port internal FuLens (gateway eksekutor tetap 8000)
API_PREFIX  = "/api/v1"

# ─────────────────────────────────────────
#  SINYAL THRESHOLD
# ─────────────────────────────────────────
SIGNAL_THRESHOLDS = {
    "RSI_OVERSOLD"      : 30,
    "RSI_OVERBOUGHT"    : 70,
    "CONFIDENCE_BUY"    : 0.65,   # Min confidence untuk sinyal beli
    "CONFIDENCE_SELL"   : 0.65,
}
