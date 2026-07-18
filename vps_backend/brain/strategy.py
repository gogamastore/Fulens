"""Mesin strategi FuLens — rantai gerbang AND pada bar TERTUTUP.

Dua mode dengan PERAN BERBEDA, bukan versi cepat/lambat dari hal yang sama:

  SWING    : Stochastic cross -> Tren EMA200 -> Sentuh S&R
             Ikut tren besar, masuk saat koreksi menyentuh S&R. Konsekuensinya
             ia BUY-only selama uptrend dan SELL-only selama downtrend — itu
             memang maksudnya, bukan cacat.

  SCALPING : Stochastic cross -> BB Squeeze
             Tidak peduli tren. Menunggu kompresi volatilitas lalu ikut arah
             Stochastic, sehingga SEIMBANG BUY/SELL — cari profit harian dua
             arah. Squeeze itu netral arah; itulah kuncinya.

Mode DIPILIH DARI FLUTTER (BotSettings.trading_mode), bukan dari EA maupun dari
timeframe. EA murni tangan+mata: kirim OHLC, terima perintah. Simbol mana yang
ditradingkan ditentukan chart tempat EA dipasang — jadi mode berlaku untuk semua
simbol.

Tiap komponen adalah GERBANG (AND), bukan pemilih. Ini menggantikan voting 16
indikator yang lama, yang secara matematis ANTI-REVERSAL: 5 dari 16 pemilih
(EMA20/50/200, SMA50/200) mengukur hal identik — "harga di atas/di bawah garis
rata-rata" — sehingga tiap setup reversal otomatis kalah suara.

Dua aturan yang berlaku di semua gerbang:

1. BAR TERTUTUP. Semua dinilai di `idx = -2` (pandas), bukan `-1` — bar terakhir
   masih berjalan dan berubah tiap tick, jadi memakainya bikin sinyal repaint.

2. CONFIDENCE BUKAN RASIO SUARA. Dengan AND hasilnya biner, jadi rasio kehilangan
   makna — padahal `min_confidence` di executor dan UI Flutter memakai angka
   0-100. Gantinya skor kualitas: tiap gerbang menyumbang sub-skor 0..1 yang
   mengukur SEBERAPA BAIK syaratnya dipenuhi, lalu quality = 50 + 50 × rata-rata.
   Setup yang lolos selalu ≥ 50, setup sempurna = 100.
"""
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

import config

# Bar yang dinilai: -1 = bar berjalan (repaint), -2 = bar tertutup terakhir.
BAR_CLOSED = -2


@dataclass
class GateResult:
    """Satu gerbang: lolos atau tidak, plus seberapa baik ia dipenuhi.

    `informational=True` → dihitung & dilaporkan, tapi TIDAK memblokir entry dan
    tidak ikut skor kualitas.
    """
    name: str
    passed: bool
    score: float = 0.0      # 0..1 — hanya bermakna bila passed
    detail: str = ""
    informational: bool = False

    def to_dict(self) -> dict:
        return {"name": self.name, "passed": self.passed,
                "score": round(self.score, 3), "detail": self.detail,
                "informational": self.informational}


@dataclass
class SetupReport:
    """Hasil evaluasi strategi pada satu simbol/timeframe."""
    mode: str = "swing"
    timestamp: str = ""
    current_price: float = 0.0
    direction: str | None = None        # "BUY" | "SELL" | None
    signal: str = "NETRAL"              # BELI KUAT / BELI / NETRAL / JUAL / JUAL KUAT
    quality: float = 0.0                # 0-100 → dipakai sebagai `confidence`
    gates: list = field(default_factory=list)
    support_levels: list = field(default_factory=list)
    resistance_levels: list = field(default_factory=list)
    # Saat tak ada setup, `gates` berisi diagnosa untuk SATU arah saja. Field ini
    # menyebut arah mana, supaya UI tidak menyesatkan (dulu selalu BUY, sehingga
    # gerbang pertama—Stochastic—tampak "selalu menahan" padahal sisi SELL-nya
    # lolos).
    probe_direction: str | None = None

    def to_dict(self) -> dict:
        return {
            "mode": self.mode, "timestamp": self.timestamp,
            "current_price": self.current_price, "direction": self.direction,
            "signal": self.signal, "quality": self.quality,
            "gates": [g.to_dict() for g in self.gates],
            "support": self.support_levels, "resistance": self.resistance_levels,
        }


def _p(key: str):
    return config.STRATEGY_PARAMS[key]


def _label(direction: str | None, quality: float) -> str:
    """Arah + kualitas → label yang dikenal executor & Flutter.

    Bentuk teks tak boleh berubah: executor membaca substring "KUAT" untuk
    `require_strong` (lihat fulens_client._map_signal).
    """
    if direction is None:
        return "NETRAL"
    strong = quality >= _p("STRONG_QUALITY")
    if direction == "BUY":
        return "BELI KUAT" if strong else "BELI"
    return "JUAL KUAT" if strong else "JUAL"


def _clamp01(x: float) -> float:
    if not np.isfinite(x):
        return 0.0
    return float(min(max(x, 0.0), 1.0))


# ─────────────────────────────────────────────────────────
#  GERBANG
# ─────────────────────────────────────────────────────────
def gate_stoch(ind: dict, idx: int, direction: str) -> GateResult:
    """Konfirmasi momentum: %K menyilang %D ke arah entry.

    HANYA arah cross yang wajib. Zona jenuh (20/80) sengaja TIDAK memblokir —
    ia cuma menaikkan skor. Alasannya terukur: pada 352 bar emas D1, %K di pivot
    sisi BUY min 31 / median 34, jadi syarat wajib "%K < 20" lolos NOL kali dan
    membuat strategi praktis SELL-only. Ambang absolut tak generalisasi lintas
    rezim — sama seperti pelajaran ambang squeeze dalam pips.
    """
    k = float(ind["stoch_k"].iloc[idx])
    d = float(ind["stoch_d"].iloc[idx])
    if not (np.isfinite(k) and np.isfinite(d)):
        return GateResult("Stochastic", False, 0.0, "data belum cukup")

    spread = (k - d) if direction == "BUY" else (d - k)
    passed = spread > 0
    if not passed:
        arah = "%K masih di bawah %D" if direction == "BUY" else "%K masih di atas %D"
        return GateResult("Stochastic", False, 0.0,
                          f"{arah} (%K {k:.1f}, %D {d:.1f})")

    # Skor: 60% kekuatan cross + 40% posisi zona (makin jenuh makin bagus).
    spread_score = _clamp01(spread / 10.0)          # spread 10 poin = penuh
    mid = _p("STOCH_ZONE_NEUTRAL")
    if direction == "BUY":
        zone_score = _clamp01((mid - k) / (mid - _p("STOCH_OVERSOLD")))
        zone_txt = "oversold" if k < _p("STOCH_OVERSOLD") else f"%K {k:.0f}"
    else:
        zone_score = _clamp01((k - mid) / (_p("STOCH_OVERBOUGHT") - mid))
        zone_txt = "overbought" if k > _p("STOCH_OVERBOUGHT") else f"%K {k:.0f}"

    score = 0.6 * spread_score + 0.4 * zone_score
    arah = ">" if direction == "BUY" else "<"
    return GateResult("Stochastic", True, score,
                      f"%K {k:.1f} {arah} %D {d:.1f} · {zone_txt}")


def gate_macd(ind: dict, idx: int, direction: str, need_cross: bool) -> GateResult:
    """MACD. Swing: WAJIB cross yang masih baru. Scalping: cukup searah.

    Cross adalah "pelatuk pengaman" swing — konfirmasi lain bisa bertahan lama
    sebelum harga benar-benar berbalik.
    """
    line = ind["macd_line"]
    sig = ind["macd_signal"]
    hist = ind["macd_hist"]
    l_now = float(line.iloc[idx])
    s_now = float(sig.iloc[idx])
    h_now = float(hist.iloc[idx])
    if not all(np.isfinite(v) for v in (l_now, s_now, h_now)):
        return GateResult("MACD", False, 0.0, "data belum cukup")

    aligned = (l_now > s_now and h_now > 0) if direction == "BUY" \
        else (l_now < s_now and h_now < 0)

    if not need_cross:
        atr = float(ind["atr"].iloc[idx])
        # Histogram sebesar ~10% ATR sudah momentum yang berarti.
        ref = 0.10 * atr if np.isfinite(atr) and atr > 0 else abs(h_now) or 1.0
        score = _clamp01(abs(h_now) / ref) if aligned else 0.0
        return GateResult("MACD", aligned, score,
                          f"{'searah' if aligned else 'melawan'}, hist {h_now:+.3f}")

    # Cari cross paling baru dalam MACD_CROSS_MAX_AGE bar terakhir.
    max_age = _p("MACD_CROSS_MAX_AGE")
    age = None
    for a in range(max_age):
        j = idx - a
        if j - 1 < 0:
            break
        prev_d = float(line.iloc[j - 1]) - float(sig.iloc[j - 1])
        cur_d = float(line.iloc[j]) - float(sig.iloc[j])
        if not (np.isfinite(prev_d) and np.isfinite(cur_d)):
            continue
        crossed = (prev_d <= 0 < cur_d) if direction == "BUY" \
            else (prev_d >= 0 > cur_d)
        if crossed:
            age = a
            break

    if age is None or not aligned:
        return GateResult("MACD Cross", False, 0.0,
                          f"belum ada {'golden' if direction == 'BUY' else 'dead'} "
                          f"cross dalam {max_age} bar")
    score = _clamp01(1 - age / max_age)      # makin baru makin bagus
    kind = "Golden" if direction == "BUY" else "Dead"
    return GateResult("MACD Cross", True, score, f"{kind} Cross {age} bar lalu")


def gate_trend(ind: dict, idx: int, direction: str) -> GateResult:
    """SWING: entry harus SEARAH tren besar (harga vs EMA200).

    Ini satu-satunya gerbang yang menjawab pertanyaan berbeda dari yang lain.
    Stochastic, MACD, BB, dan S&R semuanya turunan harga jangka pendek; EMA200
    memberi konteks "kita di sisi mana dari tren besar".

    Kenapa ini menggantikan MACD di rantai swing — terukur lewat uji ke depan
    (emas D1, SL/TP ditelusuri bar demi bar):
      Stoch+MACD cross+S&R+BB : win 22%, ekspektansi -0.39R  (rugi)
      Stoch+EMA200 +S&R+BB    : win 73%, ekspektansi +0.61R
    Sebabnya struktural: Stochastic dan MACD sama-sama osilator momentum dari
    deret harga yang sama, jadi menggandengkannya cuma konfirmasi BERULANG —
    dan hasilnya bot sering melawan tren (terukur 2.2:1 SELL di tren NAIK).

    Konsekuensi yang harus disadari: gerbang ini MEMBLOKIR reversal melawan tren.
    Swing jadi "beli koreksi searah tren", bukan "menangkap titik balik besar".
    """
    c = float(ind["close"].iloc[idx])
    e = float(ind["ema_trend"].iloc[idx])
    if not (np.isfinite(c) and np.isfinite(e)) or e <= 0:
        return GateResult("Tren (EMA200)", False, 0.0, "data belum cukup")

    passed = (c > e) if direction == "BUY" else (c < e)
    gap_pct = abs(c - e) / e * 100
    if not passed:
        sisi = "di bawah" if c < e else "di atas"
        return GateResult("Tren (EMA200)", False, 0.0,
                          f"harga {sisi} EMA200 {e:.2f} - melawan tren besar")

    # Skor: jarak dari EMA200. Terlalu mepet = tren belum tegas; terlalu jauh =
    # sudah terentang. ~2% dari EMA dianggap posisi ideal.
    score = _clamp01(gap_pct / 2.0)
    return GateResult("Tren (EMA200)", True, score,
                      f"harga {gap_pct:.1f}% di {'atas' if c > e else 'bawah'} "
                      f"EMA200 {e:.2f} - searah tren")


def gate_sr_touch(ind: dict, idx: int, direction: str,
                  support: list, resistance: list) -> GateResult:
    """SWING: harga menyentuh area Major S&R dalam SR_TOUCH_LOOKBACK bar terakhir.

    Ini JENDELA, bukan titik. Strateginya berurutan: sentuh dulu, LALU tunggu
    MACD cross. Menuntut keduanya di bar yang sama membuat BUY mustahil menyala —
    saat harga menyentuh support MACD masih turun; cross datang beberapa bar
    kemudian setelah harga memantul menjauh.

    BUY memakai low bar (titik terdalam sentuhan), SELL memakai high.
    """
    atr = float(ind["atr"].iloc[idx])
    if not np.isfinite(atr) or atr <= 0:
        return GateResult("Sentuh S&R", False, 0.0, "ATR belum siap")

    if direction == "BUY":
        probe_ser, levels, lbl = ind["low"], support, "support"
    else:
        probe_ser, levels, lbl = ind["high"], resistance, "resisten"

    if not levels:
        return GateResult("Sentuh S&R", False, 0.0, f"tak ada {lbl} terdeteksi")

    tol = _p("SR_TOUCH_ATR") * atr
    look = _p("SR_TOUCH_LOOKBACK")

    best = None
    for age in range(look):
        j = idx - age
        if j < 0:
            break
        probe = float(probe_ser.iloc[j])
        if not np.isfinite(probe):
            continue
        lvl = min(levels, key=lambda v: abs(v - probe))
        dist = abs(probe - lvl)
        if best is None or dist < best[0]:
            best = (dist, lvl, age)

    if best is None:
        return GateResult("Sentuh S&R", False, 0.0, "data belum cukup")

    dist, lvl, age = best
    passed = dist <= tol
    score = _clamp01(1 - dist / tol) if passed else 0.0
    when = "bar ini" if age == 0 else f"{age} bar lalu"
    return GateResult("Sentuh S&R", passed, score,
                      f"sentuh {lbl} {lvl:.2f} {when}, jarak {dist:.2f} "
                      f"(toleransi {tol:.2f})")


def gate_bb_squeeze(ind: dict, idx: int, direction: str) -> GateResult:
    """SCALPING: pita Bollinger sedang MENYEMPIT — volatilitas terkompresi.

    NETRAL ARAH — sengaja tidak melihat `direction` sama sekali. Ia menyaring
    KAPAN layak masuk, bukan KE MANA; arah sepenuhnya ditentukan Stochastic.
    Justru itu yang bikin scalping bisa seimbang BUY/SELL, sementara gerbang tren
    (EMA200) secara definisi mengunci satu sisi saja.

    Logikanya: pita menyempit = pasar menabung tenaga sebelum bergerak. Kita tidak
    menebak arah ledakannya, kita menunggu kompresinya lalu ikut Stochastic.

    Terukur (emas D1, SL/TP ditelusuri bar demi bar), di periode datar/turun:
      Stoch + BB squeeze : +0.42R  (BUY +0.38R, SELL +0.46R — imbang 0.92)
      Stoch + EMA200     : +0.27R  (SELL NOL trade — BUY-only)
      Stoch + BB melebar : +0.03R  (kebalikan squeeze, dan memang terburuk)
    Yang meyakinkan bukan satu angka tapi DATARANNYA: persentil p20..p70 semuanya
    positif di kedua rezim. Overfit akan terlihat sebagai satu puncak sempit.

    Yang harus disadari: SELL tetap rugi di pasar naik (-0.21R di sampel bullish).
    Itu perilaku pasar yang wajar, bukan cacat — total tetap positif karena BUY
    menutupinya. Jangan kaget melihat rentetan SELL merah saat tren naik kuat.

    `direction` tetap di tanda tangan agar seragam dengan gerbang lain.
    """
    w = float(ind["bb_width"].iloc[idx])
    ref = float(ind["bb_width_ref"].iloc[idx])
    if not (np.isfinite(w) and np.isfinite(ref)) or ref <= 0:
        return GateResult("BB Squeeze", False, 0.0, "data belum cukup")

    pctile = _p("BB_SQUEEZE_PCTILE")
    passed = w < ref
    if not passed:
        return GateResult("BB Squeeze", False, 0.0,
                          f"pita melebar (lebar {w:.2f}% > acuan {ref:.2f}%) - "
                          f"volatilitas sudah terlepas, bukan fase kompresi")

    # Skor: makin sempit relatif acuan makin bagus. w=0 → 1.0, w=ref → 0.0.
    score = _clamp01((ref - w) / ref)
    return GateResult("BB Squeeze", True, score,
                      f"pita menyempit (lebar {w:.2f}% < p{pctile} {ref:.2f}%) - "
                      f"volatilitas terkompresi")


# ─────────────────────────────────────────────────────────
#  MODE
# ─────────────────────────────────────────────────────────
def _evaluate_direction(ind: dict, idx: int, mode: str, direction: str,
                        support: list, resistance: list) -> list:
    """Rangkai gerbang untuk satu arah. Urutan = urutan cerita strateginya."""
    if mode == "scalping":
        # Scalping TIDAK mengikuti tren — ia cari profit harian dua arah. Karena
        # itu tak ada gerbang tren di sini: kompresi volatilitas menentukan KAPAN,
        # Stochastic menentukan KE MANA. MACD dibuang (searah/cross dua-duanya
        # rugi: -0.25R dan -0.31R) — ia dan Stochastic sama-sama osilator momentum
        # dari deret harga yang sama, jadi cuma konfirmasi berulang.
        return [
            gate_stoch(ind, idx, direction),
            gate_bb_squeeze(ind, idx, direction),
        ]
    # SWING: MACD cross DIGANTI gerbang tren EMA200 — lihat alasan terukur di
    # gate_trend(). Stochastic tetap sebagai konfirmasi momentum; membuangnya
    # justru memperburuk hasil di semua uji. S&R dipertahankan meski sebagai
    # gerbang ia nyaris netral (+0.62R vs +0.63R tanpanya) — ia memberi konteks
    # level yang dipakai untuk membaca SL/TP, dan menyaring entry jadi lebih
    # selektif (54 vs 120 trade) tanpa mengorbankan ekspektansi.
    return [
        gate_stoch(ind, idx, direction),
        gate_trend(ind, idx, direction),
        gate_sr_touch(ind, idx, direction, support, resistance),
    ]


def evaluate(ind: dict, support: list, resistance: list,
             mode: str = "swing", idx: int | None = None) -> SetupReport:
    """Nilai kedua arah pada bar tertutup; kembalikan setup yang lolos penuh.

    `ind` = dict of Series dari TechnicalAnalyzer._calc (+ close/high/low).
    `idx` default = bar tertutup terakhir (-2), bukan bar berjalan.
    """
    n = len(ind["close"])
    if idx is None:
        idx = n + BAR_CLOSED
    if idx < 0 or idx >= n:
        return SetupReport(mode=mode)

    rep = SetupReport(mode=mode)
    rep.current_price = float(ind["close"].iloc[idx])
    ts = ind["close"].index[idx]
    rep.timestamp = str(getattr(ts, "date", lambda: ts)())
    rep.support_levels = support
    rep.resistance_levels = resistance

    # BUY dan SELL saling eksklusif. Kalau dua-duanya lolos (mestinya mustahil),
    # pasar sedang tidak jelas → NETRAL.
    passing = {}
    all_gates = {}
    for direction in ("BUY", "SELL"):
        gates = _evaluate_direction(ind, idx, mode, direction, support, resistance)
        all_gates[direction] = gates
        required = [g for g in gates if not g.informational]
        if required and all(g.passed for g in required):
            passing[direction] = gates

    if len(passing) != 1:
        # Tak ada setup. Untuk diagnosa, tampilkan arah yang PALING DEKAT lolos —
        # bukan selalu BUY. Stochastic itu gerbang pertama dan saling melengkapi
        # antar-arah (%K>%D untuk BUY, %K<%D untuk SELL), jadi selalu menampilkan
        # BUY membuatnya tampak "selalu menahan" separuh waktu, sekaligus
        # menyembunyikan gerbang lain yang sebenarnya jadi penghambat.
        def _passed(gs):
            return sum(1 for g in gs if not g.informational and g.passed)

        probe = max(("BUY", "SELL"), key=lambda dr: _passed(all_gates[dr]))
        rep.gates = all_gates[probe]
        rep.probe_direction = probe
        rep.direction = None
        rep.signal = "NETRAL"
        rep.quality = 0.0
        return rep

    direction, gates = next(iter(passing.items()))
    req_scores = [g.score for g in gates if not g.informational]
    mean_score = float(np.mean(req_scores)) if req_scores else 0.0
    rep.direction = direction
    rep.gates = gates
    rep.quality = round(50 + 50 * mean_score, 1)
    rep.signal = _label(direction, rep.quality)
    return rep
