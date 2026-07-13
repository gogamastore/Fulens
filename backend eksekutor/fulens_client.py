"""Klien ke otak FuLens (backend ML prediksi emas).

Eksekutor memanggil FuLens untuk memperoleh KEPUTUSAN arah trading.
Dua peran:
  1. fetch_signal()  → dipakai bot_engine untuk memutuskan BUY/SELL/flat.
  2. proxy_get()     → dipakai main.py agar Flutter mengakses endpoint analisis
                       FuLens (chart/prediksi/fundamental) lewat gerbang :8000.
"""
import logging
from dataclasses import dataclass, field

import httpx

from config import FulensConfig

log = logging.getLogger("fulens")


@dataclass
class SignalDecision:
    """Keputusan yang sudah dinormalisasi dari sinyal FuLens."""
    symbol: str
    direction: str | None          # "BUY" / "SELL" / None (NETRAL)
    confidence: float              # 0-100
    strong: bool                   # sinyal "KUAT"
    raw_signal: str                # teks asli FuLens (mis. "BELI KUAT")
    price: float = 0.0
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol, "direction": self.direction,
            "confidence": self.confidence, "strong": self.strong,
            "raw_signal": self.raw_signal, "price": self.price,
            "reasons": self.reasons, "source": "fulens",
        }


def _map_signal(text: str) -> tuple[str | None, bool]:
    """FuLens 'BELI/JUAL/NETRAL' → ('BUY'/'SELL'/None, strong?)."""
    t = (text or "").upper()
    strong = "KUAT" in t
    if "BELI" in t:
        return "BUY", strong
    if "JUAL" in t:
        return "SELL", strong
    return None, False


def _headers() -> dict:
    return {"X-API-Key": FulensConfig.API_KEY} if FulensConfig.API_KEY else {}


def fetch_signal(symbol: str) -> SignalDecision | None:
    """Ambil sinyal ringkas FuLens dan ubah ke keputusan arah.

    FuLens saat ini hanya menghasilkan sinyal EMAS (harian). `symbol` dipakai
    untuk penanda & pemetaan; simbol non-emas mengembalikan None (tidak dikenali otak).
    """
    asset = FulensConfig.SYMBOL_MAP.get(symbol)
    if asset != "GOLD":
        log.debug("Simbol %s di luar cakupan FuLens (emas) — dilewati", symbol)
        return None

    try:
        with httpx.Client(base_url=FulensConfig.BASE_URL,
                          timeout=FulensConfig.TIMEOUT, headers=_headers()) as c:
            r = c.get("/api/v1/signal")
            r.raise_for_status()
            data = r.json()
    except Exception as e:
        log.warning("Gagal ambil sinyal FuLens (%s): %s", symbol, e)
        return None

    direction, strong = _map_signal(data.get("signal", "NETRAL"))
    reasons = [f"FuLens: {data.get('signal', 'NETRAL')} "
               f"(confidence {data.get('confidence', 0)}%)"]
    p1, p7 = data.get("prediction_1d"), data.get("prediction_7d")
    if p1 is not None:
        reasons.append(f"Prediksi 1 hari: {p1:+.2f}%")
    if p7 is not None:
        reasons.append(f"Prediksi 7 hari: {p7:+.2f}%")
    summ = data.get("indicator_summary") or {}
    if summ:
        reasons.append(f"Indikator FuLens — beli {summ.get('buy', 0)} / "
                       f"jual {summ.get('sell', 0)} / netral {summ.get('neutral', 0)}")

    return SignalDecision(
        symbol=symbol, direction=direction,
        confidence=float(data.get("confidence", 0) or 0), strong=strong,
        raw_signal=data.get("signal", "NETRAL"),
        price=float(data.get("current_price", 0) or 0), reasons=reasons,
    )


async def proxy_get(path: str, params: dict | None = None) -> tuple[int, object]:
    """Teruskan GET ke FuLens (dipakai gateway untuk endpoint analisis)."""
    try:
        async with httpx.AsyncClient(base_url=FulensConfig.BASE_URL,
                                     timeout=FulensConfig.TIMEOUT,
                                     headers=_headers()) as c:
            r = await c.get(path, params=params)
            ct = r.headers.get("content-type", "")
            body = r.json() if "application/json" in ct else {"raw": r.text}
            return r.status_code, body
    except Exception as e:
        log.warning("Proxy FuLens gagal %s: %s", path, e)
        return 502, {"detail": f"FuLens tidak dapat dihubungi: {e}"}
