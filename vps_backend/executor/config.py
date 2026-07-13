"""Konfigurasi backend EKSEKUTOR.

Peran: penghubung MURNI ke MT5. Tidak ada lagi "otak"/strategi di sini —
seluruh keputusan arah (BUY/SELL/NETRAL) datang dari backend FuLens (ML).
Eksekutor hanya: ambil sinyal FuLens → hitung lot/SL/TP (ATR) → kirim ke MT5,
lalu kelola trailing stop & proteksi drawdown.
"""
from pydantic import BaseModel


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

    # Entry bertahap (pyramiding ke arah profit) per simbol:
    #  • entry-1 saat sinyal valid;
    #  • entry ke-k ditambah HANYA jika harga sudah bergerak menguntungkan
    #    ≥ (k-1) × add_step_atr × ATR dari entry pertama (menambah ke posisi
    #    yang terbukti benar, bukan averaging-down).
    max_positions_per_symbol: int = 1  # jumlah entry maksimum per simbol
    add_step_atr: float = 0.5          # jarak (×ATR) antar entry bertahap

    # ── Risk management (mekanika eksekusi, bukan keputusan) ─────────
    risk_percent: float = 0.5     # % equity yang dirisikokan per entry
    atr_period: int = 14          # ATR dihitung dari rate MT5 untuk jarak SL/TP
    atr_timeframe: str = "H1"     # timeframe ATR (selaras horizon sinyal FuLens)
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
    TIMEOUT = 8.0                         # detik
    # Override pemetaan simbol broker → simbol kanonik FuLens.
    # Umumnya tak perlu: FuLens (symbols.normalize) sudah mengenali nama broker
    # standar & suffix umum. Isi di sini HANYA jika broker Anda pakai nama unik,
    # mis. {"GOLD#": "XAUUSD", "OIL": "WTIUSD"}.
    SYMBOL_MAP: dict[str, str] = {}


class ServerConfig:
    # Bind ke IP interface VPS (mis. Tailscale). Sebagian Windows Server menolak
    # "0.0.0.0" dengan error `getaddrinfo failed` — pakai IP spesifik agar aman.
    HOST = "100.78.56.14"
    PORT = 8000                                          # gerbang tunggal utk Flutter
    API_KEY = "CN9-5UB1TBJMD5wM_WR5dNiPr_Gbq9CXz6dt8Pa1spg"  # wajib diganti sebelum publik!

    # Login MT5 (kosongkan untuk memakai terminal yang sudah login)
    MT5_LOGIN: int | None = None
    MT5_PASSWORD: str | None = None
    MT5_SERVER: str | None = None
    MT5_PATH: str | None = None  # path terminal64.exe jika perlu


settings = BotSettings()
