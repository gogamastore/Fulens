"""Mesin sinyal multi-simbol & multi-timeframe (konfluensi 4 komponen + ML veto).

Arah keputusan datang SEPENUHNYA dari gerbang konfluensi di `strategy.py`
(Bollinger Bands, S&R, Stochastic, MACD). Model ML per simbol (ml_symbol) TIDAK
lagi ikut menentukan arah — ia turun pangkat jadi VETO: bila probabilitasnya
melawan arah setup dengan cukup yakin, entry diblokir; bila cuma ragu-ragu,
confidence dipotong.

Kenapa berubah: dulu `final = 0.5 * ta_score + 0.5 * ml_score`, di mana ta_score
adalah rasio suara 16 indikator. Dua-duanya bermasalah. Rasio suara itu
anti-reversal (lihat strategy.py), dan mencampur skor kontinu dari dua sumber
membuat tak ada satu pun kondisi yang benar-benar wajib — persis yang bikin
sinyalnya terasa lembek. Sekarang gerbang yang memutuskan, ML yang menyaring.

Bentuk output tetap kompatibel dengan model Flutter & executor yang ada.
"""
import logging
from datetime import datetime

import pandas as pd

import config
import market_data
import ml_symbol
import symbols as sym
import timeframes as tfmod
from indicators import TechnicalAnalyzer, analyze_multi_timeframe

log = logging.getLogger("signal_engine")

# Mode per timeframe. M15/M30 = scalping (squeeze breakout), sisanya swing
# (divergence di Major S&R). Bisa dioverride lewat argumen `mode`.
_SCALP_TFS = {"M1", "M5", "M15", "M30"}


def _resolve_mode(tf: str, mode: str | None) -> str:
    """Mode efektif. None/"auto" → dipilih dari timeframe; selain itu dipakai apa
    adanya (tapi divalidasi — nilai asing jatuh ke auto, bukan meledak)."""
    m = (mode or "auto").strip().lower()
    if m in ("scalping", "swing"):
        return m
    return "scalping" if tfmod.normalize(tf) in _SCALP_TFS else "swing"


def _mode_for(tf: str) -> str:
    return _resolve_mode(tf, None)


def _analyzer(symbol: str, tf: str):
    df = market_data.get_ohlc(symbol, tf)
    if df is None or len(df) < 60:
        return None
    return TechnicalAnalyzer(df)


def price(symbol: str, tf: str = "D1") -> dict | None:
    return market_data.latest_price(symbol, tf)


def indicators(symbol: str, tf: str = "D1", mode: str | None = None) -> dict | None:
    an = _analyzer(symbol, tf)
    if not an:
        return None
    mode = _resolve_mode(tf, mode)
    report = an.get_signals(mode=mode)
    # `current_price` = harga BAR YANG DIANALISIS (bar tertutup terakhir) — itulah
    # dasar semua gerbang, jadi ia harus dipakai saat membandingkan dengan S&R.
    # `live_price` = baris terakhir data (bar berjalan) — ini yang mendekati harga
    # di terminal MT5. Keduanya dikirim supaya UI tak lagi menyebut harga bar
    # tertutup sebagai "harga saat ini" (sumber kebingungan harga tak cocok).
    live = float(an.close.iloc[-1]) if len(an.close) else report.current_price
    return {
        "symbol": sym.normalize(symbol),
        "timeframe": tfmod.normalize(tf),
        "timestamp": report.timestamp,
        "current_price": report.current_price,
        "live_price": round(live, 5),
        "overall_signal": report.overall_signal,
        "confidence": round(report.confidence * 100, 1),
        "mode": report.mode,
        "direction": report.direction,
        # Arah yang sedang didiagnosa saat belum ada setup (paling dekat lolos).
        "probe_direction": report.probe_direction,
        # Inti laporan sekarang: checklist gerbang, bukan hitungan suara.
        "gates": report.gates,
        # Ringkasan lama (buy/sell/neutral) sengaja tidak dikirim lagi — dengan
        # gerbang AND angka itu tak bermakna. Kotak "Ringkasan Sinyal" di
        # technical_screen.dart perlu diganti jadi checklist gerbang.
        "signals": [
            {"name": s.name, "value": round(s.value, 5) if s.value else 0,
             "signal": s.signal, "category": s.category, "detail": s.detail}
            for s in report.signals
        ],
        "support_levels": report.support_levels,
        "resistance_levels": report.resistance_levels,
    }


def _ml_veto(direction: str, ml_prob: float) -> tuple[bool, float, str]:
    """ML sebagai penyaring, bukan penentu arah.

    `ml_prob` = probabilitas naik (0..1). Kembalikan (lolos, faktor, alasan).
    Faktor mengalikan quality — setup yang ML-nya ragu tetap boleh jalan tapi
    confidence-nya turun, sehingga `min_confidence` di executor otomatis jadi
    saringan kedua tanpa aturan tambahan.
    """
    p = config.ML_VETO
    agree = ml_prob if direction == "BUY" else 1.0 - ml_prob

    if agree < p["BLOCK_BELOW"]:
        return False, 0.0, (f"ML menolak: probabilitas searah {agree * 100:.0f}% "
                            f"< {p['BLOCK_BELOW'] * 100:.0f}%")
    if agree < p["FULL_ABOVE"]:
        # Interpolasi linear antara faktor minimum dan 1.0.
        span = p["FULL_ABOVE"] - p["BLOCK_BELOW"]
        t = (agree - p["BLOCK_BELOW"]) / span if span > 0 else 1.0
        factor = p["MIN_FACTOR"] + (1.0 - p["MIN_FACTOR"]) * t
        return True, factor, f"ML ragu ({agree * 100:.0f}% searah) — kualitas dipotong"
    return True, 1.0, f"ML setuju ({agree * 100:.0f}% searah)"


def signal(symbol: str, tf: str = "D1", mode: str | None = None) -> dict | None:
    """Sinyal ringkas untuk /signal — dipakai executor & app."""
    an = _analyzer(symbol, tf)
    if not an:
        return None

    mode = _resolve_mode(tf, mode)
    report = an.get_signals(mode=mode)

    direction = report.direction
    quality = report.confidence * 100          # 0..100
    reasons = [f"{g['name']}: {g['detail']}" for g in report.gates if g["passed"]]
    source = "technical"
    ml_prob = None

    if direction is not None:
        ml_prob = (ml_symbol.predict_latest(symbol, tf)
                   if ml_symbol.has_model(symbol, tf) else None)
        if ml_prob is not None:
            source = "ml-veto+technical"
            ok, factor, why = _ml_veto(direction, ml_prob)
            reasons.append(why)
            if not ok:
                direction, quality = None, 0.0
            else:
                quality = round(quality * factor, 1)
    else:
        # Tak ada setup: jelaskan gerbang mana yang menahannya.
        reasons = [f"{g['name']}: {g['detail']}"
                   for g in report.gates if not g["passed"]] or ["belum ada setup"]

    # Label harus dihitung ulang: faktor ML bisa menurunkan quality melewati
    # ambang KUAT, dan executor membaca substring "KUAT" untuk require_strong.
    import strategy
    label = strategy._label(direction, quality)

    # Mekanika risiko: jarak SL/TP dari ATR (harga). EA memakainya untuk lot &
    # penempatan order. Arah & jarak = otak; ukuran lot (butuh equity) = EA.
    atr = report.atr
    sl_distance = round(atr * config.RISK_PARAMS["SL_ATR_MULT"], 5) if atr else None
    tp_distance = round(atr * config.RISK_PARAMS["TP_ATR_MULT"], 5) if atr else None

    return {
        "symbol": sym.normalize(symbol),
        "timeframe": tfmod.normalize(tf),
        "timestamp": datetime.now().isoformat(),
        "current_price": report.current_price,
        "signal": label,
        "confidence": round(quality, 1),
        "mode": mode,
        "direction": direction,
        # Arah yang gerbangnya sedang ditampilkan saat belum ada setup — supaya
        # log keputusan di Flutter tidak disalahartikan (checklist itu diagnosa
        # satu arah, bukan bukti indikatornya rusak).
        "probe_direction": report.probe_direction,
        "gates": report.gates,
        "reasons": reasons,
        "atr": round(atr, 5) if atr else None,
        "sl_distance": sl_distance,
        "tp_distance": tp_distance,
        "ml_probability": round(ml_prob * 100, 1) if ml_prob is not None else None,
        "prediction_1d": None,
        "prediction_7d": None,
        "support": report.support_levels[:2],
        "resistance": report.resistance_levels[:2],
        "source": source,
    }


def multitimeframe(symbol: str, tf: str = "D1") -> dict | None:
    df = market_data.get_ohlc(symbol, tf)
    if df is None or len(df) < 60:
        return None
    results = analyze_multi_timeframe(df, mode=_mode_for(tf))
    buy_tfs = sum(1 for r in results if "BELI" in r["signal"])
    sell_tfs = sum(1 for r in results if "JUAL" in r["signal"])
    return {
        "symbol": sym.normalize(symbol),
        "timestamp": datetime.now().isoformat(),
        "timeframes": results,
        "consensus": {
            "bullish": buy_tfs, "bearish": sell_tfs,
            "neutral": len(results) - buy_tfs - sell_tfs,
            "bias": ("BULLISH" if buy_tfs > sell_tfs else
                     "BEARISH" if sell_tfs > buy_tfs else "MIXED"),
        },
    }


def history(symbol: str, days: int = 90, tf: str = "D1") -> dict | None:
    df = market_data.get_ohlc(symbol, tf)
    if df is None:
        return None
    days = min(days, 2000)
    sl = df.tail(days)
    data = [{
        "date": str(idx),
        "open": round(float(r["gold_open"]), 5),
        "high": round(float(r["gold_high"]), 5),
        "low": round(float(r["gold_low"]), 5),
        "close": round(float(r["gold_close"]), 5),
        "volume": int(r["gold_volume"]) if pd.notna(r["gold_volume"]) else 0,
    } for idx, r in sl.iterrows()]
    return {"symbol": sym.normalize(symbol), "timeframe": tfmod.normalize(tf),
            "days": days, "count": len(data), "data": data}
