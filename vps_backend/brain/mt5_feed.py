"""Penyimpan OHLC yang DIDORONG EA dari terminal MT5.

Ini "mata" dalam arsitektur hybrid: EA mengirim bar tertutup dari chart broker ke
sini, lalu `market_data.get_ohlc` memilih data ini LEBIH DULU daripada yfinance.
Efeknya, seluruh otak (gerbang, S&R, ML) menilai harga broker yang SAMA dengan
yang dieksekusi — memperbaiki futures-vs-spot dan data M15 sintetis sekaligus.

Sengaja modul kecil & tanpa dependensi baru: dict di memori + cache CSV per key
supaya bertahan restart brain. EA mengirim ulang tiap bar, jadi restart cuma
kehilangan data sampai push berikutnya.
"""
import logging
import threading
import time
from pathlib import Path

import pandas as pd

import config
import symbols as sym
import timeframes as tfmod

log = logging.getLogger("mt5_feed")

# Batasi jendela: cukup untuk squeeze percentile (100) + S&R pivot + margin.
MAX_BARS = 600

_DIR = config.DATA_DIR / "mt5_feed"
_DIR.mkdir(parents=True, exist_ok=True)

# key = (simbol kanonik, tf ternormalisasi) → (epoch update terakhir, DataFrame)
_STORE: dict[tuple, tuple[float, pd.DataFrame]] = {}
_LOCK = threading.Lock()

_COLS = ["gold_open", "gold_high", "gold_low", "gold_close", "gold_volume"]


def _key(symbol: str, timeframe: str) -> tuple:
    return (sym.normalize(symbol), tfmod.normalize(timeframe))


def _path(key: tuple) -> Path:
    return _DIR / f"{key[0]}_{key[1]}.csv"


def _to_index(raw_time) -> pd.Timestamp:
    """'time' dari EA bisa epoch detik (int/float) atau string ISO. Terima keduanya."""
    if isinstance(raw_time, (int, float)):
        return pd.to_datetime(int(raw_time), unit="s")
    return pd.to_datetime(raw_time)


def _frame_from_bars(bars: list[dict]) -> pd.DataFrame:
    rows = {}
    for b in bars:
        try:
            idx = _to_index(b["time"])
            rows[idx] = [
                float(b["open"]), float(b["high"]),
                float(b["low"]), float(b["close"]),
                float(b.get("volume", 0) or 0),
            ]
        except (KeyError, TypeError, ValueError):
            continue  # lewati bar rusak, jangan gagalkan seluruh batch
    if not rows:
        return pd.DataFrame(columns=_COLS)
    df = pd.DataFrame.from_dict(rows, orient="index", columns=_COLS)
    df.index = pd.DatetimeIndex(df.index)
    return df.sort_index()


def _spacing_ok(df: pd.DataFrame, timeframe: str) -> bool:
    """Apakah jarak antar-bar cocok dengan label timeframe-nya?

    Ada di sini karena kelas bug ini pernah lolos diam-diam: EA mengirim bar D1
    BERLABEL "M1" (TfFromString tidak mengenal M1/M5 dan jatuh ke PERIOD_D1).
    Otak menerimanya tanpa curiga, menghitung ATR D1, lalu memasang SL/TP puluhan
    kali terlalu lebar — tanpa satu pun error.

    Pengirim dan penerima memakai label yang sama tapi tak pernah saling
    memeriksa. Sekarang diperiksa: data yang salah skala lebih berbahaya daripada
    tidak ada data, karena ia tetap menghasilkan angka yang kelihatan masuk akal.

    Toleransinya longgar (0.5x-3x) supaya akhir pekan, libur bursa, dan sesi
    tertutup tidak memicu penolakan palsu — yang dicari adalah salah skala
    besar (M1 vs D1 = 1440x), bukan penyimpangan kecil.
    """
    if len(df) < 10:
        return True                      # terlalu sedikit untuk dinilai
    expected = tfmod.seconds(timeframe)
    if not expected:
        return True
    deltas = df.index.to_series().diff().dt.total_seconds().dropna()
    deltas = deltas[deltas > 0]
    if deltas.empty:
        return True
    median = float(deltas.median())
    return 0.5 * expected <= median <= 3.0 * expected


def ingest(symbol: str, timeframe: str, bars: list[dict]) -> int:
    """Gabung bar dari EA ke penyimpan. Upsert berdasarkan timestamp — bar
    berjalan yang dikirim berulang akan menimpa versinya sendiri, bukan menumpuk.
    Kembalikan jumlah bar tersimpan (total setelah merge)."""
    incoming = _frame_from_bars(bars)
    if incoming.empty:
        return 0
    if not _spacing_ok(incoming, timeframe):
        gap = float(incoming.index.to_series().diff().dt.total_seconds()
                    .dropna().median())
        log.error(
            "TOLAK feed %s %s: jarak antar-bar %.0f dtk, seharusnya ~%s dtk. "
            "EA hampir pasti mengirim timeframe lain dengan label ini — "
            "perbarui TfFromString di FuLensEA.mq5. Data TIDAK disimpan.",
            sym.normalize(symbol), tfmod.normalize(timeframe),
            gap, tfmod.seconds(timeframe))
        return 0
    key = _key(symbol, timeframe)
    with _LOCK:
        cur = _load(key)
        if cur is not None and not cur.empty:
            # incoming menang saat timestamp bertabrakan (bar terbaru dari broker).
            merged = pd.concat([cur[~cur.index.isin(incoming.index)], incoming])
            merged = merged.sort_index()
        else:
            merged = incoming
        merged = merged.tail(MAX_BARS)
        _STORE[key] = (time.time(), merged)
        try:
            merged.to_csv(_path(key))
        except OSError as e:
            log.warning("Gagal tulis cache %s: %s", _path(key).name, e)
        return len(merged)


def _load(key: tuple) -> pd.DataFrame | None:
    """Ambil dari memori; kalau kosong (mis. setelah restart) coba dari CSV."""
    hit = _STORE.get(key)
    if hit is not None:
        return hit[1]
    p = _path(key)
    if p.exists():
        try:
            df = pd.read_csv(p, index_col=0, parse_dates=True)
            # mtime file jadi proksi 'update terakhir' setelah restart.
            _STORE[key] = (p.stat().st_mtime, df)
            return df
        except (OSError, ValueError) as e:
            log.warning("Gagal baca cache %s: %s", p.name, e)
    return None


def get(symbol: str, timeframe: str,
        max_age_s: float | None = None) -> pd.DataFrame | None:
    """DataFrame OHLC dorongan EA bila ADA dan belum basi; selain itu None
    (memberi sinyal ke market_data untuk fallback ke yfinance).

    Basi = update terakhir lebih tua dari `max_age_s`. Default longgar
    (6 × durasi bar, minimal 6 jam): kalau EA berhenti mengirim, akhirnya
    fallback — tapi jangan terlalu galak, karena data broker basi pun sering
    lebih benar daripada yfinance yang futures/delayed.
    """
    key = _key(symbol, timeframe)
    with _LOCK:
        df = _load(key)
        if df is None or df.empty:
            return None
        updated = _STORE.get(key, (0, None))[0]
    if max_age_s is None:
        max_age_s = max(6 * tfmod.seconds(timeframe), 6 * 3600)
    if time.time() - updated > max_age_s:
        log.info("Data EA %s %s basi (%.0f dtk) — fallback yfinance",
                 key[0], key[1], time.time() - updated)
        return None
    return df


def has(symbol: str, timeframe: str) -> bool:
    return get(symbol, timeframe) is not None


def status() -> list[dict]:
    """Ringkasan untuk /health & debug: key apa saja yang terisi, umur, jumlah bar."""
    out = []
    now = time.time()
    with _LOCK:
        for (s, tf), (updated, df) in _STORE.items():
            out.append({
                "symbol": s, "timeframe": tf, "bars": len(df),
                "age_seconds": round(now - updated, 1),
                "last_bar": str(df.index[-1]) if len(df) else None,
            })
    return out
