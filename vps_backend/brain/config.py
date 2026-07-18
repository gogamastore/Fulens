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
# Hanya 4 komponen strategi + ATR. Indikator lama (RSI/CCI/Williams/ROC/ADX/
# PSAR/Ichimoku/OBV/EMA/SMA) sudah dibuang: mereka memberi ilusi konfirmasi —
# lima di antaranya (EMA20/50/200, SMA50/200) mengukur hal yang sama persis.
# ATR TETAP ADA tapi bukan komponen sinyal: risk_manager memakainya untuk lot
# dan jarak SL/TP, jadi jangan dihapus.
INDICATOR_PARAMS = {
    "MACD_FAST"         : 12,
    "MACD_SLOW"         : 26,
    "MACD_SIGNAL"       : 9,
    "BB_PERIOD"         : 20,
    "BB_STD"            : 2,
    "STOCH_K"           : 14,
    "STOCH_D"           : 3,
    "ATR_PERIOD"        : 14,
    # EMA200 dikembalikan — TAPI perannya beda dari dulu. Dulu ia salah satu dari
    # 16 PEMILIH (dan bersama 4 MA lain mendominasi voting sehingga setup reversal
    # mustahil menang). Sekarang ia satu GERBANG khusus: penentu sisi tren.
    # Ini satu-satunya komponen yang menjawab "kita di sisi mana dari tren besar?"
    # — BB/Stoch/MACD/S&R semuanya turunan harga jangka pendek.
    # Terukur cukup dengan 200 bar (keputusan sisi harga identik dgn histori penuh).
    "EMA_TREND"         : 200,
}

# ─────────────────────────────────────────
#  PARAMETER STRATEGI (gerbang konfluensi)
# ─────────────────────────────────────────
# Rantai gerbang (AND, dinilai pada bar TERTUTUP):
#   SWING    : Stochastic cross -> Tren EMA200 -> Sentuh S&R
#   SCALPING : Stochastic cross -> BB Squeeze
#
# Dua mode sengaja BERBEDA PERAN, bukan versi cepat/lambat dari hal yang sama:
#   swing    = ikut tren besar, masuk saat koreksi menyentuh S&R (BUY-only saat
#              uptrend, SELL-only saat downtrend — itu memang maksudnya)
#   scalping = tidak peduli tren, menunggu kompresi volatilitas lalu ikut arah
#              Stochastic (seimbang BUY/SELL — cari profit harian dua arah)
#
# Gerbang "Ruang BB" (%B) SUDAH DIPENSIUNKAN dari kedua mode. Ia menolak BUY saat
# harga mepet pita atas dengan logika mean-reversion, padahal digandeng filter
# tren setupnya justru momentum continuation — dua premis yang bertabrakan.
# Terukur: trade yang DIBLOKIR olehnya justru yang terbaik (80% win, +0.87R, nol
# timeout) sementara yang diloloskan cuma +0.48R. Ia membuang trade terbaik.
STRATEGY_PARAMS = {
    # ── Stochastic (konfirmasi momentum, kedua mode) ─────
    # Yang WAJIB hanya arah cross: %K > %D untuk BUY, %K < %D untuk SELL.
    # Zona jenuh TIDAK memblokir — ia hanya menaikkan skor kualitas. Alasannya
    # terukur: pada 352 bar emas D1, %K di pivot sisi BUY min 31 / median 34,
    # jadi syarat wajib "%K < 20" LOLOS NOL KALI dan membuat strategi SELL-only.
    "STOCH_OVERSOLD"     : 20,    # dipakai untuk SKOR, bukan gerbang
    "STOCH_OVERBOUGHT"   : 80,
    "STOCH_ZONE_NEUTRAL" : 50,    # titik netral untuk menghitung skor zona

    # ── MACD ─────────────────────────────────────────────
    # Swing menuntut cross yang masih baru (pelatuk pengaman); scalping cukup
    # searah (butuh kecepatan, cross terlalu jarang bertemu syarat lain).
    "MACD_CROSS_MAX_AGE" : 2,     # swing: cross wajib ≤ N bar lalu

    # ── Support & Resistance (khusus SWING) ──────────────
    "SR_PIVOT_WINDOW"    : 5,     # fractal window pendeteksi swing high/low
    "SR_MIN_GAP_PCT"     : 0.3,   # jarak minimal antar level agar tak berdempet
    "SR_TOUCH_ATR"       : 0.5,   # dianggap "menyentuh" bila ≤ N×ATR dari level
    # Sentuhan S&R adalah JENDELA, bukan titik. Strateginya berurutan — "harga
    # membentur S&R, LALU tunggu MACD cross". Menuntut keduanya di bar yang SAMA
    # membuat keduanya saling meniadakan; terukur: BUY nol dari 352 bar.
    "SR_TOUCH_LOOKBACK"  : 5,     # sentuhan sah bila terjadi ≤ N bar terakhir

    # ── Bollinger Bands: SQUEEZE (khusus SCALPING) ───────
    # Gerbang lolos bila lebar BB berada di bawah persentil ke-N dari lebar
    # dirinya sendiri selama BB_SQUEEZE_WINDOW bar terakhir. Pita menyempit =
    # volatilitas terkompresi = pasar menabung tenaga sebelum bergerak.
    #
    # Gerbang ini NETRAL ARAH — ia menyaring "kapan layak masuk", bukan "ke mana".
    # Itu yang bikin scalping bisa seimbang BUY/SELL, sementara gerbang tren
    # (EMA200) secara definisi mengunci satu arah saja.
    #
    # Persentil, bukan ambang mutlak dalam pips: lebar BB berbeda drastis antar
    # simbol (BTCUSD vs XAUUSD) dan antar rezim volatilitas. Persentil relatif
    # terhadap diri sendiri otomatis menyesuaikan — pelajaran yang sama dengan
    # kenapa zona Stochastic 20/80 tak dipakai sebagai gerbang.
    #
    # p50 dipilih dari uji ke depan (emas D1, SL/TP ditelusuri bar demi bar).
    # Yang meyakinkan bukan angkanya, tapi DATARANNYA: p20..p70 semuanya positif
    # di kedua rezim (bullish +0.25..+0.34R, datar +0.34..+0.48R). Kalau ini hasil
    # mencocok-cocokkan angka, tetangga p50 akan jeblok — nyatanya tidak.
    "BB_SQUEEZE_PCTILE"  : 50,
    "BB_SQUEEZE_WINDOW"  : 100,

    # ── Pelabelan ────────────────────────────────────────
    # quality ≥ ini → "BELI KUAT"/"JUAL KUAT". Dibaca executor lewat
    # require_strong (fulens_client._map_signal mencari substring "KUAT").
    "STRONG_QUALITY"     : 80.0,
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
#  ML SEBAGAI VETO (bukan penentu arah)
# ─────────────────────────────────────────
# Dulu: final = 0.5 × skor_TA + 0.5 × skor_ML → tak ada satu pun syarat yang
# benar-benar wajib, sinyalnya jadi lembek. Sekarang arah 100% dari gerbang
# konfluensi; ML hanya menyaring.
#
# `agree` = probabilitas ML yang SEARAH dengan setup (untuk BUY = prob naik,
# untuk SELL = 1 − prob naik).
ML_VETO = {
    "BLOCK_BELOW" : 0.40,   # agree < ini → entry diblokir total
    "FULL_ABOVE"  : 0.55,   # agree ≥ ini → quality utuh
    # Di antara keduanya: quality dikali faktor MIN_FACTOR..1.0 (interpolasi
    # linear), jadi min_confidence di executor otomatis jadi saringan kedua.
    "MIN_FACTOR"  : 0.70,
}

# Catatan: SIGNAL_THRESHOLDS lama (RSI_OVERSOLD/RSI_OVERBOUGHT/CONFIDENCE_*)
# dihapus — RSI sudah tidak ikut strategi, dan ambang confidence sekarang dipegang
# `min_confidence` di executor (backend eksekutor/config.py), bukan di brain.

# ─────────────────────────────────────────
#  MEKANIKA RISIKO (jarak SL/TP)
# ─────────────────────────────────────────
# Otak memberi JARAK SL/TP (harga) dari ATR; EA menghitung lot dari equity live ÷
# jarak SL. Keputusan (arah + jarak) di otak, ukuran lot (butuh equity) di EA.
# Mult di sini SATU tempat — jangan diduplikasi di input EA (itu sumber drift).
RISK_PARAMS = {
    "SL_ATR_MULT": 1.5,   # SL = 1.5 × ATR
    # TP diturunkan 2.5 → 2.0 berdasarkan uji ke depan (emas D1, SL/TP nyata
    # ditelusuri bar demi bar). TP 2.5 terlalu jauh: 38% trade habis waktu tanpa
    # menyentuh TP maupun SL di periode non-tren, dan ekspektansi NEGATIF (−0.11R).
    # Dengan TP 2.0 ekspektansi positif di KEDUA rezim (+0.61R bullish, +0.13R
    # datar). Memperpendek TP menaikkan ambang impas (37%→43%), tapi kenaikan win
    # rate-nya lebih besar. Ini terbukti lebih menentukan daripada pilihan indikator.
    "TP_ATR_MULT": 2.0,
}
