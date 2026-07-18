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

from pydantic import BaseModel, Field, ValidationError

log = logging.getLogger("config")


class BotSettings(BaseModel):
    # Simbol yang dipantau/dieksekusi (nama simbol broker MT5 Anda).
    # FuLens kini bersinyal multi-aset: emas, forex, crypto, komoditas.
    symbols: list[str] = [
        "XAUUSD", "XAGUSD", "EURUSD", "GBPUSD", "USDJPY",
        "AUDUSD", "BTCUSD", "ETHUSD",
    ]

    # ── Timeframe EKSEKUSI (DIPILIH DARI FLUTTER) ────────────────────
    # EA mendorong OHLC untuk BANYAK timeframe (jadi semua layar analisis memakai
    # harga broker asli, bukan yfinance). Tapi yang DIEKSEKUSI hanya SATU — yang
    # dipilih di sini. Jadi kontrolnya satu tempat: aplikasi.
    #
    # Ini menggantikan `signal_timeframe` lama DAN input `SignalTF` di EA yang
    # dulu diam-diam menentukan timeframe keputusan. Dua sumber kebenaran itu
    # yang bikin layar menampilkan gerbang M1 sementara bot menilai H1.
    exec_timeframe: str = "M15"

    # ── Mode strategi otak (DIPILIH DARI FLUTTER) ────────────────────
    # Otak punya dua rantai gerbang (lihat brain/strategy.py):
    #   • "swing"    → Stochastic cross → Tren EMA200 → Sentuh S&R
    #                  Ikut tren besar; BUY-only saat uptrend, SELL-only saat
    #                  downtrend. Itu memang maksudnya.
    #   • "scalping" → Stochastic cross → BB Squeeze
    #                  Tidak peduli tren; seimbang BUY/SELL, cari profit harian.
    #   • "auto"     → otak memilih dari timeframe (M1/M5/M15/M30 → scalping).
    #
    # Mode berlaku untuk SEMUA simbol. Simbol mana yang ditradingkan ditentukan
    # oleh chart tempat EA dipasang — bukan oleh setelan di sini. Karena itu
    # `execution_mode`/`selected_symbol` lama DIHAPUS: dengan EA per-chart,
    # konsep "auto semua simbol" vs "fokus satu simbol" tak lagi relevan.
    trading_mode: str = "swing"

    # ── Gerbang keputusan dari FuLens ────────────────────────────────
    # Sinyal FuLens: "BELI KUAT" / "BELI" / "NETRAL" / "JUAL" / "JUAL KUAT".
    # Ambang kualitas setup, DIATUR DARI FLUTTER. Dibatasi 50-95 karena dengan
    # gerbang AND skor selalu >= 50 (quality = 50 + 50 x rata-rata skor gerbang),
    # jadi nilai < 50 tak bermakna dan > 95 praktis mematikan bot.
    #
    # PERINGATAN TERUKUR: menaikkannya MEMPERBURUK hasil, bukan memperbaiki.
    # Skor kualitas mengukur "seberapa baik syarat dipenuhi", BUKAN "seberapa
    # besar peluang profit" — dan uji ke depan menunjukkan keduanya tidak
    # berkorelasi. Scalping: 50%→+0.31R, 60%→+0.25R, 70%→+0.14R, 75%→-0.05R
    # (sambil membuang 80% peluang). Swing: skor selalu 76-98 jadi ambang < 75
    # tak berefek. Biarkan 50 kecuali kamu memang ingin lebih sedikit transaksi.
    min_confidence: float = Field(default=50.0, ge=50.0, le=95.0)
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
    # CATATAN: `scaling_mode`, `add_step_atr`, `tp_step_atr`, `min_tp_atr_mult`
    # juga BELUM dibaca siapa pun — entry bertahap belum diimplementasikan ulang
    # setelah bot_engine dicabut. Dibiarkan di sini sebagai rencana, TAPI jangan
    # berharap mengubahnya mengubah perilaku bot. Saat ini: 1 entry per simbol.
    tp_step_atr: float = 0.5
    min_tp_atr_mult: float = 0.5

    # Setelan lama `scalp_*` dan `entry_timing_*` DIHAPUS: keduanya milik
    # strategy/scalp.py + bot_engine yang sudah dicabut. Peran filter lokasi kini
    # ada di gerbang otak (Sentuh S&R untuk swing, BB Squeeze untuk scalping),
    # dan timing Stochastic sudah jadi gerbang wajib di kedua mode.

    # ── Risk management (mekanika eksekusi, bukan keputusan) ─────────
    risk_percent: float = 0.5     # % equity yang dirisikokan per entry

    # DIHAPUS 2026-07-19: `atr_timeframe`, `atr_period`, `sl_atr_mult`,
    # `tp_atr_mult`. Keempatnya KODE MATI — tak satu pun dibaca sejak
    # risk_manager.py dicabut. Jarak SL/TP kini sepenuhnya dari otak
    # (brain/config.py RISK_PARAMS, ATR dari timeframe yang dianalisis).
    #
    # Kenapa dicabut, bukan dibiarkan: field mati yang kelihatan hidup itu
    # menipu. `tp_atr_mult` di sini masih 2.5 sementara otak sudah memakai 2.0,
    # dan pengguna sempat mengubah `atr_timeframe` "auto"->"M15" lalu heran
    # kenapa SL/TP tidak berubah sama sekali. Satu sumber kebenaran: otak.
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
    # Dipakai bertiga: Flutter (app_config.dart), EA (input ApiKey), dan cek WS.

    # Field login MT5 (MT5_LOGIN/PASSWORD/SERVER/PATH) DIHAPUS: gerbang tak lagi
    # menyentuh MT5 — EA yang login & mengeksekusi di terminal. Kalau kode lama
    # masih mencarinya, itu sisa yang sudah tidak relevan.


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
        log.info("Setelan dimuat dari %s (mode=%s)",
                 SETTINGS_FILE.name, s.trading_mode)
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
