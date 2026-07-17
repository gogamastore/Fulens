"""Gerbang entry mode SCALPING M15 — adaptif-rezim.

PERAN: FILTER/VETO, bukan pembuat arah. Otak FuLens tetap satu-satunya penentu
BUY/SELL/NETRAL. Modul ini hanya menjawab satu pertanyaan:
"apakah LOKASI harga & kondisi pasar layak untuk entry itu SEKARANG?"
Bila tidak, entry dibatalkan beserta alasan yang bisa dibaca pengguna.

KENAPA ADAPTIF-REZIM. Dua naluri yang sama-sama benar bisa bertabrakan:
  • "beli di support, jual di resisten" (mean-reversion) — bagus di pasar ranging,
    tapi mematikan di tren kuat: resisten saat uptrend lebih sering JEBOL daripada
    memantul, jadi sell di resisten = melawan tren.
  • "ikut tren" — bagus di tren, tapi tersayat-sayat di pasar sideways.
Kaufman Efficiency Ratio (|gerak bersih| / total lintasan; ~0 choppy, ~1 trending
mulus) dipakai memilih gaya mana yang sedang cocok, alih-alih menebak.

Fungsi murni: tak menyentuh MT5/jaringan, semua input berupa angka — supaya
keputusannya bisa diuji langsung.
"""
from dataclasses import dataclass

from config import BotSettings


@dataclass
class ScalpVerdict:
    ok: bool
    regime: str   # "trending" | "ranging"
    reason: str   # alasan terima/tolak, ikut tercatat di log sinyal


def _nearest_above(levels: list[float], price: float) -> float | None:
    above = [x for x in levels if x > price]
    return min(above) if above else None


def _nearest_below(levels: list[float], price: float) -> float | None:
    below = [x for x in levels if x < price]
    return max(below) if below else None


def evaluate(direction: str, price: float, atr: float, er: float,
             ema50: float, ema200: float, volume: float, vol_ma: float,
             support: list[float], resistance: list[float],
             s: BotSettings) -> ScalpVerdict:
    """True = boleh entry. `direction` "BUY"/"SELL" datang dari otak FuLens."""
    regime = "trending" if er >= s.scalp_er_trend else "ranging"

    if atr <= 0:
        return ScalpVerdict(False, regime, "ATR tidak valid")

    # 1) PARTISIPASI — gerakan bervolume tipis gampang palsu/mudah dibalik.
    if vol_ma > 0 and volume < s.scalp_vol_mult * vol_ma:
        return ScalpVerdict(False, regime,
                            f"volume tipis ({volume:.0f} < {s.scalp_vol_mult:.2f}"
                            f"× rata2 {vol_ma:.0f})")

    # 2) RUANG KE TARGET — inti anti-danger-zone. Kalau TP tak punya ruang sebelum
    #    menabrak level lawan, entry itu taruhan buruk SEKUAT apa pun sinyalnya.
    #    Inilah terjemahan objektif dari "jangan buy tepat di bawah resisten".
    need = s.scalp_min_room_mult * s.tp_atr_mult * atr
    if direction == "BUY":
        lvl = _nearest_above(resistance, price)
        if lvl is not None and (lvl - price) < need:
            return ScalpVerdict(False, regime,
                                f"ruang ke resisten {lvl:.2f} cuma {lvl - price:.2f}"
                                f" (butuh {need:.2f}) — zona rawan")
    else:
        lvl = _nearest_below(support, price)
        if lvl is not None and (price - lvl) < need:
            return ScalpVerdict(False, regime,
                                f"ruang ke support {lvl:.2f} cuma {price - lvl:.2f}"
                                f" (butuh {need:.2f}) — zona rawan")

    # 3) GAYA MENGIKUTI REZIM.
    if regime == "trending":
        up = ema50 > ema200
        if up and direction == "SELL":
            return ScalpVerdict(False, regime, f"melawan tren naik (ER {er:.2f})")
        if not up and direction == "BUY":
            return ScalpVerdict(False, regime, f"melawan tren turun (ER {er:.2f})")
        # Anti-mengejar: harga yang sudah terentang jauh dari EMA50 justru zona
        # rawan koreksi — persis skenario "buy di resisten saat uptrend volatil".
        # Tunggu harga merapat dulu (pullback).
        ext = (price - ema50) if direction == "BUY" else (ema50 - price)
        if ext > s.scalp_ext_atr * atr:
            return ScalpVerdict(False, regime,
                                f"harga {ext / atr:.1f}×ATR dari EMA50 — mengejar,"
                                f" tunggu pullback")
        return ScalpVerdict(True, regime,
                            f"searah tren (ER {er:.2f}), jarak EMA50"
                            f" {ext / atr:.1f}×ATR, ruang cukup")

    # RANGING — mean-reversion: hanya masuk saat menempel level pendukungnya.
    if direction == "BUY":
        lvl = _nearest_below(support, price)
        if lvl is None or (price - lvl) > s.scalp_near_atr * atr:
            return ScalpVerdict(False, regime, "belum menempel support")
        gap = price - lvl
    else:
        lvl = _nearest_above(resistance, price)
        if lvl is None or (lvl - price) > s.scalp_near_atr * atr:
            return ScalpVerdict(False, regime, "belum menempel resisten")
        gap = lvl - price
    return ScalpVerdict(True, regime,
                        f"mean-reversion (ER {er:.2f}) di {gap / atr:.1f}×ATR"
                        f" dari level {lvl:.2f}")
