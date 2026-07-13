"""Peta timeframe aplikasi → spesifikasi unduh yfinance.

yfinance membatasi kedalaman histori untuk data intraday, jadi tiap timeframe
punya `period` sendiri. H4 tidak ada di yfinance → di-resample dari 60m.
"""

TF: dict[str, dict] = {
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
