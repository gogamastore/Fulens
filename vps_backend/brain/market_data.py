"""Ambil OHLC untuk simbol apa pun (yfinance) dan alias ke skema kolom FuLens.

TechnicalAnalyzer & analyze_multi_timeframe membaca kolom `gold_*`. Modul ini
mengunduh data per simbol + timeframe lalu menamai ulang kolomnya menjadi
`gold_open/high/low/close/volume`, sehingga seluruh mesin analisis yang ada bisa
dipakai lintas simbol & timeframe tanpa perubahan.
"""
import logging
import threading
import time
import warnings

import pandas as pd
import yfinance as yf

import symbols as sym
import timeframes as tfmod

warnings.filterwarnings("ignore")
log = logging.getLogger("market_data")

_CACHE: dict[tuple, tuple[float, pd.DataFrame]] = {}
_TTL = 300  # detik

# Kunci per-key: mencegah "thundering herd". Saat ganti timeframe, Flutter
# menembak signal/history/indicators/price/multitimeframe serentak — semuanya
# cache-miss untuk (simbol, tf) yang SAMA. Tanpa kunci, tiap request mengunduh
# sendiri dari Yahoo secara paralel → throttling → semua lambat/timeout (502).
# Dengan kunci: request pertama mengunduh, sisanya menunggu lalu ambil dari cache.
_LOCKS: dict[tuple, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()

# Key yang sedang di-refresh di latar belakang (agar tak menumpuk thread).
_REFRESHING: set[tuple] = set()


def _lock_for(key: tuple) -> threading.Lock:
    with _LOCKS_GUARD:
        lock = _LOCKS.get(key)
        if lock is None:
            lock = _LOCKS[key] = threading.Lock()
        return lock


def _flatten(df: pd.DataFrame) -> pd.DataFrame:
    """yfinance kadang mengembalikan MultiIndex kolom (nama, ticker) — ratakan."""
    if isinstance(df.columns, pd.MultiIndex):
        df = df.copy()
        df.columns = [c[0] for c in df.columns]
    return df


def _alias(raw: pd.DataFrame) -> pd.DataFrame:
    raw = _flatten(raw)
    df = pd.DataFrame(index=raw.index)
    df["gold_open"]   = raw.get("Open",   raw["Close"])
    df["gold_high"]   = raw.get("High",   raw["Close"])
    df["gold_low"]    = raw.get("Low",    raw["Close"])
    df["gold_close"]  = raw["Close"]
    df["gold_volume"] = raw.get("Volume", 0)
    return df.dropna(subset=["gold_close"])


def _resample(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    out = pd.DataFrame({
        "gold_open":   df["gold_open"].resample(rule).first(),
        "gold_high":   df["gold_high"].resample(rule).max(),
        "gold_low":    df["gold_low"].resample(rule).min(),
        "gold_close":  df["gold_close"].resample(rule).last(),
        "gold_volume": df["gold_volume"].resample(rule).sum(),
    })
    return out.dropna(subset=["gold_close"])


def _download(ticker: str, spec: dict, start, end) -> pd.DataFrame | None:
    """Unduh mentah dari yfinance lalu alias/resample ke skema `gold_*`."""
    kw = dict(interval=spec["interval"], auto_adjust=True, progress=False)
    if start or end:
        raw = yf.download(ticker, start=start, end=end, **kw)
    else:
        raw = yf.download(ticker, period=spec["period"], **kw)
    if raw is None or len(raw) == 0:
        return None
    df = _alias(raw)
    if spec["resample"]:
        df = _resample(df, spec["resample"])
    return df


def _fetch_into_cache(key, ticker, spec, start, end) -> pd.DataFrame | None:
    """Unduh (dengan kunci per-key) lalu simpan ke cache. Mengembalikan data lama
    bila unduhan gagal — lebih baik basi daripada tak ada."""
    with _lock_for(key):
        hit = _CACHE.get(key)
        if hit and time.time() - hit[0] < _TTL:
            return hit[1]                       # thread lain sudah mengisi
        try:
            df = _download(ticker, spec, start, end)
        except Exception as e:
            log.warning("Gagal unduh %s: %s", ticker, e)
            return hit[1] if hit else None
        if df is None or len(df) == 0:
            log.warning("Data kosong untuk %s", ticker)
            return hit[1] if hit else None
        _CACHE[key] = (time.time(), df)
        return df


def _refresh_bg(key, ticker, spec, start, end):
    """Perbarui cache di latar belakang; maksimal satu refresh per key."""
    with _LOCKS_GUARD:
        if key in _REFRESHING:
            return
        _REFRESHING.add(key)

    def run():
        try:
            _fetch_into_cache(key, ticker, spec, start, end)
        finally:
            with _LOCKS_GUARD:
                _REFRESHING.discard(key)

    threading.Thread(target=run, daemon=True).start()


def get_ohlc(symbol: str, timeframe: str = "D1",
             start: str | None = None, end: str | None = None) -> pd.DataFrame | None:
    """DataFrame OHLC (kolom `gold_*`) untuk simbol pada timeframe tertentu.

    - timeframe: M15/M30/H1/H4/D1/W1
    - start/end: 'YYYY-MM-DD' (opsional; untuk backtest rentang tanggal).
      Bila diisi, menggantikan `period` bawaan timeframe.

    Pola *stale-while-revalidate*: request TIDAK PERNAH menunggu unduhan selama
    cache pernah terisi. Unduhan intraday yfinance bisa makan puluhan detik —
    kalau request ikut menunggu, proxy eksekutor keburu timeout → 502. Jadi:
      • cache segar  → langsung sajikan;
      • cache basi   → sajikan yang LAMA sekarang, perbarui di latar belakang;
      • belum ada    → terpaksa menunggu (sekali saja; ditutup oleh prewarm()).
    """
    ticker = sym.yf_ticker(symbol)
    if not ticker:
        log.warning("Simbol tak dikenal: %s", symbol)
        return None

    spec = tfmod.spec(timeframe)
    key = (ticker, tfmod.normalize(timeframe), start, end)
    hit = _CACHE.get(key)

    if hit:
        if time.time() - hit[0] < _TTL:
            return hit[1]
        _refresh_bg(key, ticker, spec, start, end)
        return hit[1]                           # sajikan basi, jangan blokir

    return _fetch_into_cache(key, ticker, spec, start, end)


def prewarm(pairs: list[tuple[str, str]], delay: float = 1.5):
    """Isi cache di latar belakang saat startup, agar request pertama tak menunggu.

    Dijalankan berurutan dengan jeda: Yahoo Finance membatasi laju, dan menembak
    puluhan unduhan sekaligus justru membuat semuanya lambat/gagal.
    """
    def run():
        ok = 0
        for s, tf in pairs:
            try:
                if get_ohlc(s, tf) is not None:
                    ok += 1
            except Exception as e:
                log.warning("Prewarm %s %s gagal: %s", s, tf, e)
            time.sleep(delay)
        log.info("Prewarm selesai: %d/%d pasangan siap di cache", ok, len(pairs))

    threading.Thread(target=run, daemon=True).start()


def latest_price(symbol: str, timeframe: str = "D1") -> dict | None:
    """Harga terkini + perubahan untuk endpoint /price."""
    df = get_ohlc(symbol, timeframe)
    if df is None or len(df) < 2:
        return None
    last, prev = df.iloc[-1], df.iloc[-2]
    chg = float(last["gold_close"]) - float(prev["gold_close"])
    return {
        "symbol": sym.normalize(symbol),
        "timeframe": tfmod.normalize(timeframe),
        "timestamp": str(df.index[-1]),
        "price": round(float(last["gold_close"]), 5),
        "open": round(float(last["gold_open"]), 5),
        "high": round(float(last["gold_high"]), 5),
        "low": round(float(last["gold_low"]), 5),
        "change_usd": round(chg, 5),
        "change_pct": round(chg / float(prev["gold_close"]) * 100, 2),
    }
