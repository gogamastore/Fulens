# FuLens Hybrid — Integrasi Otak (FuLens) + Eksekutor (MT5)

Model **hybrid**: FuLens (Python/ML) = **otak** yang menghasilkan sinyal; backend
**Eksekutor** = **tangan** yang mengeksekusi ke MetaTrader 5. Flutter cukup terhubung
ke **satu pintu** (gerbang eksekutor `:8000`).

```
┌──────────────────────────────────────────────┐
│  FLUTTER (Android / Web / Windows)            │
│  Analisis · Sinyal · Posisi · Kontrol Bot     │
└───────────────┬──────────────────────────────┘
                │ http://<VPS>:8000  (+ X-API-Key)  &  ws://<VPS>:8000/ws?key=…
┌───────────────▼──────────────────────────────┐
│  EKSEKUTOR  (FastAPI, port 8000) — GERBANG    │
│  • /status /bot/* /positions /history /ws     │  ← trading (lokal)
│  • /api/v1/*  ──proxy──►  FuLens              │  ← analisis (diteruskan)
│  • bot_engine: ambil sinyal FuLens → MT5      │
└───────┬───────────────────────────┬───────────┘
        │ MetaTrader5 (IPC)         │ httpx (localhost:8500)
┌───────▼─────────┐        ┌────────▼──────────────────────┐
│ Terminal MT5    │        │  FuLENS (FastAPI, port 8500)   │
│ (Windows/VPS)   │        │  LSTM+XGBoost — sinyal EMAS     │
└─────────────────┘        └────────────────────────────────┘
```

> **Penting:** FuLens sekarang hanya "otak". Eksekutor **tidak punya strategi lagi** —
> seluruh keputusan arah (BUY/SELL/NETRAL) datang dari `GET /api/v1/signal` FuLens.
> FuLens saat ini hanya bersinyal **EMAS (XAUUSD)**, jadi default eksekutor
> `symbols = ["XAUUSD"]`.

## Menjalankan di VPS Windows

Butuh **Windows** (library `MetaTrader5` hanya jalan di Windows, satu mesin dengan terminal MT5).

### 1. Otak FuLens (internal, port 8500)
```powershell
cd "Backend Fulens"
python -m venv venv ; venv\Scripts\activate
pip install -r requirements.txt
python data_pipeline.py          # sekali di awal: unduh & proses data
python api_server.py             # jalan di 127.0.0.1:8500 (loopback, tidak publik)
```
`config.py` FuLens sudah diset `API_HOST="127.0.0.1"`, `API_PORT=8500`.

### 2. Eksekutor / gerbang (publik, port 8000)
```powershell
cd "backend eksekutor"
python -m venv venv ; venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000
```
Pastikan **terminal MT5 sudah login** (atau isi `ServerConfig.MT5_LOGIN/PASSWORD/SERVER`
di `config.py`). Klik **Start Bot** dari aplikasi (atau `POST /bot/start`).

### 3. Aplikasi Flutter
Edit [lib/config/app_config.dart](lib/config/app_config.dart): set `host` ke IP VPS dan
`apiKey` sama dengan `ServerConfig.API_KEY`. Lalu:
```powershell
flutter pub get
flutter run       # atau: flutter build apk / web / windows
```

## Keamanan (wajib sebelum publik)
- **Ganti `ServerConfig.API_KEY`** di `backend eksekutor/config.py` (nilai contoh jangan dipakai).
- FuLens (8500) **loopback saja** — jangan buka port 8500 di firewall VPS.
- Buka hanya port **8000**; idealnya di belakang HTTPS (Caddy/Nginx) atau Tailscale/VPN.
- **Uji di akun DEMO dulu.**

## Alur keputusan (ringkas)
1. Tiap `loop_interval` detik, eksekutor `fetch_signal()` → FuLens `/api/v1/signal`.
2. `BELI[/KUAT]`→BUY, `JUAL[/KUAT]`→SELL, `NETRAL`→flat, disaring `min_confidence`.
3. Lot & SL/TP dihitung dari **ATR** (mekanika risiko, bukan keputusan arah).
4. Balik arah → tutup posisi lawan; NETRAL → tutup (opsi `close_on_neutral`).
5. Trailing stop + stop trading bila drawdown harian ≥ `max_daily_drawdown_pct`.

Semua parameter di atas dapat diubah lewat `PUT /settings` (layar Settings Flutter).

## Memperluas cakupan (roadmap)
FuLens hanya emas/harian. Untuk simbol/timeframe lain, perluas FuLens agar
mengeluarkan sinyal per-simbol (mis. `GET /api/v1/signal?symbol=EURUSD`) —
eksekutor sudah siap lewat `FulensConfig.SYMBOL_MAP` dan `fetch_signal(symbol)`.
