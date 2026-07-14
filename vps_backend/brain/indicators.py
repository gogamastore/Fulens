"""
FuLens — Modul Indikator Teknikal
Menghitung 25+ indikator teknikal dan menghasilkan sinyal beli/jual/netral.

Jalankan standalone: python indicators.py
Atau import ke modul lain: from indicators import TechnicalAnalyzer
"""

import warnings
warnings.filterwarnings("ignore")

import pandas as pd
import numpy as np
from tabulate import tabulate
from colorama import init, Fore, Style
from dataclasses import dataclass, field
from typing import Optional

init(autoreset=True)
import config
from ta import trend, momentum, volatility, volume as ta_volume

# ─────────────────────────────────────────────────────────
#  DATA CLASS HASIL INDIKATOR
# ─────────────────────────────────────────────────────────
@dataclass
class SignalResult:
    name    : str
    value   : float
    signal  : str        # "BELI" | "JUAL" | "NETRAL"
    category: str        # "Tren" | "Momentum" | "Volatilitas" | "Volume"
    detail  : str = ""

@dataclass
class AnalysisReport:
    timestamp       : str = ""
    current_price   : float = 0.0
    signals         : list = field(default_factory=list)
    buy_count       : int = 0
    sell_count      : int = 0
    neutral_count   : int = 0
    overall_signal  : str = "NETRAL"
    confidence      : float = 0.0
    support_levels  : list = field(default_factory=list)
    resistance_levels: list = field(default_factory=list)


# ─────────────────────────────────────────────────────────
#  KELAS UTAMA
# ─────────────────────────────────────────────────────────
class TechnicalAnalyzer:
    """Hitung semua indikator teknikal dari DataFrame OHLCV."""

    def __init__(self, df: pd.DataFrame):
        self.df     = df.copy()
        self.p      = config.INDICATOR_PARAMS
        self.close  = df["gold_close"]
        self.high   = df.get("gold_high",   df["gold_close"])
        self.low    = df.get("gold_low",    df["gold_close"])
        self.open_  = df.get("gold_open",   df["gold_close"])
        self.volume = df.get("gold_volume", pd.Series(np.ones(len(df)), index=df.index))
        self._calc  = self._calculate_all()

    # ── UTILITAS ──────────────────────────────────────────
    @staticmethod
    def _ema(series: pd.Series, period: int) -> pd.Series:
        return series.ewm(span=period, adjust=False).mean()

    @staticmethod
    def _sma(series: pd.Series, period: int) -> pd.Series:
        return series.rolling(window=period).mean()

    @staticmethod
    def _signal(val, buy_cond: bool, sell_cond: bool) -> str:
        if buy_cond:  return "BELI"
        if sell_cond: return "JUAL"
        return "NETRAL"

    # ── KALKULASI SEMUA INDIKATOR ─────────────────────────
    def _calculate_all(self) -> dict:
        c = self.close; h = self.high; l = self.low; v = self.volume
        p = self.p

        # ── Trend ──────────────────────────────────────────
        ema20  = self._ema(c, p["EMA_SHORT"])
        ema50  = self._ema(c, p["EMA_MED"])
        ema200 = self._ema(c, p["EMA_LONG"])
        sma50  = self._sma(c, p["SMA_SHORT"])
        sma200 = self._sma(c, p["SMA_LONG"])

        # ── MACD ───────────────────────────────────────────
        ema_fast   = self._ema(c, p["MACD_FAST"])
        ema_slow   = self._ema(c, p["MACD_SLOW"])
        macd_line  = ema_fast - ema_slow
        macd_signal= self._ema(macd_line, p["MACD_SIGNAL"])
        macd_hist  = macd_line - macd_signal

        # ── RSI ────────────────────────────────────────────
        delta  = c.diff()
        gain   = delta.clip(lower=0).ewm(com=p["RSI_PERIOD"]-1, adjust=False).mean()
        loss   = (-delta.clip(upper=0)).ewm(com=p["RSI_PERIOD"]-1, adjust=False).mean()
        rs     = gain / loss.replace(0, np.nan)
        rsi    = 100 - (100 / (1 + rs))

        # ── Bollinger Bands ────────────────────────────────
        bb_mid   = self._sma(c, p["BB_PERIOD"])
        bb_std   = c.rolling(p["BB_PERIOD"]).std()
        bb_upper = bb_mid + p["BB_STD"] * bb_std
        bb_lower = bb_mid - p["BB_STD"] * bb_std
        bb_width = (bb_upper - bb_lower) / bb_mid * 100
        bb_pct_b = (c - bb_lower) / (bb_upper - bb_lower)

        # ── Stochastic ────────────────────────────────────
        k_period = p["STOCH_K"]
        low_min  = l.rolling(k_period).min()
        high_max = h.rolling(k_period).max()
        stoch_k  = 100 * (c - low_min) / (high_max - low_min).replace(0, np.nan)
        stoch_d  = self._sma(stoch_k, p["STOCH_D"])

        # ── ATR ───────────────────────────────────────────
        tr1  = h - l
        tr2  = (h - c.shift()).abs()
        tr3  = (l - c.shift()).abs()
        tr   = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr  = self._ema(tr, p["ATR_PERIOD"])

        # ── CCI ───────────────────────────────────────────
        tp   = (h + l + c) / 3
        cci  = (tp - self._sma(tp, p["CCI_PERIOD"])) / (0.015 * tp.rolling(p["CCI_PERIOD"]).std())

        # ── Williams %R ───────────────────────────────────
        wp   = p["WILLIAMS_PERIOD"]
        wr   = -100 * (h.rolling(wp).max() - c) / (h.rolling(wp).max() - l.rolling(wp).min()).replace(0, np.nan)

        # ── ROC ───────────────────────────────────────────
        roc  = c.pct_change(12) * 100

        # ── ADX ───────────────────────────────────────────
        dm_plus  = (h.diff()).clip(lower=0)
        dm_minus = (-l.diff()).clip(lower=0)
        dm_plus  = dm_plus.where(dm_plus > dm_minus, 0)
        dm_minus = dm_minus.where(dm_minus > dm_plus, 0)
        di_plus  = 100 * self._ema(dm_plus, p["ADX_PERIOD"]) / atr.replace(0, np.nan)
        di_minus = 100 * self._ema(dm_minus, p["ADX_PERIOD"]) / atr.replace(0, np.nan)
        dx       = 100 * (di_plus - di_minus).abs() / (di_plus + di_minus).replace(0, np.nan)
        adx      = self._sma(dx, p["ADX_PERIOD"])

        # ── Parabolic SAR (sederhana) ──────────────────────
        sar = self._calc_psar(h, l, c)

        # ── OBV ───────────────────────────────────────────
        obv = (np.sign(c.diff()) * v).fillna(0).cumsum()

        # ── Momentum ──────────────────────────────────────
        momentum = c - c.shift(10)

        # ── Ichimoku ──────────────────────────────────────
        tenkan  = (h.rolling(9).max()  + l.rolling(9).min())  / 2
        kijun   = (h.rolling(26).max() + l.rolling(26).min()) / 2
        senkou_a = ((tenkan + kijun) / 2).shift(26)
        senkou_b = ((h.rolling(52).max() + l.rolling(52).min()) / 2).shift(26)

        return {
            "ema20": ema20, "ema50": ema50, "ema200": ema200,
            "sma50": sma50, "sma200": sma200,
            "macd_line": macd_line, "macd_signal": macd_signal, "macd_hist": macd_hist,
            "rsi": rsi,
            "bb_upper": bb_upper, "bb_mid": bb_mid, "bb_lower": bb_lower,
            "bb_width": bb_width, "bb_pct_b": bb_pct_b,
            "stoch_k": stoch_k, "stoch_d": stoch_d,
            "atr": atr, "cci": cci, "wr": wr, "roc": roc,
            "adx": adx, "di_plus": di_plus, "di_minus": di_minus,
            "sar": sar, "obv": obv, "momentum": momentum,
            "tenkan": tenkan, "kijun": kijun,
            "senkou_a": senkou_a, "senkou_b": senkou_b,
        }

    @staticmethod
    def _calc_psar(high, low, close, af_start=0.02, af_max=0.2) -> pd.Series:
        """Simplified Parabolic SAR."""
        sar_vals = close.copy() * np.nan
        try:
            bull = True
            sar  = low.iloc[0]
            ep   = high.iloc[0]
            af   = af_start
            for i in range(1, len(close)):
                prev_sar = sar
                sar = prev_sar + af * (ep - prev_sar)
                if bull:
                    sar = min(sar, low.iloc[i-1], low.iloc[max(0,i-2)])
                    if low.iloc[i] < sar:
                        bull = False; sar = ep; ep = low.iloc[i]; af = af_start
                    else:
                        if high.iloc[i] > ep:
                            ep = high.iloc[i]
                            af = min(af + af_start, af_max)
                else:
                    sar = max(sar, high.iloc[i-1], high.iloc[max(0,i-2)])
                    if high.iloc[i] > sar:
                        bull = True; sar = ep; ep = high.iloc[i]; af = af_start
                    else:
                        if low.iloc[i] < ep:
                            ep = low.iloc[i]
                            af = min(af + af_start, af_max)
                sar_vals.iloc[i] = sar
        except Exception:
            pass
        return sar_vals

    # ── GENERATE SINYAL ───────────────────────────────────
    def get_signals(self) -> AnalysisReport:
        """Hasilkan semua sinyal berdasarkan nilai indikator terakhir."""
        d    = {k: v.iloc[-1] if not v.empty else np.nan for k, v in self._calc.items()}
        cp   = float(self.close.iloc[-1])
        report = AnalysisReport()
        report.current_price = cp
        report.timestamp = str(self.close.index[-1].date())
        sigs = []

        def safe(val):
            return float(val) if pd.notna(val) else 0.0

        # ── Tren ──────────────────────────────────────────
        sigs += [
            SignalResult("EMA 20",   safe(d["ema20"]),   self._signal(None, cp > safe(d["ema20"]),   cp < safe(d["ema20"])),   "Tren",  f"Harga {'di atas' if cp > safe(d['ema20']) else 'di bawah'} EMA20"),
            SignalResult("EMA 50",   safe(d["ema50"]),   self._signal(None, cp > safe(d["ema50"]),   cp < safe(d["ema50"])),   "Tren",  ""),
            SignalResult("EMA 200",  safe(d["ema200"]),  self._signal(None, cp > safe(d["ema200"]),  cp < safe(d["ema200"])),  "Tren",  "Tren jangka panjang"),
            SignalResult("SMA 50",   safe(d["sma50"]),   self._signal(None, cp > safe(d["sma50"]),   cp < safe(d["sma50"])),   "Tren",  ""),
            SignalResult("SMA 200",  safe(d["sma200"]),  self._signal(None, cp > safe(d["sma200"]),  cp < safe(d["sma200"])),  "Tren",  "Golden/Death cross"),
            SignalResult("MACD",     safe(d["macd_line"]),
                self._signal(None, safe(d["macd_line"]) > safe(d["macd_signal"]) and safe(d["macd_hist"]) > 0,
                                   safe(d["macd_line"]) < safe(d["macd_signal"]) and safe(d["macd_hist"]) < 0),
                "Tren", f"Hist: {safe(d['macd_hist']):.2f}"),
            SignalResult("Parabolic SAR", safe(d["sar"]),
                self._signal(None, cp > safe(d["sar"]), cp < safe(d["sar"])),
                "Tren", ""),
            SignalResult("ADX", safe(d["adx"]),
                self._signal(None,
                    safe(d["adx"]) > 25 and safe(d["di_plus"]) > safe(d["di_minus"]),
                    safe(d["adx"]) > 25 and safe(d["di_plus"]) < safe(d["di_minus"])),
                "Tren", f"Kekuatan tren: {'Kuat' if safe(d['adx'])>25 else 'Lemah'}"),
            SignalResult("Ichimoku", safe(d["tenkan"]),
                self._signal(None,
                    cp > max(safe(d["senkou_a"]), safe(d["senkou_b"])),
                    cp < min(safe(d["senkou_a"]), safe(d["senkou_b"]))),
                "Tren", "Posisi vs Kumo cloud"),
        ]

        # ── Momentum ──────────────────────────────────────
        rsi_val = safe(d["rsi"])
        sigs += [
            SignalResult("RSI (14)", rsi_val,
                self._signal(None, rsi_val < config.SIGNAL_THRESHOLDS["RSI_OVERSOLD"],
                                   rsi_val > config.SIGNAL_THRESHOLDS["RSI_OVERBOUGHT"]),
                "Momentum", f"{'Oversold' if rsi_val<30 else 'Overbought' if rsi_val>70 else 'Netral'}"),
            SignalResult("Stochastic %K", safe(d["stoch_k"]),
                self._signal(None, safe(d["stoch_k"]) < 20 and safe(d["stoch_k"]) > safe(d["stoch_d"]),
                                   safe(d["stoch_k"]) > 80 and safe(d["stoch_k"]) < safe(d["stoch_d"])),
                "Momentum", ""),
            SignalResult("CCI (20)", safe(d["cci"]),
                self._signal(None, safe(d["cci"]) < -100, safe(d["cci"]) > 100),
                "Momentum", ""),
            SignalResult("Williams %R", safe(d["wr"]),
                self._signal(None, safe(d["wr"]) < -80, safe(d["wr"]) > -20),
                "Momentum", ""),
            SignalResult("ROC (12)", safe(d["roc"]),
                self._signal(None, safe(d["roc"]) > 0, safe(d["roc"]) < 0),
                "Momentum", ""),
            SignalResult("Momentum", safe(d["momentum"]),
                self._signal(None, safe(d["momentum"]) > 0, safe(d["momentum"]) < 0),
                "Momentum", ""),
        ]

        # ── Volatilitas ───────────────────────────────────
        bb_pct = safe(d["bb_pct_b"])
        sigs += [
            SignalResult("BB Atas",  safe(d["bb_upper"]), "NETRAL", "Volatilitas", "Resistance dinamis"),
            SignalResult("BB Bawah", safe(d["bb_lower"]), "NETRAL", "Volatilitas", "Support dinamis"),
            SignalResult("BB %B",    bb_pct,
                self._signal(None, bb_pct < 0.2, bb_pct > 0.8),
                "Volatilitas", f"Posisi di band: {bb_pct:.2f}"),
            SignalResult("ATR (14)", safe(d["atr"]), "NETRAL", "Volatilitas",
                f"Range avg: ${safe(d['atr']):.2f}"),
        ]

        # ── Volume ────────────────────────────────────────
        sigs += [
            SignalResult("OBV", safe(d["obv"]), "NETRAL", "Volume", "On-Balance Volume"),
        ]

        # ── Hitung ringkasan ──────────────────────────────
        report.signals  = sigs
        buy_sigs  = [s for s in sigs if s.signal == "BELI"]
        sell_sigs = [s for s in sigs if s.signal == "JUAL"]
        neu_sigs  = [s for s in sigs if s.signal == "NETRAL"]

        report.buy_count     = len(buy_sigs)
        report.sell_count    = len(sell_sigs)
        report.neutral_count = len(neu_sigs)

        total = report.buy_count + report.sell_count
        if total == 0:
            report.overall_signal = "NETRAL"
            report.confidence     = 0.5
        else:
            buy_ratio = report.buy_count / total
            if buy_ratio >= 0.65:
                report.overall_signal = "BELI KUAT" if buy_ratio >= 0.80 else "BELI"
            elif buy_ratio <= 0.35:
                report.overall_signal = "JUAL KUAT" if buy_ratio <= 0.20 else "JUAL"
            else:
                report.overall_signal = "NETRAL"
            report.confidence = max(buy_ratio, 1 - buy_ratio)

        # ── Support & Resistance ──────────────────────────
        report.support_levels    = self._find_levels(mode="support")
        report.resistance_levels = self._find_levels(mode="resistance")

        return report

    def _find_levels(self, mode="support", n=3, window=20) -> list:
        """Temukan level support/resistance dari pivot points."""
        c  = self.close
        cp = float(c.iloc[-1])
        levels = []
        for i in range(window, len(c) - window):
            val = float(c.iloc[i])
            if mode == "support":
                if val == c.iloc[i-window:i+window].min() and val < cp:
                    levels.append(round(val, 2))
            else:
                if val == c.iloc[i-window:i+window].max() and val > cp:
                    levels.append(round(val, 2))
        # Ambil n level TERDEKAT ke harga sekarang (bukan swing paling ekstrem):
        #  • support   → nilai TERBESAR di bawah harga  → urut MENURUN, ambil n.
        #  • resistance → nilai TERKECIL di atas harga    → urut MENAIK, ambil n.
        # (Sebelumnya arah sort terbalik sehingga selalu memilih swing high/low
        #  2 tahun terjauh — mis. resistance 5200 / support 2565 saat harga 4215.)
        levels = sorted(set(levels), reverse=(mode == "support"))
        return levels[:n]

    def get_dataframe(self) -> pd.DataFrame:
        """Kembalikan DataFrame dengan semua kolom indikator."""
        df = self.df.copy()
        for name, series in self._calc.items():
            df[f"ind_{name}"] = series
        return df


# ─────────────────────────────────────────────────────────
#  TAMPILKAN LAPORAN DI TERMINAL
# ─────────────────────────────────────────────────────────
def print_report(report: AnalysisReport):
    SIG_COLOR = {
        "BELI": Fore.GREEN, "BELI KUAT": Fore.GREEN,
        "JUAL": Fore.RED,   "JUAL KUAT": Fore.RED,
        "NETRAL": Fore.YELLOW,
    }
    cat_order = ["Tren", "Momentum", "Volatilitas", "Volume"]

    print("\n" + "═"*68)
    print(f"  {'LAPORAN ANALISIS TEKNIKAL — FULENS':^64}")
    print("═"*68)
    print(f"  Tanggal   : {report.timestamp}")
    print(f"  Harga     : ${report.current_price:,.2f}")

    sig_clr = SIG_COLOR.get(report.overall_signal, Fore.YELLOW)
    print(f"  Sinyal    : {sig_clr}{report.overall_signal}{Style.RESET_ALL}")
    print(f"  Konfiden  : {report.confidence*100:.1f}%")
    print(f"  Beli/Jual/Netral: {report.buy_count} / {report.sell_count} / {report.neutral_count}")

    for cat in cat_order:
        cat_sigs = [s for s in report.signals if s.category == cat]
        if not cat_sigs:
            continue
        print(f"\n  ── {cat} {'─'*(52-len(cat))}")
        rows = []
        for s in cat_sigs:
            clr = SIG_COLOR.get(s.signal, Fore.YELLOW)
            sig_str = f"{clr}{s.signal}{Style.RESET_ALL}"
            rows.append([s.name, f"{s.value:,.2f}", sig_str, s.detail])
        print(tabulate(rows, headers=["Indikator","Nilai","Sinyal","Keterangan"],
                       tablefmt="simple", colalign=("left","right","left","left")))

    if report.resistance_levels:
        print(f"\n  Resistance: {' | '.join(f'${r:,.2f}' for r in report.resistance_levels)}")
    if report.support_levels:
        print(f"  Support   : {' | '.join(f'${s:,.2f}' for s in report.support_levels)}")

    print("\n" + "═"*68 + "\n")


# ─────────────────────────────────────────────────────────
#  ANALISIS MULTI-TIMEFRAME
# ─────────────────────────────────────────────────────────

# Mapping timeframe → jumlah candle dari data harian
# Data kita adalah daily, jadi kita resample/simulasi TF pendek
# dari data yang ada. TF < 1D diestimasi dari volatilitas harian.
TIMEFRAMES = {
    "15 Menit" : {"bars": 5,   "weight_vol": 0.30, "label": "15m"},
    "30 Menit" : {"bars": 10,  "weight_vol": 0.28, "label": "30m"},
    "1 Jam"    : {"bars": 20,  "weight_vol": 0.25, "label": "1H"},
    "4 Jam"    : {"bars": 40,  "weight_vol": 0.20, "label": "4H"},
    "1 Hari"   : {"bars": 60,  "weight_vol": 0.10, "label": "1D"},
    "1 Minggu" : {"bars": 120, "weight_vol": 0.05, "label": "1W"},
    "1 Bulan"  : {"bars": 250, "weight_vol": 0.03, "label": "1M"},
    "1 Tahun"  : {"bars": 500, "weight_vol": 0.01, "label": "1Y"},
}

def _resample_to_tf(df: pd.DataFrame, bars: int, weight_vol: float) -> pd.DataFrame:
    """
    Simulasi timeframe lebih pendek dari data harian.
    Untuk TF < 1D: tambahkan noise proporsional ke volatilitas harian (ATR).
    Untuk TF >= 1D: slice n bar terakhir langsung.
    """
    n = min(bars, len(df))
    sliced = df.tail(n).copy()

    if weight_vol > 0.10:
        # Simulasi intraday: tambah variasi kecil berdasarkan ATR harian
        atr_est = sliced["gold_close"].diff().abs().mean()
        noise_scale = atr_est * weight_vol
        rng = np.random.default_rng(seed=42)  # seed tetap agar konsisten
        noise = rng.normal(0, noise_scale, len(sliced))
        sliced = sliced.copy()
        sliced["gold_close"] = (sliced["gold_close"] + noise).clip(lower=1)
        sliced["gold_high"]  = sliced["gold_high"]  + abs(noise)
        sliced["gold_low"]   = sliced["gold_low"]   - abs(noise)

    return sliced


def analyze_multi_timeframe(df: pd.DataFrame) -> list:
    """Jalankan analisis teknikal untuk setiap timeframe."""
    results = []
    for tf_name, cfg in TIMEFRAMES.items():
        try:
            tf_df = _resample_to_tf(df, cfg["bars"], cfg["weight_vol"])
            if len(tf_df) < 30:
                continue
            analyzer = TechnicalAnalyzer(tf_df)
            report   = analyzer.get_signals()
            results.append({
                "timeframe" : tf_name,
                "label"     : cfg["label"],
                "signal"    : report.overall_signal,
                "confidence": report.confidence,
                "buy"       : report.buy_count,
                "sell"      : report.sell_count,
                "neutral"   : report.neutral_count,
                "price"     : report.current_price,
                "rsi"       : next((s.value for s in report.signals if s.name == "RSI (14)"), 0),
                "macd"      : next((s.value for s in report.signals if s.name == "MACD"), 0),
                "adx"       : next((s.value for s in report.signals if s.name == "ADX"), 0),
            })
        except Exception as e:
            results.append({"timeframe": tf_name, "label": cfg["label"],
                            "signal": "ERROR", "confidence": 0,
                            "buy": 0, "sell": 0, "neutral": 0,
                            "price": 0, "rsi": 0, "macd": 0, "adx": 0})
    return results


def print_multi_timeframe_report(results: list, current_price: float):
    """Tampilkan laporan multi-timeframe di terminal."""
    SIG_COLOR = {
        "BELI": Fore.GREEN, "BELI KUAT": Fore.GREEN,
        "JUAL": Fore.RED,   "JUAL KUAT": Fore.RED,
        "NETRAL": Fore.YELLOW, "ERROR": Fore.WHITE,
    }
    SIG_ICON = {
        "BELI": "▲", "BELI KUAT": "▲▲",
        "JUAL": "▼", "JUAL KUAT": "▼▼",
        "NETRAL": "◆", "ERROR": "?",
    }

    print("\n" + "═"*78)
    print(f"  {'ANALISIS MULTI-TIMEFRAME — FULENS':^74}")
    print(f"  {'Harga Referensi: $' + f'{current_price:,.2f}':^74}")
    print("═"*78)

    # Hitung konsensus keseluruhan
    buy_tfs  = [r for r in results if "BELI" in r["signal"]]
    sell_tfs = [r for r in results if "JUAL" in r["signal"]]
    neu_tfs  = [r for r in results if r["signal"] == "NETRAL"]

    rows = []
    for r in results:
        clr     = SIG_COLOR.get(r["signal"], Fore.WHITE)
        icon    = SIG_ICON.get(r["signal"], "?")
        sig_str = f"{clr}{icon} {r['signal']}{Style.RESET_ALL}"
        conf    = f"{r['confidence']*100:.0f}%"
        bsn     = f"{r['buy']}B / {r['sell']}J / {r['neutral']}N"
        rsi_str = f"{r['rsi']:.1f}" if r['rsi'] else "-"
        adx_str = f"{r['adx']:.1f}" if r['adx'] else "-"
        rows.append([r["timeframe"], r["label"], sig_str, conf, bsn, rsi_str, adx_str])

    print(tabulate(
        rows,
        headers=["Timeframe", "TF", "Sinyal", "Konfiden", "B/J/N", "RSI", "ADX"],
        tablefmt="simple",
        colalign=("left","center","left","center","center","right","right")
    ))

    # Ringkasan konsensus
    print("\n" + "─"*78)
    total_tf = len(results)
    print(f"  Konsensus  : {Fore.GREEN}{len(buy_tfs)} Bullish{Style.RESET_ALL} | "
          f"{Fore.RED}{len(sell_tfs)} Bearish{Style.RESET_ALL} | "
          f"{Fore.YELLOW}{len(neu_tfs)} Netral{Style.RESET_ALL}  "
          f"(dari {total_tf} timeframe)")

    # Tentukan bias keseluruhan
    if len(buy_tfs) > len(sell_tfs) * 1.5:
        bias = f"{Fore.GREEN}BULLISH DOMINAN{Style.RESET_ALL}"
        saran = "Tren naik mendominasi di mayoritas timeframe. Waspadai resistensi."
    elif len(sell_tfs) > len(buy_tfs) * 1.5:
        bias = f"{Fore.RED}BEARISH DOMINAN{Style.RESET_ALL}"
        saran = "Tekanan jual kuat di mayoritas timeframe. Waspadai support."
    else:
        bias = f"{Fore.YELLOW}MIXED / KONSOLIDASI{Style.RESET_ALL}"
        saran = "Sinyal bertentangan antar timeframe. Tunggu konfirmasi arah."

    print(f"  Bias       : {bias}")
    print(f"  Analisis   : {saran}")

    # Saran per kelompok TF
    print("\n  ── Ringkasan per Kelompok ─────────────────────────────────────────")
    short_tfs  = [r for r in results if r["label"] in ["15m","30m","1H"]]
    mid_tfs    = [r for r in results if r["label"] in ["4H","1D"]]
    long_tfs   = [r for r in results if r["label"] in ["1W","1M","1Y"]]

    def group_bias(group):
        b = sum(1 for r in group if "BELI" in r["signal"])
        s = sum(1 for r in group if "JUAL" in r["signal"])
        if b > s: return f"{Fore.GREEN}Bullish{Style.RESET_ALL}"
        if s > b: return f"{Fore.RED}Bearish{Style.RESET_ALL}"
        return f"{Fore.YELLOW}Netral{Style.RESET_ALL}"

    print(f"  Jangka Pendek (15m–1H) : {group_bias(short_tfs)}"
          f"  → Cocok untuk scalping/intraday")
    print(f"  Jangka Menengah (4H–1D): {group_bias(mid_tfs)}"
          f"  → Cocok untuk swing trading")
    print(f"  Jangka Panjang  (1W–1Y): {group_bias(long_tfs)}"
          f"  → Cocok untuk posisi/investasi")

    print("\n" + "═"*78 + "\n")


# ─────────────────────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────────────────────
if __name__ == "__main__":
    from data_pipeline import load_processed_data, run_pipeline

    print("Memuat data...")
    try:
        df = load_processed_data()
    except FileNotFoundError:
        print("Data belum ada, menjalankan pipeline dulu...")
        df = run_pipeline()

    if df is not None and not df.empty:
        # ── Laporan indikator standar (1D)
        analyzer = TechnicalAnalyzer(df)
        report   = analyzer.get_signals()
        print_report(report)

        # ── Laporan multi-timeframe
        print("Menghitung analisis multi-timeframe...")
        mtf_results = analyze_multi_timeframe(df)
        print_multi_timeframe_report(mtf_results, report.current_price)
    else:
        print("Gagal memuat data.")
