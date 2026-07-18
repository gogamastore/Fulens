"""Peta timeframe aplikasi → spesifikasi unduh yfinance.

yfinance membatasi kedalaman histori untuk data intraday, jadi tiap timeframe
punya `period` sendiri. H4 tidak ada di yfinance → di-resample dari 60m.
"""

# Catatan M1/M5: batas yfinance ketat (1m hanya 7 hari terakhir, 5m 60 hari) dan
# datanya delayed. Itu dapat diterima karena kini hanya FALLBACK — sumber utama
# adalah OHLC yang didorong EA dari terminal MT5 (mt5_feed), yang tak punya batas
# ini dan harganya harga broker asli.
TF: dict[str, dict] = {
    "M1":  {"interval": "1m",  "period": "7d",   "resample": None},
    "M5":  {"interval": "5m",  "period": "60d",  "resample": None},
    "M15": {"interval": "15m", "period": "60d",  "resample": None},
    "M30": {"interval": "30m", "period": "60d",  "resample": None},
    "H1":  {"interval": "60m", "period": "180d", "resample": None},
    "H4":  {"interval": "60m", "period": "720d", "resample": "4h"},
    "D1":  {"interval": "1d",  "period": "2y",   "resample": None},
    "W1":  {"interval": "1wk", "period": "5y",   "resample": None},
}

DEFAULT = "D1"


def normalize(tf: str | None) -> str:
    t = (tf or DEFAULT).upper()
    return t if t in TF else DEFAULT


def spec(tf: str | None) -> dict:
    return TF[normalize(tf)]


def all_timeframes() -> list[str]:
    return list(TF.keys())


# Durasi satu bar per timeframe (detik) — dipakai mt5_feed untuk menilai apakah
# data dorongan EA sudah basi (EA berhenti mengirim) sehingga perlu fallback.
_SECONDS = {
    "M1": 60, "M5": 5 * 60, "M15": 15 * 60, "M30": 30 * 60,
    "H1": 3600, "H4": 4 * 3600, "D1": 86400, "W1": 7 * 86400,
}


def seconds(tf: str | None) -> int:
    return _SECONDS[normalize(tf)]
