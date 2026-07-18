# FuLens EA — Runbook Uji Demo

EA = **tangan + mata**. Semua keputusan dari otak Python; EA cuma kirim OHLC,
eksekusi, dan lapor balik. Urutan uji dari yang paling aman ke live-demo.

## Komponen & port

```
Flutter ─► Gerbang :8000 (executor/main.py)  ─► Otak :8500 (brain/api_server.py)
                 ▲
                 │  POST /ea/sync (OHLC + state)  ◄─► rencana + perintah
              EA MQL5 (di terminal MT5, akun DEMO)
```

## 1. Jalankan otak (:8500)

```powershell
cd vps_backend\brain
python -m venv venv ; venv\Scripts\activate
pip install -r requirements.txt
python api_server.py            # loopback 127.0.0.1:8500
```

## 2. Jalankan gerbang (:8000)

```powershell
cd vps_backend\executor
python -m venv venv ; venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000
```

> Gerbang kini TAK butuh MetaTrader5 Python lib lagi — jadi bisa jalan di OS apa
> pun. (`requirements.txt` executor masih menyebut MetaTrader5 dari arsitektur
> lama; boleh dibiarkan sampai cleanup, tak dipakai jalur EA.)

## 3. Uji pipa TANPA MT5 dulu (sim_ea.py)

Ini membuktikan otak + gerbang benar sebelum menyentuh MQL5:

```powershell
cd vps_backend\ea
python sim_ea.py --gateway http://127.0.0.1:8000 --key <API_KEY> `
                 --symbol XAUUSD --timeframe D1 `
                 --csv ..\brain\data\processed\gold_processed.csv
```

Yang harus terjadi:
- Otak menerima OHLC (cek `GET /api/v1/ohlc/status` → ada entri XAUUSD/D1).
- Gerbang membalas rencana: `signal`, `target`, `actionable`, `sl_distance`,
  `tp_distance`, checklist `reasons`.
- Baris "Yang akan dilakukan EA" merangkum aksinya.

Cek juga dari Flutter/curl: `GET /status` (harus `mt5_connected: true` karena
sim baru saja sync), `GET /signals` (keputusan tercatat).

## 4. Pasang EA di MT5 (akun DEMO)

1. **Whitelist URL gerbang** — MT5 → Tools → Options → Expert Advisors →
   centang **Allow WebRequest for listed URL** → tambahkan `http://<ip-vps>:8000`
   (persis, termasuk port). Tanpa ini `WebRequest` balas -1.
2. Salin `FuLensEA.mq5` ke `MQL5\Experts\` (folder data terminal:
   File → Open Data Folder). Compile di MetaEditor (F7).
3. Buka chart simbol yang diinginkan (mis. XAUUSD), set periodenya sesuai
   `SignalTF` yang akan dipakai.
4. Drag `FuLensEA` ke chart. Isi input:
   - `GatewayUrl` = `http://<ip-vps>:8000`
   - `ApiKey` = sama dengan `ServerConfig.API_KEY`
   - `FeedTimeframes` = timeframe yang **didorong** ke otak
     (default `M1,M5,M15,M30,H1,H4,D1,W1`). Makin lengkap, makin banyak layar
     analisis Flutter yang memakai harga broker asli. Kurangi bila ingin ringan.
   - Centang **Allow Algo Trading**.

   > **EA tidak menentukan apa pun soal strategi.** Mode (swing/scalping) DAN
   > timeframe eksekusi diatur dari aplikasi Flutter. EA hanya: dorong data
   > semua timeframe (mata) + jalankan perintah (tangan). Periode chart tempat
   > EA dipasang tidak berpengaruh — yang menentukan simbol hanyalah chart-nya.

## Siapa menentukan apa

| Hal | Ditentukan oleh |
|---|---|
| Simbol yang ditradingkan | chart tempat EA dipasang |
| Timeframe yang **dieksekusi** | Flutter → Bot Trading → *Timeframe Eksekusi* |
| Mode (swing / scalping) | Flutter → Bot Trading → *Mode Kerja Otak* |
| Timeframe yang **didorong** (data) | input `FeedTimeframes` di EA |
| Ukuran lot | EA (dari equity live ÷ jarak SL yang diberi otak) |
| Arah + jarak SL/TP | otak (gerbang konfluensi) |
5. Pastarkan akun **DEMO**. Amati tab Experts untuk log siklus.

## Dua irama: push bar-tertutup + poll cepat

EA bicara ke gerbang lewat DUA jalur, dan ini penting untuk latensi:

| Kapan | Kirim OHLC? | Untuk apa |
|---|---|---|
| **Bar tertutup** (`OnTick`) | ya — hanya timeframe yang barusan menutup bar | data baru untuk otak (mata) |
| **Tiap `PollSeconds`** (`OnTimer`) | tidak (`feeds: []`) | ambil rencana + perintah manual |

Saat start, EA mendorong **semua** timeframe sekali (bootstrap). Setelah itu
hanya yang bar-nya baru tertutup — biasanya 1 timeframe per menit. Feed yang
gagal terkirim ditandai dan **dicoba lagi** otomatis, jadi data tidak bolong.

Tanpa poll cepat, EA hanya bicara saat bar tertutup — di H1 **sekali sejam**,
di D1 **sekali sehari**. Akibatnya perintah "tutup posisi" dari Flutter dan
perubahan setelan (ganti mode/risk) baru sampai satu bar kemudian. Poll ringan
menutup celah itu tanpa membebani jaringan (tidak mengirim ulang 200 bar).

`PollSeconds = 5` cukup untuk kebanyakan kasus. Set `0` untuk kembali ke
perilaku bar-close saja. Jangan terlalu agresif: `WebRequest` MQL5 **sinkron**
dan memblokir thread tick — itu sebabnya `PollTimeoutMs` sengaja pendek (3 dtk).

## Alur satu siklus EA

1. Kirim akun + posisi + fill (+ OHLC bila bar baru) → `POST /ea/sync`.
2. Terima rencana (arah, actionable, jarak SL/TP) + `close_tickets`.
3. Jalankan perintah manual (tutup tiket dari Flutter).
4. Terapkan rencana: NETRAL→tutup, balik arah→tutup lawan, actionable→buka
   (lot dari equity ÷ jarak SL). v1: satu entry per simbol.
5. Trailing stop.

## Batasan v1 (sengaja, untuk membuktikan pipa dulu)

- **Satu entry per simbol** — belum ada scaling/pyramiding (ada di roadmap otak).
- **Satu simbol per EA** — pasang EA di tiap chart simbol yang mau ditradingkan.
- **Push = polling bar** — `WebRequest` sinkron; untuk scalping perkecil timeframe
  (bukan menambah timer agresif yang bisa menyendat tick).
- Perintah close/stop lewat polling (jeda ≤ 1 bar). Cukup untuk swing.

## Jika bermasalah

| Gejala | Sebab paling mungkin |
|---|---|
| `WebRequest error 4060/-1` | URL belum di-whitelist, atau salah port |
| Gerbang balas 401 | `ApiKey` EA ≠ `ServerConfig.API_KEY` |
| `signal` selalu NETRAL | belum ada setup lolos gerbang (normal) — cek `reasons` |
| `sl_distance` null | ATR belum siap (bar < ~60) — kirim lebih banyak bar |
| `/status` mt5_connected false | EA belum sync / berhenti — cek log Experts |
