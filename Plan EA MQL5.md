# Plan EA MQL5 — FuLens Hybrid (EA = Tangan + Mata, Python = Otak + Gerbang)

> **Revisi total.** Versi lama dokumen ini mendeskripsikan EA STANDALONE yang
> menghitung sendiri BB squeeze, divergence, MACD cross, dan S&R di dalam MQL5.
> Itu dibatalkan — bertentangan dengan arsitektur yang sudah dibangun (gerbang
> konfluensi 4 komponen ada di `vps_backend/brain/strategy.py`). Membangun ulang
> deteksi divergence di MQL5 jauh lebih sulit daripada di pandas, dan akan membuang
> seluruh kerja otak. EA di sini **tipis**: tidak punya strategi.

## Prinsip

- **Otak (Python, `brain/`)** — satu-satunya pembuat keputusan. Menghitung 4
  gerbang, menentukan BUY/SELL/NETRAL + kualitas, memberi level SL/TP (jarak ATR)
  dan S&R. ML jadi veto. Sudah selesai & teruji.
- **EA (MQL5)** — **tangan + mata**. Tidak menghitung strategi apa pun.
  - MATA: kirim OHLC bar tertutup dari terminal ke otak (lewat gerbang).
  - TANGAN: polling sinyal, hitung lot dari equity live, eksekusi order, trailing,
    lalu **laporkan** posisi/akun/fill balik ke gerbang.
- **Gerbang (Python, `executor/main.py`)** — satu pintu untuk Flutter DAN untuk EA.
  Menyimpan state yang dilaporkan EA, mem-proxy analisis ke otak. Loopback otak
  tetap tertutup dari internet.

## Kenapa ini sekaligus memperbaiki 3 bug yang sudah ditemukan

Begitu otak menerima OHLC MT5 asli dari EA, ketiganya lenyap tanpa kerja tambahan:

1. **Futures-vs-spot** — otak berhenti pakai yfinance `GC=F`; ia menilai harga spot
   broker yang sama dengan yang dieksekusi.
2. **Data M15 sintetis** — `_resample_to_tf` (data harian + noise acak) tidak
   dipakai lagi; M15 jadi OHLC M15 asli.
3. **scalp.py jadi benar-benar usang** — cek EMA/ER/volume-nya (satu-satunya
   pemeriksa harga riil saat ini) tinggal dipindah jadi gerbang di otak, karena
   otak akhirnya melihat harga riil. Sampai EA ada, scalp.py DIPERTAHANKAN sebagai
   jaring pengaman (dorman di config default D1).

## Arsitektur target

```
Flutter ──HTTP/WS──►  GERBANG :8000 (executor/main.py)
                        │   ▲
        proxy analisis  │   │  state EA (posisi/akun/fill) disimpan di sini
                        ▼   │
                     OTAK :8500 (brain, loopback)
                        ▲   │
                 OHLC   │   │  sinyal (arah + kualitas + SL/TP + S&R)
                        │   ▼
                    EA (MQL5) di terminal MT5
                    • OnBar: kirim OHLC bar tertutup  ──► gerbang ──► otak
                    • polling GET sinyal              ◄── gerbang ◄── otak
                    • hitung lot dari equity, kirim order (CTrade)
                    • trailing stop
                    • laporkan posisi/akun/fill        ──► gerbang
```

EA bicara HANYA ke gerbang :8000 (prinsip satu pintu, sama seperti Flutter) —
supaya otak tetap loopback dan EA bisa di VPS broker yang berbeda.

## Perubahan per komponen

### A. OTAK (`brain/`) — jadikan MT5 sumber data

1. **Endpoint terima OHLC** — `POST /api/v1/ohlc` (body: symbol, timeframe, array
   bar OHLCV). Simpan per `(symbol, tf)` di memori/disk.
2. **`market_data.get_ohlc`** — bila ada data MT5 tersimpan untuk `(symbol, tf)`,
   PAKAI ITU; yfinance cuma fallback saat data MT5 belum masuk. Ini titik tunggal
   yang membuat seluruh otak (gerbang, S&R, ML) beralih ke harga riil.
3. **Sinyal sertakan mekanika risiko** — tambah `sl_distance`/`tp_distance` (dalam
   harga, dari ATR × mult) ke respons `/signal`, supaya EA tak perlu hitung ATR
   sendiri. Arah & level = keputusan otak; ukuran lot = mekanika EA (butuh equity
   live). `atr` sudah dihitung otak; tinggal diekspos.

### B. GERBANG (`executor/`) — dari eksekutor MT5 jadi penyimpan state

Ini perubahan terbesar. Sekarang tiap endpoint Flutter membaca `engine.mt5`
(library MetaTrader5 Python). Setelah EA jadi tangan, itu dicabut:

1. **Hapus** `MT5Connector`, loop `BotEngine`, `risk_manager`, `trade_executor`,
   `strategy/scalp.py` — semua peran eksekusi pindah ke EA. (lot-calc `risk_manager`
   pindah ke EA; SL/TP dari otak.)
2. **Endpoint untuk EA:**
   - `POST /ea/ohlc` → teruskan ke otak `POST /api/v1/ohlc`.
   - `GET  /ea/signal?symbol=&timeframe=&mode=` → teruskan ke otak `/api/v1/signal`
     (mode dari `BotSettings.trading_mode` — sudah ada).
   - `POST /ea/report` → EA kirim akun + posisi terbuka + fill terakhir; gerbang
     simpan sebagai state terkini.
4. **Endpoint Flutter dibaca-ulang dari state EA** (bukan `engine.mt5`):
   - `/status`, `/positions`, `/history`, `/signals` → dari state laporan EA.
   - `/positions/{ticket}/close`, `/bot/start`, `/bot/stop` → jadi PERINTAH yang
     dititipkan untuk EA (EA menariknya saat polling), karena Python tak lagi
     memegang koneksi MT5.
   - `/ws` → dipublish saat laporan EA masuk (trade_opened/closed/account).
5. `BotSettings` sebagian besar tetap (symbols, timeframe, trading_mode,
   min_confidence, require_strong, scaling, risk_percent, sl/tp mult, trailing,
   proteksi). Yang khusus scalp.py (`scalp_*`, `entry_timing_*`) dihapus.

### C. EA (MQL5) — file baru `FuLensEA.mq5`

**Input (bisa dioptimasi di backtest):**
- Koneksi: `GatewayUrl` (`http://<vps>:8000`), `ApiKey`, `Symbol`, `Timeframe`,
  `PollSeconds`.
- Risiko: `RiskPercent`, `MaxPositions`, `MagicNumber`. (SL/TP datang dari otak.)
- `TradingMode` (auto/scalping/swing) — diteruskan sebagai query, bukan dihitung.

**Alur (semua di penutupan bar, `Bar 1` — hindari repaint):**
```
OnTick:
  if (bar baru terbentuk):
      1. kirim N bar OHLC terakhir  → POST /ea/ohlc
      2. GET /ea/signal             → {direction, confidence, sl, tp, ...}
      3. tarik perintah tertunda (close/stop) dari respons, jalankan
      4. jika actionable (confidence ≥ min, arah valid):
           lot = EquityRisk(RiskPercent, sl_distance)
           CTrade.Buy/Sell(lot, sl, tp)
      5. kelola trailing stop
      6. POST /ea/report  (akun + posisi + fill)
```

**Catatan MQL5:**
- `WebRequest()` sinkron & memblokir thread tick — semua URL harus di-whitelist
  manual di terminal (Tools → Options → Expert Advisors → Allow WebRequest).
  Karena itu polling di penutupan bar, bukan tiap tick.
- Tidak ada WebSocket native — EA polling; Flutter tetap dapat realtime via `/ws`
  gerbang yang dipublish saat `/ea/report` masuk.
- `CTrade` untuk order. 1 magic number per EA. Baca `Bar 1`, bukan `Bar 0`.

## Urutan pengerjaan (milestone)

1. ✅ **SELESAI — Otak terima OHLC** (A1–A3). `brain/mt5_feed.py` (store + cache CSV,
   upsert, deteksi basi→fallback); `market_data.get_ohlc` prefer data EA; `POST
   /api/v1/ohlc` + `GET /api/v1/ohlc/status`; sinyal menyertakan `atr`/`sl_distance`/
   `tp_distance` (config.RISK_PARAMS). Teruji dengan simulasi ingest.
2. ✅ **SELESAI — Gerbang EA-driven** (B2–B4). `executor/ea_state.py` (state +
   pub/sub WS + antrean perintah + history dari fill); `main.py` ditulis ulang jadi
   EA-driven — **tak lagi impor MetaTrader5** (bisa jalan di OS apa pun); endpoint
   `POST /ea/sync` (respons FLAT untuk MQL5); endpoint Flutter dibaca dari state EA;
   perintah close dititip untuk EA. `fulens_client` parse sl/tp + `push_ohlc`.
3. ✅ **SELESAI — EA MQL5 + simulator** (C). `ea/FuLensEA.mq5` (tangan+mata: push
   OHLC, poll rencana, lot dari equity, buka/tutup/flip, trailing, lapor fill);
   `ea/sim_ea.py` (uji pipa tanpa MT5); `ea/README.md` (runbook demo). v1: satu
   entry/simbol, satu simbol/EA. **← siap diuji di DEMO (lihat ea/README.md).**
4. ⬜ **Cabut MT5Connector & bot_engine** (B1) — SETELAH EA terbukti di demo. File
   dorman sekarang (tak diimpor), belum dihapus agar jalur lama masih ada bila perlu.
5. ⬜ **Pindah cek EMA/ER/volume scalp.py jadi gerbang otak** (pasca-EA) — lalu hapus
   scalp.py. Sekaligus scaling/pyramiding (v1 EA baru satu entry).

## Keputusan yang sudah diambil (2026-07-18)

- **Lot dihitung di EA.** Otak cukup memberi jarak SL/TP (dari ATR); EA menghitung
  lot dari equity live × RiskPercent ÷ jarak SL. Mekanika di tangan, keputusan di
  otak.
- **Perintah close/stop: hibrida per horizon.**
  - SWING (TF besar) → dititip di respons poll; EA menariknya tiap penutupan bar.
    Jeda ≤ interval bar wajar untuk swing.
  - SCALPING / harian (TF kecil) → EA polling interval SANGAT PENDEK (mis. 1–3 dtk)
    supaya perintah nyaris real-time.

    ⚠️ Catatan MQL5: EA TIDAK bisa menerima push — `WebRequest()` cuma keluar,
    tidak ada server HTTP di dalam EA. Jadi "push" di sini = polling cepat, bukan
    server mengirim ke EA. `PollSeconds` dibuat kecil saat TradingMode scalping.
    (Konsekuensi: `WebRequest` sinkron memblokir thread tick — polling terlalu
    agresif bisa membuat EA tersendat; uji intervalnya di DEMO.)
