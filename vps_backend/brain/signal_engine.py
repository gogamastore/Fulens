"""Mesin sinyal multi-simbol & multi-timeframe (TA + ML per simbol).

Menyediakan sinyal / indikator / harga / history untuk SEMUA simbol dengan
TechnicalAnalyzer & analyze_multi_timeframe. Bila tersedia model ML per simbol
(ml_symbol), arah & confidence di-blend dengan probabilitas ML.

Bentuk output tetap kompatibel dengan model Flutter yang ada.
"""
import logging
from datetime import datetime

import pandas as pd

import market_data
import ml_symbol
import symbols as sym
import timeframes as tfmod
from indicators import TechnicalAnalyzer, analyze_multi_timeframe

log = logging.getLogger("signal_engine")


def _analyzer(symbol: str, tf: str):
    df = market_data.get_ohlc(symbol, tf)
    if df is None or len(df) < 60:
        return None
    return TechnicalAnalyzer(df)


def price(symbol: str, tf: str = "D1") -> dict | None:
    return market_data.latest_price(symbol, tf)


def indicators(symbol: str, tf: str = "D1") -> dict | None:
    an = _analyzer(symbol, tf)
    if not an:
        return None
    report = an.get_signals()
    return {
        "symbol": sym.normalize(symbol),
        "timeframe": tfmod.normalize(tf),
        "timestamp": report.timestamp,
        "current_price": report.current_price,
        "overall_signal": report.overall_signal,
        "confidence": round(report.confidence * 100, 1),
        "summary": {"buy": report.buy_count, "sell": report.sell_count,
                    "neutral": report.neutral_count},
        "signals": [
            {"name": s.name, "value": round(s.value, 5) if s.value else 0,
             "signal": s.signal, "category": s.category, "detail": s.detail}
            for s in report.signals
        ],
        "support_levels": report.support_levels,
        "resistance_levels": report.resistance_levels,
    }


def _label(score: float) -> str:
    """score in [-1,1] → label sinyal."""
    if score > 0.6:
        return "BELI KUAT"
    if score > 0.15:
        return "BELI"
    if score < -0.6:
        return "JUAL KUAT"
    if score < -0.15:
        return "JUAL"
    return "NETRAL"


def signal(symbol: str, tf: str = "D1") -> dict | None:
    """Sinyal ringkas (TA + ML blend) untuk /signal — dipakai executor & app."""
    an = _analyzer(symbol, tf)
    if not an:
        return None
    report = an.get_signals()

    denom = max(report.buy_count + report.sell_count, 1)
    ta_score = (report.buy_count - report.sell_count) / denom

    ml_prob = ml_symbol.predict_latest(symbol, tf) if ml_symbol.has_model(symbol, tf) else None
    if ml_prob is not None:
        ml_score = (ml_prob - 0.5) * 2          # [-1,1]
        final = 0.5 * ta_score + 0.5 * ml_score
        source = "ml+technical"
    else:
        final = ta_score
        source = "technical"

    conf = round(min(abs(final), 1.0) * 100, 1)
    return {
        "symbol": sym.normalize(symbol),
        "timeframe": tfmod.normalize(tf),
        "timestamp": datetime.now().isoformat(),
        "current_price": report.current_price,
        "signal": _label(final),
        "confidence": conf,
        "indicator_summary": {"buy": report.buy_count, "sell": report.sell_count,
                              "neutral": report.neutral_count},
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
    results = analyze_multi_timeframe(df)
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
