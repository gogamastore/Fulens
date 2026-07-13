# FuLens VPS Backend (bundel siap pindah)

Satu folder berisi **dua service** yang jalan bersama di VPS Windows:

```
vps_backend/
├── brain/        ← OTAK FuLens (ML) — FastAPI di 127.0.0.1:8500 (internal)
│   ├── api_server.py, config.py, data_pipeline.py, features.py,
│   │   indicators.py, ensemble.py, model_lstm.py, model_xgboost.py
│   ├── data/     ← data terproses (dibawa, agar tak perlu unduh ulang)
│   └── models/   ← model terlatih (XGBoost + LSTM + scaler)
├── executor/     ← GERBANG eksekutor (MT5) — FastAPI di 0.0.0.0:8000 (publik)
│   ├── main.py, config.py, bot_engine.py, fulens_client.py,
│   │   mt5_connector.py, risk_manager.py, trade_executor.py
│   └── strategy/ ← indicators.py (hanya ATR untuk lot/SL/TP)
├── setup.ps1     ← buat venv + install dependency (jalankan sekali)
└── run_all.ps1   ← jalankan kedua service
```

> **Model hybrid:** `brain` menghasilkan sinyal (arah), `executor` mengeksekusi ke MT5.
> Flutter cukup terhubung ke **satu pintu**: `http://<VPS>:8000` (+ header `X-API-Key`).
> `brain` hanya loopback `127.0.0.1:8500` — **jangan** buka port 8500 di firewall.

## Prasyarat VPS
- **Windows** (library `MetaTrader5` hanya jalan di Windows).
- **Python 3.11+** terpasang & ada di PATH.
- **Terminal MetaTrader 5** terpasang dan **sudah login** ke akun broker
  (atau isi `MT5_LOGIN/PASSWORD/SERVER` di `executor/config.py`).

## Langkah pakai
```powershell
# 1. Sekali di awal: buat venv & install dependency untuk kedua service
./setup.ps1

# 2. Jalankan keduanya (dua jendela terpisah)
./run_all.ps1
```
Cek: buka `http://<VPS>:8000/health` — harus `fulens_reachable: true` & `mt5_connected: true`
setelah bot di-start dari aplikasi.

## Menjalankan manual (opsional)
```powershell
# Otak (internal 8500)
cd brain ; .\venv\Scripts\activate ; python api_server.py
# Gerbang (publik 8000) — jendela lain
cd executor ; .\venv\Scripts\activate ; python main.py
```

## WAJIB sebelum online
1. Ganti `ServerConfig.API_KEY` di `executor/config.py` (dan samakan di app Flutter
   `lib/config/app_config.dart`).
2. Buka **hanya port 8000** di firewall; idealnya di balik HTTPS (Caddy/Nginx) atau Tailscale.
3. **Uji di akun DEMO dulu.**

## Melatih ML per simbol (agar backtest & sinyal akurat)
Model XGBoost per simbol dilatih dari data yfinance. Jalankan di folder `brain`:
```powershell
cd brain ; .\venv\Scripts\activate
python train_symbols.py                 # semua simbol, timeframe D1
python train_symbols.py --tf D1,H1      # beberapa timeframe
python train_symbols.py --symbols EURUSD,BTCUSD --tf H1
```
Model tersimpan di `brain/models/sym_<SIMBOL>_<TF>_xgb.json`. Ulangi berkala
(mis. mingguan) agar belajar data terbaru. Bisa juga via API:
`POST /api/v1/train?symbol=EURUSD&timeframe=D1` (berjalan di background).

Setelah dilatih, sinyal simbol itu memakai **blend TA + ML**, dan backtest
strategi **ml** aktif. Emas (XAUUSD, D1) tetap memakai ensemble LSTM+XGBoost lama.

## Endpoint baru (ringkas)
- `GET /api/v1/symbols` — daftar simbol + flag `ml`
- `GET /api/v1/timeframes` — M15/M30/H1/H4/D1/W1
- semua analisis menerima `?symbol=&timeframe=`
- `GET /api/v1/backtest?symbol=&timeframe=&start=&end=&strategy=ta|ml`
- `POST /api/v1/train?symbol=&timeframe=`

## Data pertama kali (jika `brain/data` kosong / ingin refresh)
```powershell
cd brain ; .\venv\Scripts\activate ; python data_pipeline.py
```
Cakupan sinyal FuLens saat ini: **EMAS (XAUUSD)**. Eksekutor default trading XAUUSD saja.
