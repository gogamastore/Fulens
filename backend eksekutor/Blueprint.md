# Arsitektur Bot Trading MetaTrader 5

## Gambaran Umum

Sistem terdiri dari 3 lapisan. Flutter tidak bisa terhubung langsung ke MT5, sehingga backend Python menjadi jembatan.

```
┌──────────────────────────────────────────────┐
│  FLUTTER APP (Android / Web / Windows)       │
│  Dashboard · Sinyal · Posisi · Settings      │
└───────────────┬──────────────────────────────┘
                │ REST API + WebSocket (realtime)
┌───────────────▼──────────────────────────────┐
│  BACKEND PYTHON (FastAPI)                    │
│  ┌────────────────────────────────────────┐  │
│  │ Bot Engine (loop utama)                │  │
│  │  1. Ambil data dari Fulens backend utama        │  │
│  │  2. Hitung indikator + price action    │  │
│  │  3. Cek filter berita                  │  │
│  │  4. Skor confluence → keputusan entry  │  │
│  │  5. Risk manager → lot, SL, TP (ATR)   │  │
│  │  6. Eksekusi order + trailing stop     │  │
│  └────────────────────────────────────────┘  │
└───────────────┬──────────────────────────────┘
                │ Library python MetaTrader5 (IPC)
┌───────────────▼──────────────────────────────┐
│  TERMINAL MT5 (Windows / VPS Windows)        │
│  Koneksi ke broker: forex, emas, saham,      │
│  indeks, crypto (semua simbol Market Watch)  │
└──────────────────────────────────────────────┘
```

Catatan penting: library `MetaTrader5` untuk Python hanya berjalan di **Windows**, di mesin yang sama dengan terminal MT5. Untuk operasi 24 jam, jalankan backend + MT5 di VPS Windows. Aplikasi Flutter bisa mengakses dari mana saja.

## Komponen Backend

| Modul | File | Tanggung Jawab |
|---|---|---|
| MT5 Connector | `mt5_connector.py` | Inisialisasi/login MT5, ambil OHLC multi-timeframe, info akun & simbol |
| Indikator | `strategy/indicators.py` | EMA, RSI, MACD, ATR, Stochastic — dihitung dengan pandas/numpy |
| Price Action | `strategy/price_action.py` | Swing high/low, Break of Structure (BOS), order block, engulfing/pinbar |
| Multi-Timeframe | `strategy/multi_timeframe.py` | Skor confluence: trend H4/H1 harus searah dengan sinyal M15/M5 |
| Filter Berita | `strategy/news_filter.py` | Kalender ekonomi (Forex Factory JSON) — blok entry ±30 menit sekitar berita high-impact |
| Risk Manager | `risk_manager.py` | Lot dari % risiko akun; SL = 1.5×ATR, TP = 2.5×ATR (configurable); trailing stop; batas drawdown harian |
| Executor | `trade_executor.py` | Kirim order market, modifikasi SL/TP, tutup posisi |
| Bot Engine | `bot_engine.py` | Loop per simbol; menyatukan semua modul; publish event ke WebSocket |
| API | `main.py` | REST (start/stop, settings, posisi, riwayat) + WebSocket (sinyal, equity realtime) |

## Logika Keputusan Entry (Confluence Scoring)

Setiap simbol dievaluasi tiap candle baru. Skor 0–100 dari beberapa konfirmasi:

| Konfirmasi | Bobot | Kriteria BUY (SELL kebalikannya) |
|---|---|---|
| Trend timeframe besar | 25 | H1 & M30: EMA50 > EMA200, harga di atas EMA50 |
| Momentum | 20 | RSI M15 naik melewati zona 35–50, MACD cross up |
| Price action | 25 | BOS bullish, reaksi order block demand, atau engulfing bullish |
| Volatilitas layak | 15 | ATR di atas ambang minimum (hindari pasar mati) |
| Filter berita | 15 | Tidak ada berita high-impact ±30 menit |

Entry hanya jika skor ≥ ambang (default 70) **dan** arah timeframe selaras. Setiap keputusan disimpan dengan alasan lengkap (`reasons[]`) sehingga aplikasi menampilkan **kenapa bot entry** — transparansi penuh.

## Risk Management

- Risiko per transaksi: default 1% equity (configurable per simbol).
- SL awal: `entry ∓ 1.5 × ATR(14)` — otomatis menyesuaikan volatilitas tiap pasar (emas vs forex vs crypto beda jarak).
- TP: `entry ± 2.5 × ATR(14)` → risk:reward ≈ 1 : 1.67 (configurable).
- Trailing stop: setelah profit ≥ 1×ATR, SL digeser mengikuti harga dengan jarak 1×ATR.
- Proteksi: maksimal N posisi bersamaan; stop trading jika drawdown harian melewati batas (default 10%).

## Komponen Flutter

```
lib/
├── main.dart                   # Entry, routing, theme
├── config/app_config.dart      # URL backend
├── models/                     # Signal, Position, AccountInfo, BotSettings
├── services/
│   ├── api_service.dart        # REST (http)
│   └── ws_service.dart         # WebSocket realtime + auto-reconnect
├── providers/bot_provider.dart # State management (provider)
└── screens/
    ├── dashboard_screen.dart   # Equity, status bot, start/stop
    ├── signals_screen.dart     # Riwayat sinyal + alasan entry
    ├── positions_screen.dart   # Posisi terbuka, P/L realtime, tutup manual
    └── settings_screen.dart    # Simbol aktif, risiko %, ambang skor, ATR multiplier
```

Target platform: Android, Web, Windows (satu codebase).

## Alur Data Realtime

1. Bot engine menghasilkan event: `signal`, `trade_opened`, `trade_closed`, `account`.
2. FastAPI broadcast lewat WebSocket `/ws`.
3. Flutter `ws_service` menerima → update provider → UI langsung berubah.

## Keamanan

- Backend memakai API key (header `X-API-Key`) — wajib diganti sebelum diekspos ke internet.
- Akses dari luar VPS: pakai HTTPS (reverse proxy Caddy/Nginx) atau VPN/Tailscale.
- **Selalu uji di akun demo dulu.**

## Roadmap

1. **Tahap 1 (scaffold ini):** koneksi MT5, strategi confluence, eksekusi + ATR SL/TP, aplikasi monitoring.
2. **Tahap 2:** backtesting engine, jurnal trading, notifikasi push.
3. **Tahap 3:** filter sentimen tambahan, optimasi parameter per simbol, analisis AI opsional.

## Update tambahan Tahap 1:
- Sinyal Muncul dengan panduan Live Chart Syncfusion Flutter sebagai Gambaran Keputusan menggunakan pemetaan menggunakan Fibonanci
- C:\Users\USER\fulens_app\backend eksekutor MT5 kita ambil hanya trade_executor.py nya, tapi kita modifikasi agar bot ini hanya mengambil signal keputusan pada signal dari fulens.
- 
