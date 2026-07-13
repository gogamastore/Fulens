"""Registry simbol multi-aset untuk otak FuLens.

Menghubungkan simbol aplikasi (nama broker MT5) ↔ ticker yfinance ↔ kelas aset.
Dipakai signal_engine / market_data / backtest_engine untuk mendukung banyak simbol.
"""

# key = simbol kanonik (dipakai app & executor).
SYMBOLS: dict[str, dict] = {
    "XAUUSD": {"yf": "GC=F",     "asset": "metal",     "name": "Emas (Gold)",   "ml": True},
    "XAGUSD": {"yf": "SI=F",     "asset": "metal",     "name": "Perak (Silver)","ml": False},
    "EURUSD": {"yf": "EURUSD=X", "asset": "forex",     "name": "EUR/USD",       "ml": False},
    "GBPUSD": {"yf": "GBPUSD=X", "asset": "forex",     "name": "GBP/USD",       "ml": False},
    "USDJPY": {"yf": "USDJPY=X", "asset": "forex",     "name": "USD/JPY",       "ml": False},
    "AUDUSD": {"yf": "AUDUSD=X", "asset": "forex",     "name": "AUD/USD",       "ml": False},
    "BTCUSD": {"yf": "BTC-USD",  "asset": "crypto",    "name": "Bitcoin",       "ml": False},
    "ETHUSD": {"yf": "ETH-USD",  "asset": "crypto",    "name": "Ethereum",      "ml": False},
    "WTIUSD": {"yf": "CL=F",     "asset": "commodity", "name": "Minyak WTI",    "ml": False},
}

DEFAULT = "XAUUSD"

# Alias nama broker/umum → simbol kanonik.
_ALIASES = {
    "GOLD": "XAUUSD", "XAUUSD.": "XAUUSD", "GOLDMICRO": "XAUUSD", "XAUUSDM": "XAUUSD",
    "SILVER": "XAGUSD", "XAGUSDM": "XAGUSD",
    "BTCUSDT": "BTCUSD", "BTCUSD.": "BTCUSD", "XBTUSD": "BTCUSD",
    "ETHUSDT": "ETHUSD",
    "USOIL": "WTIUSD", "WTI": "WTIUSD", "XTIUSD": "WTIUSD", "OILUSD": "WTIUSD",
    "EURUSDM": "EURUSD", "GBPUSDM": "GBPUSD", "USDJPYM": "USDJPY", "AUDUSDM": "AUDUSD",
}


def normalize(symbol: str | None) -> str:
    """Ubah nama broker apa pun menjadi simbol kanonik yang dikenal FuLens."""
    if not symbol:
        return DEFAULT
    s = symbol.strip().upper()
    if s in SYMBOLS:
        return s
    if s in _ALIASES:
        return _ALIASES[s]
    # Buang suffix broker umum (mis. 'EURUSD.a', 'XAUUSD-ECN').
    base = s.replace(".", "").replace("-", "").replace("_", "")
    for k in SYMBOLS:
        if base.startswith(k):
            return k
    return s  # tak dikenali — biarkan (akan ditolak di lapisan atas)


def exists(symbol: str) -> bool:
    return normalize(symbol) in SYMBOLS


def get(symbol: str) -> dict | None:
    return SYMBOLS.get(normalize(symbol))


def yf_ticker(symbol: str) -> str | None:
    info = get(symbol)
    return info["yf"] if info else None


def has_ml(symbol: str) -> bool:
    info = get(symbol)
    return bool(info and info["ml"])


def all_symbols() -> list[dict]:
    """Daftar simbol untuk dropdown Flutter."""
    return [{"symbol": k, **v} for k, v in SYMBOLS.items()]
