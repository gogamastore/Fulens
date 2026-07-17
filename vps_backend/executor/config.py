"""Konfigurasi backend EKSEKUTOR.

Peran: penghubung MURNI ke MT5. Tidak ada lagi "otak"/strategi di sini —
seluruh keputusan arah (BUY/SELL/NETRAL) datang dari backend FuLens (ML).
Eksekutor hanya: ambil sinyal FuLens → hitung lot/SL/TP (ATR) → kirim ke MT5,
lalu kelola trailing stop & proteksi drawdown.

Nilai di `BotSettings` adalah DEFAULT PABRIK. Setelan yang diubah lewat aplikasi
(PUT /settings) disimpan ke `bot_settings.json` di folder ini dan dimuat kembali
saat start — lihat load_settings()/save_settings() di bawah.
"""
import json
import logging
from pathlib import Path

from pydantic import BaseModel, ValidationError

log = logging.getLogger("config")


class BotSettings(BaseModel):
    # Simbol yang dipantau/dieksekusi (nama simbol broker MT5 Anda).
    # FuLens kini bersinyal multi-aset: emas, forex, crypto, komoditas.
    symbols: list[str] = [
        "XAUUSD", "XAGUSD", "EURUSD", "GBPUSD", "USDJPY",
        "AUDUSD", "BTCUSD", "ETHUSD",
    ]

    # ── Mode eksekusi ────────────────────────────────────────────────
    # "auto"     : eksekusi sinyal untuk SEMUA simbol di `symbols`.
    # "selected" : hanya eksekusi `selected_symbol` (fokus satu simbol).
    execution_mode: str = "auto"
    selected_symbol: str = "XAUUSD"

    # Timeframe sinyal FuLens yang diikuti bot (M15/M30/H1/H4/D1/W1).
    # Sinyal & arah dihitung otak pada timeframe ini.
    signal_timeframe: str = "D1"

    # ── Gerbang keputusan dari FuLens ────────────────────────────────
    # Sinyal FuLens: "BELI KUAT" / "BELI" / "NETRAL" / "JUAL" / "JUAL KUAT".
    min_confidence: float = 50.0      # confidence minimum FuLens (0-100) untuk entry
    require_strong: bool = False      # True = hanya entry pada "BELI KUAT"/"JUAL KUAT"
    close_on_neutral: bool = True     # tutup posisi saat FuLens berubah NETRAL
    close_on_flip: bool = True        # tutup posisi lama saat arah FuLens berbalik

    # ── Entry bertahap per simbol (scaling) ──────────────────────────
    # Entry-1 selalu butuh sinyal valid + timing stochastic (M15). Entry ke-k
    # ditambah saat harga sudah bergerak ≥ (k-1)×add_step_atr×ATR dari entry-1;
    # ARAH gerakan yang dituntut tergantung `scaling_mode`:
    #
    #  • "pyramid"      → tambah saat posisi PROFIT (BUY: harga naik; SELL: turun).
    #                     Menambah ke posisi yang sudah terbukti benar — risiko
    #                     lebih terkendali karena entry baru lahir dari kemenangan.
    #  • "average_down" → tambah saat harga MELAWAN (BUY: turun; SELL: naik).
    #                     Memperbaiki harga rata-rata (DCA), TAPI menumpuk lot pada
    #                     posisi rugi (gaya martingale) — drawdown bisa membesar
    #                     cepat saat tren melawan terus. Ini perilaku lama.
    #  • "off"          → hanya 1 entry per simbol (tanpa penambahan).
    #
    # Berlaku di SEMUA timeframe (dulu terkunci hanya M15).
    scaling_mode: str = "pyramid"
    max_positions_per_symbol: int = 3  # jumlah entry maksimum per simbol
    add_step_atr: float = 0.5          # jarak (×ATR) antar entry bertahap
    # TP entry tambahan MENGECIL tiap entry: entry-1 = tp_atr_mult (2.5),
    # entry-2 = 2.0, entry-3 = 1.5, ... dibatasi min_tp_atr_mult.
    tp_step_atr: float = 0.5
    min_tp_atr_mult: float = 0.5

    # ── Mode SCALPING (adaptif-rezim) ────────────────────────────────
    # Aktif HANYA bila signal_timeframe == "M15" DAN execution_mode == "selected"
    # (fokus satu simbol). Perannya FILTER: otak FuLens tetap penentu arah, gerbang
    # ini cuma memblokir entry yang lokasi/kondisinya buruk. Lihat strategy/scalp.py.
    scalp_enabled: bool = True
    # Ruang minimum ke level lawan sebelum entry = mult × tp_atr_mult × ATR.
    # Inti anti-danger-zone: BUY butuh ruang ke resisten, SELL butuh ruang ke support.
    # Naikkan = lebih selektif (entry lebih jarang, tapi TP lebih realistis).
    scalp_min_room_mult: float = 0.6
    # Efficiency Ratio: ≥ nilai ini dianggap TRENDING (ikut tren), di bawahnya
    # RANGING (mean-reversion di S/R). 0.3 = titik tengah yang umum dipakai.
    scalp_er_trend: float = 0.30
    # Saat TRENDING: entry ditolak bila harga sudah > nilai ini × ATR dari EMA50
    # (dianggap mengejar; tunggu pullback).
    scalp_ext_atr: float = 1.5
    # Saat RANGING: "menempel level" = dalam jarak ini × ATR dari support/resisten.
    scalp_near_atr: float = 1.0
    # Volume minimum = mult × rata-rata tick_volume (partisipasi pasar).
    scalp_vol_mult: float = 0.8
    scalp_vol_period: int = 20

    # ── Timing entry via Stochastic (HANYA timeframe M15) ────────────
    # Di M15: walau sinyal valid, bot MENUNGGU momen —
    #   SELL → %K ≥ stoch_upper (overbought); BUY → %K ≤ stoch_lower (oversold).
    # Timeframe lain: entry mengikuti sinyal saja (tanpa gerbang stochastic).
    entry_timing_enabled: bool = True
    stoch_upper: float = 70.0
    stoch_lower: float = 30.0

    # ── Risk management (mekanika eksekusi, bukan keputusan) ─────────
    risk_percent: float = 0.5     # % equity yang dirisikokan per entry
    atr_period: int = 14          # ATR dihitung dari rate MT5 untuk jarak SL/TP
    # Timeframe sumber ATR untuk jarak SL/TP + trailing:
    #  • "auto"  → IKUT timeframe yang dipilih pengguna di Flutter (signal_timeframe).
    #              SL/TP menyesuaikan horizon trading: M15 rapat, D1 lebar.
    #  • "M30"/"H1"/... → PIN ke satu timeframe, apa pun pilihan pengguna.
    #
    # Soal "auto" di D1: ATR emas D1 ~$90 → SL 1.5×ATR ≈ $139. Itu WAJAR untuk swing
    # D1 (butuh ruang napas) dan risiko TIDAK ikut membesar: lot dihitung dari
    # sl_dist (lihat risk_manager.build_plan), jadi SL lebar → lot kecil → kerugian
    # tetap risk_percent (0.5%) dari equity. Yang berubah cuma jarak, bukan risiko.
    # Pin ke "M30"/"H1" HANYA jika ingin SL selalu rapat berapa pun timeframe-nya
    # (konsekuensi: di sinyal D1, SL rapat lebih gampang kena noise → sering stop-out).
    atr_timeframe: str = "auto"
    sl_atr_mult: float = 1.5      # SL = 1.5 x ATR
    tp_atr_mult: float = 2.5      # TP = 2.5 x ATR
    trailing_enabled: bool = True
    trail_start_atr: float = 1.0  # mulai trailing setelah profit 1 x ATR
    trail_dist_atr: float = 1.0   # jarak trailing 1 x ATR

    # ── Proteksi ─────────────────────────────────────────────────────
    max_open_positions: int = 9       # maks total posisi bersamaan (semua simbol)
    max_daily_drawdown_pct: float = 10.0
    magic_number: int = 202607

    # Interval loop utama (detik). Sinyal FuLens bergerak lambat (harian),
    # jadi tak perlu terlalu cepat; 15-30 dtk cukup.
    loop_interval: int = 15


class FulensConfig:
    """Koneksi INTERNAL ke otak FuLens (jalan di localhost VPS, port 8500)."""
    BASE_URL = "http://127.0.0.1:8500"   # samakan dgn API_HOST/API_PORT FuLens
    API_KEY: str | None = None            # FuLens internal belum pakai key
    # Timeout proxy ke brain. Endpoint intraday (M15/M30/H1/H4/W1) mengunduh
    # data live dari Yahoo Finance saat cache dingin — ini bisa >8 dtk, apalagi
    # ketika ganti timeframe memicu beberapa request serentak. 8 dtk terlalu
    # pendek → httpx timeout → proxy balas 502. Beri ruang connect cepat tapi
    # read yang lega. (Pastikan timeout Flutter > nilai ini; lihat theme.dart.)
    TIMEOUT = 30.0                        # detik (read); dipakai sbg httpx timeout
    # Override pemetaan simbol broker → simbol kanonik FuLens.
    # Umumnya tak perlu: FuLens (symbols.normalize) sudah mengenali nama broker
    # standar & suffix umum. Isi di sini HANYA jika broker Anda pakai nama unik,
    # mis. {"GOLD#": "XAUUSD", "OIL": "WTIUSD"}.
    SYMBOL_MAP: dict[str, str] = {}


class ServerConfig:
    # Bind ke IP interface VPS (mis. Tailscale). Sebagian Windows Server menolak
    # "0.0.0.0" dengan error `getaddrinfo failed` — pakai IP spesifik agar aman.
    HOST = "93.127.140.99"
    PORT = 8000                                          # gerbang tunggal utk Flutter
    API_KEY = "CN9-5UB1TBJMD5wM_WR5dNiPr_Gbq9CXz6dt8Pa1spg"  # wajib diganti sebelum publik!

    # Login MT5 (kosongkan untuk memakai terminal yang sudah login)
    MT5_LOGIN: int | None = None
    MT5_PASSWORD: str | None = None
    MT5_SERVER: str | None = None
    MT5_PATH: str | None = None  # path terminal64.exe jika perlu


# ── Penyimpanan setelan (agar pilihan bertahan setelah restart) ──────
# Tanpa ini, PUT /settings hanya mengubah objek di memori: ganti timeframe ke M15
# lewat aplikasi → restart eksekutor → balik lagi ke default D1 di atas.
SETTINGS_FILE = Path(__file__).parent / "bot_settings.json"


def load_settings() -> BotSettings:
    """Setelan tersimpan (bila ada) ditumpuk di atas default pabrik.

    Field yang tak ada di file memakai default — jadi menambah setelan baru ke
    BotSettings tidak merusak file lama, dan setelan usang yang sudah dihapus dari
    kelas ini diabaikan begitu saja. Bila file rusak/tak terbaca → pakai default.
    """
    if not SETTINGS_FILE.exists():
        return BotSettings()
    try:
        data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        s = BotSettings(**data)
        log.info("Setelan dimuat dari %s (timeframe=%s)",
                 SETTINGS_FILE.name, s.signal_timeframe)
        return s
    except (json.JSONDecodeError, ValidationError, OSError, TypeError) as e:
        log.warning("Gagal baca %s (%s) — pakai default pabrik",
                    SETTINGS_FILE.name, e)
        return BotSettings()


def save_settings(s: BotSettings) -> bool:
    """Tulis setelan ke disk. Ditulis ke file sementara lalu di-rename agar file
    tidak tertinggal separuh jika proses mati di tengah penulisan."""
    try:
        tmp = SETTINGS_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(s.model_dump(), indent=2), encoding="utf-8")
        tmp.replace(SETTINGS_FILE)
        return True
    except OSError as e:
        log.warning("Gagal simpan %s: %s", SETTINGS_FILE.name, e)
        return False


settings = load_settings()
