"""
FuLens — Modul Indikator Teknikal (4 komponen)

Hitungan MURNI saja: Bollinger Bands, Stochastic, MACD, ATR, pivot & S&R.
Tidak ada keputusan di sini — keputusan ada di `strategy.py`. Pemisahan ini
disengaja: gerbang strategi bisa di-backtest tanpa menyeret lapisan tampilan.

Sengaja DIBUANG (dulu ikut voting): EMA20/50/200, SMA50/200, RSI, CCI,
Williams %R, ROC, Momentum, ADX, Parabolic SAR, Ichimoku, OBV. Alasannya bukan
sekadar "terlalu banyak" — lima di antaranya (EMA20/50/200, SMA50/200) mengukur
hal yang identik: "harga di atas/di bawah garis rata-rata". Ditambah PSAR &
Ichimoku yang juga mengukur posisi tren, votingnya bukan 16 pendapat independen
melainkan satu pendapat tren yang berteriak tujuh kali — sehingga setiap setup
reversal otomatis kalah suara. Lihat strategy.py untuk penjelasan lengkapnya.

ATR TETAP ADA tapi bukan komponen sinyal: risk_manager memakainya untuk ukuran
lot dan jarak SL/TP.

Jalankan standalone: python indicators.py
"""

import warnings
warnings.filterwarnings("ignore")

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from colorama import Fore, Style, init
from tabulate import tabulate

init(autoreset=True)
import config
import strategy


# ─────────────────────────────────────────────────────────
#  DATA CLASS HASIL INDIKATOR
# ─────────────────────────────────────────────────────────
@dataclass
class SignalResult:
    name    : str
    value   : float
    signal  : str        # "BELI" | "JUAL" | "NETRAL"
    category: str        # "Tren" | "Momentum" | "Volatilitas"
    detail  : str = ""


@dataclass
class AnalysisReport:
    timestamp       : str = ""
    current_price   : float = 0.0
    signals         : list = field(default_factory=list)
    # Sisa dari era voting. Dengan gerbang AND, "9 beli vs 3 jual" tidak punya
    # arti — hasilnya biner. Dibiarkan 0 supaya terlihat jelas sudah tidak
    # berlaku, bukan diisi angka yang tampak masuk akal tapi menyesatkan.
    # Penggantinya: `gates`.
    buy_count       : int = 0
    sell_count      : int = 0
    neutral_count   : int = 0
    overall_signal  : str = "NETRAL"
    confidence      : float = 0.0    # 0..1 (signal_engine mengalikannya × 100)
    support_levels  : list = field(default_factory=list)
    resistance_levels: list = field(default_factory=list)
    # Baru: hasil gerbang konfluensi — inti laporan sekarang.
    gates           : list = field(default_factory=list)
    mode            : str = "swing"
    direction       : str | None = None
    # Arah yang gerbangnya sedang ditampilkan saat belum ada setup (paling dekat
    # lolos). Tanpa ini UI menyangka diagnosa selalu untuk BUY.
    probe_direction : str | None = None
    atr             : float = 0.0    # ATR bar tertutup — dasar jarak SL/TP di EA


# ─────────────────────────────────────────────────────────
#  PIVOT (fractal) — dipakai S&R DAN deteksi divergence
# ─────────────────────────────────────────────────────────
def find_pivots(series: pd.Series, window: int, mode: str) -> list:
    """Indeks bar yang jadi swing pivot (fractal) pada `series`.

    Bar ke-i disebut swing low bila nilainya terendah di antara `window` bar
    sebelum dan sesudahnya; swing high sebaliknya.

    Catatan penting: sebuah pivot baru bisa dipastikan setelah `window` bar
    berikutnya terbentuk — jadi pivot termuda selalu minimal `window` bar di
    belakang. Itu sifat bawaan fractal, bukan bug; konsekuensinya deteksi
    divergence memang selalu telat sedikit.

    Jendela kecil itu disengaja. Versi lama memakai `close` dengan jendela ±20
    bar: pada tren naik kuat, low pullback TIDAK pernah jadi minimum jendela 40
    bar, jadi yang lolos hanya titik AWAL tren → support ratusan dolar jauhnya
    (mis. 3293 saat harga 4215). Jendela ±5 pada high/low menangkap swing yang
    sebenarnya.
    """
    vals = series.values
    out = []
    for i in range(window, len(vals) - window):
        seg = vals[i - window : i + window + 1]
        v = vals[i]
        if not np.isfinite(v):
            continue
        if mode == "low" and v == seg.min():
            out.append(i)
        elif mode == "high" and v == seg.max():
            out.append(i)
    return out


# ─────────────────────────────────────────────────────────
#  KELAS UTAMA
# ─────────────────────────────────────────────────────────
class TechnicalAnalyzer:
    """Hitung 4 komponen strategi + ATR dari DataFrame OHLCV."""

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

    # ── KALKULASI ─────────────────────────────────────────
    def _calculate_all(self) -> dict:
        c = self.close; h = self.high; l = self.low
        p = self.p
        sp = config.STRATEGY_PARAMS

        # ── MACD ───────────────────────────────────────────
        macd_line   = self._ema(c, p["MACD_FAST"]) - self._ema(c, p["MACD_SLOW"])
        macd_signal = self._ema(macd_line, p["MACD_SIGNAL"])
        macd_hist   = macd_line - macd_signal

        # ── Bollinger Bands ────────────────────────────────
        bb_mid   = self._sma(c, p["BB_PERIOD"])
        bb_std   = c.rolling(p["BB_PERIOD"]).std()
        bb_upper = bb_mid + p["BB_STD"] * bb_std
        bb_lower = bb_mid - p["BB_STD"] * bb_std
        # bb_width dinormalisasi ke % dari mid → sebanding lintas simbol dan
        # lintas level harga. Ini yang dipakai gerbang squeeze (via persentil).
        bb_width = (bb_upper - bb_lower) / bb_mid * 100
        bb_pct_b = (c - bb_lower) / (bb_upper - bb_lower)
        # Acuan squeeze: persentil lebar BB terhadap DIRINYA SENDIRI selama N bar.
        # Dihitung sekali di sini, bukan di dalam gerbang — gerbang dipanggil dua
        # kali per bar (BUY & SELL) dan rolling quantile itu mahal.
        # min_periods: separuh jendela sudah cukup untuk acuan yang bermakna,
        # supaya simbol/timeframe dengan data pendek tidak mati total.
        sq_win = sp["BB_SQUEEZE_WINDOW"]
        bb_width_ref = bb_width.rolling(sq_win, min_periods=sq_win // 2).quantile(
            sp["BB_SQUEEZE_PCTILE"] / 100.0)

        # ── Stochastic ────────────────────────────────────
        low_min  = l.rolling(p["STOCH_K"]).min()
        high_max = h.rolling(p["STOCH_K"]).max()
        stoch_k  = 100 * (c - low_min) / (high_max - low_min).replace(0, np.nan)
        stoch_d  = self._sma(stoch_k, p["STOCH_D"])

        # ── ATR (mekanika risiko, bukan sinyal) ───────────
        tr1 = h - l
        tr2 = (h - c.shift()).abs()
        tr3 = (l - c.shift()).abs()
        tr  = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = self._ema(tr, p["ATR_PERIOD"])

        # ── EMA tren (gerbang arah, BUKAN pemilih) ────────
        ema_trend = self._ema(c, p["EMA_TREND"])

        return {
            "close": c, "high": h, "low": l,
            "macd_line": macd_line, "macd_signal": macd_signal, "macd_hist": macd_hist,
            "bb_upper": bb_upper, "bb_mid": bb_mid, "bb_lower": bb_lower,
            "bb_width": bb_width, "bb_pct_b": bb_pct_b,
            "bb_width_ref": bb_width_ref,
            "stoch_k": stoch_k, "stoch_d": stoch_d,
            "atr": atr, "ema_trend": ema_trend,
        }

    # ── LAPORAN ───────────────────────────────────────────
    def get_signals(self, mode: str = "swing") -> AnalysisReport:
        """Jalankan gerbang strategi, bungkus jadi AnalysisReport.

        Bentuk AnalysisReport dipertahankan supaya /api/v1/indicators dan model
        Flutter yang ada tidak harus diubah serentak.
        """
        # S&R HARUS disaring terhadap bar yang sama dengan yang dinilai gerbang.
        # Kalau tidak: level disaring vs bar berjalan (mis. 4215) tapi gerbang
        # menilai bar tertutup (mis. 4090) → muncul "support" di ATAS harga yang
        # dinilai, dan gerbang Ruang S&R jadi salah hitung.
        idx = len(self.close) + strategy.BAR_CLOSED
        if idx < 0:
            idx = len(self.close) - 1
        support    = self._find_levels(mode="support", idx=idx)
        resistance = self._find_levels(mode="resistance", idx=idx)
        setup = strategy.evaluate(self._calc, support, resistance, mode=mode, idx=idx)

        report = AnalysisReport()
        report.timestamp         = setup.timestamp
        report.current_price     = setup.current_price
        report.overall_signal    = setup.signal
        report.confidence        = setup.quality / 100.0   # 0..1
        report.support_levels    = support
        report.resistance_levels = resistance
        report.gates             = [g.to_dict() for g in setup.gates]
        report.mode              = setup.mode
        report.direction         = setup.direction
        report.probe_direction   = setup.probe_direction
        atr = self._calc["atr"].iloc[idx] if len(self._calc["atr"]) else float("nan")
        report.atr               = float(atr) if pd.notna(atr) else 0.0
        report.signals           = self._component_rows(idx)
        return report

    def _component_rows(self, idx: int | None = None) -> list:
        """Baris nilai mentah 4 komponen — untuk dilihat, bukan untuk voting.

        `idx` WAJIB bar yang sama dengan yang dinilai gerbang. Kalau tidak,
        trading_advisor.dart mencampur nilai dari dua bar berbeda: ia menghitung
        zona entry dari BB Bawah (bar berjalan) tapi memakai `signal.support`
        (bar tertutup). Gejalanya kentara — BB Bawah bisa muncul DI ATAS harga
        bar tertutup, jadi "support dinamis" di atas harga.

        Kategori memakai nama lama ("Tren"/"Momentum"/"Volatilitas") demi model
        IndicatorSignal di Flutter yang masih membacanya.
        """
        idx = -1 if idx is None else idx
        d = {k: (v.iloc[idx] if len(v) else np.nan) for k, v in self._calc.items()}

        def safe(x):
            return float(x) if pd.notna(x) else 0.0

        macd_l, macd_s = safe(d["macd_line"]), safe(d["macd_signal"])
        hist  = safe(d["macd_hist"])
        k, dd = safe(d["stoch_k"]), safe(d["stoch_d"])
        pct_b = safe(d["bb_pct_b"])
        # Status squeeze dibaca dari acuan yang SAMA dengan gate_bb_squeeze —
        # jangan hitung ulang di sini, itu cara klasik UI dan gerbang jadi beda.
        _sq_ref = float(d["bb_width_ref"]) if pd.notna(d["bb_width_ref"]) else np.nan
        _sq_pct = strategy._p("BB_SQUEEZE_PCTILE")
        _squeeze_on = np.isfinite(_sq_ref) and safe(d["bb_width"]) < _sq_ref
        so    = strategy._p("STOCH_OVERSOLD")
        sob   = strategy._p("STOCH_OVERBOUGHT")

        return [
            SignalResult("MACD", macd_l,
                self._signal(None, macd_l > macd_s and hist > 0,
                                   macd_l < macd_s and hist < 0),
                "Tren", f"Signal {macd_s:.2f} · Hist {hist:+.2f}"),
            SignalResult("Stochastic %K", k,
                self._signal(None, k < so and k > dd, k > sob and k < dd),
                "Momentum",
                f"%D {dd:.1f} · "
                f"{'oversold' if k < so else 'overbought' if k > sob else 'netral'}"),
            SignalResult("EMA 200", safe(d["ema_trend"]),
                self._signal(None,
                             safe(d["close"]) > safe(d["ema_trend"]),
                             safe(d["close"]) < safe(d["ema_trend"])),
                "Tren", "Sisi tren besar - gerbang arah di mode swing"),
            SignalResult("BB %B", pct_b,
                self._signal(None, pct_b < 0.2, pct_b > 0.8),
                "Volatilitas", f"Posisi di dalam pita: {pct_b:.2f}"),
            # Baris ini kini punya makna keputusan: ia GERBANG mode scalping.
            # Ditampilkan bersama acuannya supaya angka lebarnya bisa dinilai —
            # "1.8%" sendirian tak berarti apa-apa tanpa tahu ambangnya.
            SignalResult("BB Lebar", safe(d["bb_width"]),
                "BELI" if _squeeze_on else "NETRAL", "Volatilitas",
                (f"Lebar {safe(d['bb_width']):.2f}% vs acuan p{_sq_pct} "
                 f"{_sq_ref:.2f}% — "
                 + ("MENYEMPIT, gerbang scalping terbuka" if _squeeze_on
                    else "melebar, gerbang scalping tertutup"))
                if np.isfinite(_sq_ref) else
                "Lebar pita (% dari mid) — acuan squeeze belum cukup data"),
            # "BB Atas"/"BB Bawah"/"ATR (14)" — NAMA INI KONTRAK, jangan diubah.
            # trading_advisor.dart mencarinya lewat _getIndicatorValue(nama) dan
            # DIAM-DIAM jatuh ke nilai karangan bila tak ketemu (mis. BB Atas →
            # harga × 1.02), lalu memakainya untuk zona entry & target. Ketiganya
            # tetap dihitung otak, jadi nama lama dipertahankan agar advisor dapat
            # angka ASLI, bukan tebakan.
            SignalResult("BB Atas", safe(d["bb_upper"]), "NETRAL", "Volatilitas",
                "Batas atas pita — resistance dinamis"),
            SignalResult("BB Bawah", safe(d["bb_lower"]), "NETRAL", "Volatilitas",
                "Batas bawah pita — support dinamis"),
            SignalResult("ATR (14)", safe(d["atr"]), "NETRAL", "Volatilitas",
                f"Range rata-rata: {safe(d['atr']):.2f} (dipakai lot & SL/TP)"),
        ]

    def _find_levels(self, mode="support", n=3, window=None, min_gap_pct=None,
                     idx=None) -> list:
        """Level S&R dari swing pivot, n TERDEKAT ke harga pada bar `idx`.

        `idx` default = bar terakhir. Saat dipanggil dari get_signals, ia diisi
        bar TERTUTUP supaya sejalan dengan gerbang — support harus benar-benar di
        bawah harga yang dinilai, bukan di bawah harga bar berjalan.

        `min_gap_pct` menyaring level berdempetan agar n level yang keluar
        benar-benar berbeda, bukan tiga pivot dari satu swing yang sama.
        """
        window = window if window is not None else strategy._p("SR_PIVOT_WINDOW")
        min_gap_pct = (min_gap_pct if min_gap_pct is not None
                       else strategy._p("SR_MIN_GAP_PCT"))
        idx = len(self.close) - 1 if idx is None else idx

        cp  = float(self.close.iloc[idx])
        src = self.low if mode == "support" else self.high
        piv = find_pivots(src, window, "low" if mode == "support" else "high")

        levels = []
        for i in piv:
            if i > idx:
                continue          # jangan mengintip bar setelah bar yang dinilai
            v = float(src.iloc[i])
            if (mode == "support" and v < cp) or (mode == "resistance" and v > cp):
                levels.append(v)

        # Terdekat ke harga lebih dulu: support = terbesar di bawah harga,
        # resistance = terkecil di atas harga. (Arah sort ini pernah terbalik →
        # selalu mengambil swing paling ekstrem, bukan yang terdekat.)
        levels.sort(reverse=(mode == "support"))

        out: list = []
        for v in levels:
            if all(abs(v - u) / cp * 100 >= min_gap_pct for u in out):
                out.append(round(v, 2))
                if len(out) == n:
                    break
        return out

    def get_dataframe(self) -> pd.DataFrame:
        """DataFrame + semua kolom indikator (prefix ind_)."""
        df = self.df.copy()
        for name, series in self._calc.items():
            if name in ("close", "high", "low"):
                continue
            df[f"ind_{name}"] = series
        return df


# ─────────────────────────────────────────────────────────
#  TAMPILKAN LAPORAN DI TERMINAL
# ─────────────────────────────────────────────────────────
SIG_COLOR = {
    "BELI": Fore.GREEN, "BELI KUAT": Fore.GREEN,
    "JUAL": Fore.RED,   "JUAL KUAT": Fore.RED,
    "NETRAL": Fore.YELLOW, "ERROR": Fore.WHITE,
}


def print_report(report: AnalysisReport):
    print("\n" + "═" * 68)
    print(f"  {'LAPORAN SETUP — FULENS':^64}")
    print("═" * 68)
    print(f"  Tanggal   : {report.timestamp}  (bar tertutup)")
    print(f"  Harga     : ${report.current_price:,.2f}")
    print(f"  Mode      : {report.mode.upper()}")

    clr = SIG_COLOR.get(report.overall_signal, Fore.YELLOW)
    print(f"  Sinyal    : {clr}{report.overall_signal}{Style.RESET_ALL}")
    print(f"  Kualitas  : {report.confidence * 100:.1f}%")

    print("\n  ── Gerbang Konfluensi ─────────────────────────────────")
    rows = []
    for g in report.gates:
        mark = (f"{Fore.GREEN}LOLOS{Style.RESET_ALL}" if g["passed"]
                else f"{Fore.RED}GAGAL{Style.RESET_ALL}")
        rows.append([g["name"], mark,
                     f"{g['score']:.2f}" if g["passed"] else "-", g["detail"]])
    print(tabulate(rows, headers=["Gerbang", "Status", "Skor", "Keterangan"],
                   tablefmt="simple", colalign=("left", "left", "right", "left")))

    print("\n  ── Nilai Komponen ─────────────────────────────────────")
    rows = []
    for s in report.signals:
        c = SIG_COLOR.get(s.signal, Fore.YELLOW)
        rows.append([s.name, f"{s.value:,.2f}",
                     f"{c}{s.signal}{Style.RESET_ALL}", s.detail])
    print(tabulate(rows, headers=["Komponen", "Nilai", "Baca", "Keterangan"],
                   tablefmt="simple", colalign=("left", "right", "left", "left")))

    if report.resistance_levels:
        print(f"\n  Resistance: {' | '.join(f'${r:,.2f}' for r in report.resistance_levels)}")
    if report.support_levels:
        print(f"  Support   : {' | '.join(f'${s:,.2f}' for s in report.support_levels)}")
    print("\n" + "═" * 68 + "\n")


# ─────────────────────────────────────────────────────────
#  ANALISIS MULTI-TIMEFRAME
# ─────────────────────────────────────────────────────────
# ⚠️ PERINGATAN — data intraday di sini TIDAK NYATA.
# Sumber brain masih yfinance harian, jadi TF < 1D "disimulasikan" dengan
# menambahkan noise acak ke data harian (lihat _resample_to_tf). Sinyal 15m/30m/
# 1H/4H dari sini adalah angka KARANGAN dan tidak boleh dipakai untuk keputusan.
# Ini hilang begitu EA MQL5 mengirim OHLC asli per timeframe dari MT5.
TIMEFRAMES = {
    "15 Menit" : {"bars": 5,   "weight_vol": 0.30, "label": "15m", "synthetic": True},
    "30 Menit" : {"bars": 10,  "weight_vol": 0.28, "label": "30m", "synthetic": True},
    "1 Jam"    : {"bars": 20,  "weight_vol": 0.25, "label": "1H",  "synthetic": True},
    "4 Jam"    : {"bars": 40,  "weight_vol": 0.20, "label": "4H",  "synthetic": True},
    "1 Hari"   : {"bars": 60,  "weight_vol": 0.10, "label": "1D",  "synthetic": False},
    "1 Minggu" : {"bars": 120, "weight_vol": 0.05, "label": "1W",  "synthetic": False},
    "1 Bulan"  : {"bars": 250, "weight_vol": 0.03, "label": "1M",  "synthetic": False},
    "1 Tahun"  : {"bars": 500, "weight_vol": 0.01, "label": "1Y",  "synthetic": False},
}


def _resample_to_tf(df: pd.DataFrame, bars: int, weight_vol: float) -> pd.DataFrame:
    """Ambil n bar terakhir; untuk TF < 1D tambahkan noise acak (SINTETIS!).

    Lihat peringatan di atas TIMEFRAMES — cabang noise ini mengarang data.
    """
    n = min(bars, len(df))
    sliced = df.tail(n).copy()

    if weight_vol > 0.10:
        atr_est = sliced["gold_close"].diff().abs().mean()
        noise_scale = atr_est * weight_vol
        rng = np.random.default_rng(seed=42)   # seed tetap agar konsisten
        noise = rng.normal(0, noise_scale, len(sliced))
        sliced["gold_close"] = (sliced["gold_close"] + noise).clip(lower=1)
        sliced["gold_high"]  = sliced["gold_high"] + abs(noise)
        sliced["gold_low"]   = sliced["gold_low"] - abs(noise)

    return sliced


def analyze_multi_timeframe(df: pd.DataFrame, mode: str = "swing") -> list:
    """Jalankan gerbang strategi untuk tiap timeframe.

    `synthetic: True` menandai TF yang datanya dikarang — diteruskan ke UI agar
    pengguna tahu mana yang boleh dipercaya.
    """
    results = []
    for tf_name, cfg in TIMEFRAMES.items():
        base = {"timeframe": tf_name, "label": cfg["label"],
                "synthetic": cfg["synthetic"]}
        try:
            tf_df = _resample_to_tf(df, cfg["bars"], cfg["weight_vol"])
            if len(tf_df) < 30:
                continue
            rep = TechnicalAnalyzer(tf_df).get_signals(mode=mode)
            results.append({
                **base,
                "signal"     : rep.overall_signal,
                "confidence" : rep.confidence,
                "price"      : rep.current_price,
                "direction"  : rep.direction,
                "gates_pass" : sum(1 for g in rep.gates if g["passed"]),
                "gates_total": len(rep.gates),
            })
        except Exception:
            results.append({**base, "signal": "ERROR", "confidence": 0,
                            "price": 0, "direction": None,
                            "gates_pass": 0, "gates_total": 0})
    return results


def print_multi_timeframe_report(results: list, current_price: float):
    print("\n" + "═" * 78)
    print(f"  {'SETUP MULTI-TIMEFRAME — FULENS':^74}")
    print(f"  {'Harga Referensi: $' + f'{current_price:,.2f}':^74}")
    print("═" * 78)

    buy_tfs  = [r for r in results if "BELI" in r["signal"]]
    sell_tfs = [r for r in results if "JUAL" in r["signal"]]
    neu_tfs  = [r for r in results if r["signal"] == "NETRAL"]

    rows = []
    for r in results:
        clr = SIG_COLOR.get(r["signal"], Fore.WHITE)
        flag = (f"{Fore.YELLOW}sintetis{Style.RESET_ALL}"
                if r.get("synthetic") else "asli")
        rows.append([r["timeframe"], r["label"],
                     f"{clr}{r['signal']}{Style.RESET_ALL}",
                     f"{r['confidence'] * 100:.0f}%",
                     f"{r['gates_pass']}/{r['gates_total']}", flag])
    print(tabulate(rows,
                   headers=["Timeframe", "TF", "Sinyal", "Kualitas", "Gerbang", "Data"],
                   tablefmt="simple",
                   colalign=("left", "center", "left", "center", "center", "left")))

    print("\n" + "─" * 78)
    print(f"  Konsensus  : {Fore.GREEN}{len(buy_tfs)} Bullish{Style.RESET_ALL} | "
          f"{Fore.RED}{len(sell_tfs)} Bearish{Style.RESET_ALL} | "
          f"{Fore.YELLOW}{len(neu_tfs)} Netral{Style.RESET_ALL}  "
          f"(dari {len(results)} timeframe)")
    print(f"  {Fore.YELLOW}Catatan{Style.RESET_ALL}    : baris 'sintetis' memakai "
          f"data harian + noise acak — jangan dipakai untuk keputusan.")
    print("\n" + "═" * 78 + "\n")


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
        analyzer = TechnicalAnalyzer(df)
        for m in ("swing", "scalping"):
            print_report(analyzer.get_signals(mode=m))

        print("Menghitung setup multi-timeframe...")
        mtf = analyze_multi_timeframe(df)
        print_multi_timeframe_report(mtf, float(df["gold_close"].iloc[-1]))
    else:
        print("Gagal memuat data.")
