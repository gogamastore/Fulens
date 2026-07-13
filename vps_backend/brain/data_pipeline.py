"""
FuLens — Data Pipeline
Mengambil dan memproses semua data: harga emas, DXY, VIX,
yield obligasi, minyak, dan data fundamental dari FRED.

Jalankan: python data_pipeline.py
"""

import warnings
warnings.filterwarnings("ignore")

import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta
from pathlib import Path
import json
import time
from colorama import init, Fore, Style

init(autoreset=True)

try:
    from fredapi import Fred
    FRED_AVAILABLE = True
except ImportError:
    FRED_AVAILABLE = False

import config

# ─────────────────────────────────────────────────────────
#  HELPER
# ─────────────────────────────────────────────────────────
def log(msg, level="INFO"):
    colors = {"INFO": Fore.CYAN, "OK": Fore.GREEN, "WARN": Fore.YELLOW, "ERR": Fore.RED}
    prefix = {"INFO": "●", "OK": "✓", "WARN": "⚠", "ERR": "✗"}
    print(f"{colors.get(level, '')} [{prefix.get(level,'·')}] {msg}{Style.RESET_ALL}")

def end_date():
    return datetime.today().strftime("%Y-%m-%d")

def start_date():
    return (datetime.today() - timedelta(days=config.LOOKBACK_DAYS)).strftime("%Y-%m-%d")


# ─────────────────────────────────────────────────────────
#  1. FETCH HARGA MARKET (Yahoo Finance)
# ─────────────────────────────────────────────────────────
def fetch_market_data() -> pd.DataFrame:
    """Ambil data OHLCV harga emas + aset korelatif."""
    log("Mengambil data market dari Yahoo Finance...")

    tickers = {
        "gold"   : config.GOLD_TICKER,
        "dxy"    : config.DXY_TICKER,
        "oil"    : config.OIL_TICKER,
        "sp500"  : config.SP500_TICKER,
        "vix"    : config.VIX_TICKER,
        "bond10y": config.BOND10Y_TICKER,
    }

    dfs = {}
    for name, ticker in tickers.items():
        try:
            df = yf.download(
                ticker,
                start=start_date(),
                end=end_date(),
                progress=False,
                auto_adjust=True,
            )
            if df.empty:
                log(f"  {ticker} — tidak ada data, dilewati", "WARN")
                continue

            # Flatten multi-index jika ada
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)

            df.index = pd.to_datetime(df.index)
            dfs[name] = df
            log(f"  {ticker} ({name}) — {len(df)} baris", "OK")
            time.sleep(0.3)  # hindari rate-limit

        except Exception as e:
            log(f"  Gagal fetch {ticker}: {e}", "ERR")

    if "gold" not in dfs:
        raise RuntimeError("Data emas tidak berhasil diambil!")

    # Gabungkan: pakai index tanggal emas sebagai acuan
    gold_df = dfs["gold"].copy()
    gold_df.columns = [f"gold_{c.lower()}" for c in gold_df.columns]

    for name, df in dfs.items():
        if name == "gold":
            continue
        # Ambil hanya kolom Close
        col = "Close" if "Close" in df.columns else df.columns[0]
        gold_df[name] = df[col].reindex(gold_df.index, method="ffill")

    gold_df.dropna(subset=["gold_close"], inplace=True)
    log(f"Market data siap: {gold_df.shape[0]} baris × {gold_df.shape[1]} kolom", "OK")
    return gold_df


# ─────────────────────────────────────────────────────────
#  2. FETCH DATA FUNDAMENTAL (FRED)
# ─────────────────────────────────────────────────────────
def fetch_fundamental_data(market_df: pd.DataFrame) -> pd.DataFrame:
    """Ambil data fundamental dari FRED dan gabungkan ke market_df."""

    if not FRED_AVAILABLE:
        log("fredapi tidak terinstall, lewati data FRED", "WARN")
        return market_df

    if config.FRED_API_KEY == "ISI_API_KEY_FRED_KAMU":
        log("FRED API key belum diisi di config.py — data fundamental dilewati", "WARN")
        log("  Daftar gratis di: https://fred.stlouisfed.org/docs/api/api_key.html", "WARN")
        # Buat kolom placeholder agar pipeline tetap jalan
        for col in config.FRED_SERIES.keys():
            market_df[col.lower()] = np.nan
        return market_df

    log("Mengambil data fundamental dari FRED...")
    try:
        fred = Fred(api_key=config.FRED_API_KEY)
        for series_name, series_id in config.FRED_SERIES.items():
            try:
                s = fred.get_series(
                    series_id,
                    observation_start=start_date(),
                    observation_end=end_date(),
                )
                s = s.reindex(market_df.index, method="ffill")
                market_df[series_name.lower()] = s
                log(f"  {series_name} ({series_id}) — OK", "OK")
            except Exception as e:
                log(f"  Gagal ambil {series_name}: {e}", "WARN")
                market_df[series_name.lower()] = np.nan
    except Exception as e:
        log(f"Koneksi FRED gagal: {e}", "ERR")

    return market_df


# ─────────────────────────────────────────────────────────
#  3. FEATURE ENGINEERING DASAR
# ─────────────────────────────────────────────────────────
def add_basic_features(df: pd.DataFrame) -> pd.DataFrame:
    """Tambahkan fitur turunan yang berguna untuk model."""
    log("Membuat fitur turunan...")

    # Return harian & mingguan
    df["gold_return_1d"]  = df["gold_close"].pct_change(1)
    df["gold_return_5d"]  = df["gold_close"].pct_change(5)
    df["gold_return_20d"] = df["gold_close"].pct_change(20)

    # Log return (lebih stabil untuk model ML)
    df["gold_log_return"] = np.log(df["gold_close"] / df["gold_close"].shift(1))

    # Range harian (volatilitas)
    df["gold_range"]    = df["gold_high"] - df["gold_low"]
    df["gold_range_pct"] = df["gold_range"] / df["gold_close"]

    # Gap open-close
    df["gold_gap"] = df["gold_close"] - df["gold_open"]

    # Perubahan DXY
    if "dxy" in df.columns:
        df["dxy_return"] = df["dxy"].pct_change(1)
        df["dxy_5d"]     = df["dxy"].pct_change(5)

    # Korelasi rolling emas vs DXY (20 hari)
    if "dxy" in df.columns:
        df["gold_dxy_corr_20"] = (
            df["gold_close"].rolling(20).corr(df["dxy"])
        )

    # Perubahan VIX
    if "vix" in df.columns:
        df["vix_change"] = df["vix"].pct_change(1)

    # Target: apakah harga naik besok?
    df["target_price"]     = df["gold_close"].shift(-1)          # Harga besok
    df["target_direction"] = (df["target_price"] > df["gold_close"]).astype(int)

    log(f"Fitur turunan ditambahkan. Total kolom: {df.shape[1]}", "OK")
    return df


# ─────────────────────────────────────────────────────────
#  4. SIMPAN DATA
# ─────────────────────────────────────────────────────────
def save_data(df: pd.DataFrame):
    """Simpan data ke CSV dan metadata ke JSON."""

    # Raw CSV
    raw_path = config.RAW_DIR / "gold_market_raw.csv"
    df.to_csv(raw_path)
    log(f"Raw data disimpan: {raw_path}", "OK")

    # Processed (hapus NaN)
    df_clean = df.dropna(subset=["gold_close"]).copy()
    proc_path = config.PROCESSED_DIR / "gold_processed.csv"
    df_clean.to_csv(proc_path)
    log(f"Processed data disimpan: {proc_path}", "OK")

    # Metadata JSON
    meta = {
        "last_update"  : datetime.now().isoformat(),
        "total_rows"   : len(df_clean),
        "date_range"   : {
            "start": str(df_clean.index.min().date()),
            "end"  : str(df_clean.index.max().date()),
        },
        "columns"      : list(df_clean.columns),
        "latest_price" : float(df_clean["gold_close"].iloc[-1]),
        "latest_date"  : str(df_clean.index[-1].date()),
    }
    meta_path = config.DATA_DIR / "metadata.json"
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)
    log(f"Metadata disimpan: {meta_path}", "OK")

    return df_clean


# ─────────────────────────────────────────────────────────
#  5. LOAD DATA (untuk modul lain)
# ─────────────────────────────────────────────────────────
def load_processed_data() -> pd.DataFrame:
    """Load data yang sudah diproses."""
    path = config.PROCESSED_DIR / "gold_processed.csv"
    if not path.exists():
        raise FileNotFoundError(
            "Data belum ada. Jalankan: python data_pipeline.py"
        )
    df = pd.read_csv(path, index_col=0, parse_dates=True)
    return df


def load_latest_price() -> dict:
    """Ambil harga terbaru dari metadata."""
    meta_path = config.DATA_DIR / "metadata.json"
    if not meta_path.exists():
        return {}
    with open(meta_path) as f:
        return json.load(f)


# ─────────────────────────────────────────────────────────
#  6. RINGKASAN DATA
# ─────────────────────────────────────────────────────────
def print_summary(df: pd.DataFrame):
    """Tampilkan ringkasan data di terminal."""
    print("\n" + "═" * 60)
    print(f"  {'RINGKASAN DATA FULENS':^56}")
    print("═" * 60)

    latest = df.iloc[-1]
    prev   = df.iloc[-2]
    chg    = latest["gold_close"] - prev["gold_close"]
    chg_p  = chg / prev["gold_close"] * 100

    print(f"\n  Harga Emas Terakhir : ${latest['gold_close']:,.2f}")
    print(f"  Perubahan Hari Ini  : {'▲' if chg>0 else '▼'} ${abs(chg):.2f} ({chg_p:+.2f}%)")
    print(f"  Tanggal             : {df.index[-1].date()}")
    print(f"  Total Data          : {len(df)} hari")

    if "dxy" in df.columns and not pd.isna(latest.get("dxy")):
        print(f"\n  DXY                 : {latest['dxy']:.2f}")
    if "vix" in df.columns and not pd.isna(latest.get("vix")):
        print(f"  VIX                 : {latest['vix']:.2f}")
    if "bond10y" in df.columns and not pd.isna(latest.get("bond10y")):
        print(f"  Yield 10Y           : {latest['bond10y']:.2f}%")
    if "oil" in df.columns and not pd.isna(latest.get("oil")):
        print(f"  Harga Minyak (WTI)  : ${latest['oil']:.2f}")

    print("\n" + "═" * 60)
    print(f"  {'✓ Data siap untuk analisis indikator!':^56}")
    print("═" * 60 + "\n")


# ─────────────────────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────────────────────
def run_pipeline():
    print("\n" + "═"*60)
    print("   🏅 FuLens — Data Pipeline")
    print("═"*60 + "\n")

    try:
        # Step 1: Ambil data market
        df = fetch_market_data()

        # Step 2: Tambah data fundamental
        df = fetch_fundamental_data(df)

        # Step 3: Feature engineering
        df = add_basic_features(df)

        # Step 4: Simpan
        df_clean = save_data(df)

        # Step 5: Tampilkan ringkasan
        print_summary(df_clean)

        return df_clean

    except Exception as e:
        log(f"Pipeline gagal: {e}", "ERR")
        import traceback
        traceback.print_exc()
        return None


if __name__ == "__main__":
    run_pipeline()
