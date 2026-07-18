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
    # Level struktur dari otak (dihitung pada timeframe sinyal).
    support: list[float] = field(default_factory=list)
    resistance: list[float] = field(default_factory=list)
    # Mekanika risiko dari otak (harga). EA memakainya: SL/TP = entry ∓ jarak,
    # dan lot dari equity ÷ sl_distance. None bila ATR belum siap.
    atr: float | None = None
    sl_distance: float | None = None
    tp_distance: float | None = None
    mode: str = "swing"

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol, "direction": self.direction,
            "confidence": self.confidence, "strong": self.strong,
            "raw_signal": self.raw_signal, "price": self.price,
            "reasons": self.reasons, "source": "fulens",
            "support": self.support, "resistance": self.resistance,
            "atr": self.atr, "sl_distance": self.sl_distance,
            "tp_distance": self.tp_distance, "mode": self.mode,
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


def fetch_signal(symbol: str, timeframe: str = "D1",
                 mode: str = "auto") -> SignalDecision | None:
    """Ambil sinyal FuLens untuk `symbol` pada `timeframe` → keputusan arah.

    `mode` ("auto"/"scalping"/"swing") diteruskan ke otak; "auto" berarti otak
    memilih dari timeframe. FuLens (symbols.normalize) mengenali nama broker
    standar + suffix umum. Bila simbol tak dikenali otak, endpoint balas 4xx →
    fungsi ini return None.
    """
    fulens_symbol = FulensConfig.SYMBOL_MAP.get(symbol, symbol)  # override opsional
    try:
        with httpx.Client(base_url=FulensConfig.BASE_URL,
                          timeout=FulensConfig.TIMEOUT, headers=_headers()) as c:
            r = c.get("/api/v1/signal",
                      params={"symbol": fulens_symbol, "timeframe": timeframe,
                              "mode": mode})
            r.raise_for_status()
            data = r.json()
    except Exception as e:
        log.warning("Gagal ambil sinyal FuLens (%s) → %s",
                    symbol, f"{type(e).__name__}: {e}".rstrip(": "))
        return None

    direction, strong = _map_signal(data.get("signal", "NETRAL"))
    # Otak kini mengirim `reasons` per-gerbang (checklist konfluensi). Pakai itu;
    # fallback ke ringkasan lama bila kosong. (Ringkasan "indikator beli/jual/netral"
    # dibuang — otak tak lagi memungut suara.)
    reasons = list(data.get("reasons") or [])
    if not reasons:
        reasons = [f"FuLens: {data.get('signal', 'NETRAL')} "
                   f"(confidence {data.get('confidence', 0)}%)"]
    p1, p7 = data.get("prediction_1d"), data.get("prediction_7d")
    if p1 is not None:
        reasons.append(f"Prediksi 1 hari: {p1:+.2f}%")
    if p7 is not None:
        reasons.append(f"Prediksi 7 hari: {p7:+.2f}%")

    def _levels(key: str) -> list[float]:
        try:
            return [float(x) for x in (data.get(key) or [])]
        except (TypeError, ValueError):
            return []

    def _num(key: str) -> float | None:
        v = data.get(key)
        return float(v) if v is not None else None

    return SignalDecision(
        symbol=symbol, direction=direction,
        confidence=float(data.get("confidence", 0) or 0), strong=strong,
        raw_signal=data.get("signal", "NETRAL"),
        price=float(data.get("current_price", 0) or 0), reasons=reasons,
        support=_levels("support"), resistance=_levels("resistance"),
        atr=_num("atr"), sl_distance=_num("sl_distance"),
        tp_distance=_num("tp_distance"), mode=data.get("mode", "swing"),
    )


async def push_ohlc(symbol: str, timeframe: str, bars: list[dict]) -> tuple[int, object]:
    """Teruskan OHLC dorongan EA ke otak (POST /api/v1/ohlc). Dipakai /ea/sync."""
    payload = {"symbol": symbol, "timeframe": timeframe, "bars": bars}
    try:
        async with httpx.AsyncClient(base_url=FulensConfig.BASE_URL,
                                     timeout=FulensConfig.TIMEOUT,
                                     headers=_headers()) as c:
            r = await c.post("/api/v1/ohlc", json=payload)
            ct = r.headers.get("content-type", "")
            body = r.json() if "application/json" in ct else {"raw": r.text}
            return r.status_code, body
    except Exception as e:
        detail = f"{type(e).__name__}: {e}".rstrip(": ")
        log.warning("Push OHLC ke FuLens gagal → %s", detail)
        return 502, {"detail": f"FuLens tidak dapat dihubungi ({detail})"}


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
        # Sertakan NAMA KELAS exception: httpx.ReadTimeout & kawan-kawan sering
        # ber-str() kosong, sehingga log lama hanya berbunyi "gagal /api/v1/signal:"
        # tanpa petunjuk apakah ini timeout, connect error, atau brain mati.
        detail = f"{type(e).__name__}: {e}".rstrip(": ")
        log.warning("Proxy FuLens gagal %s → %s", path, detail)
        return 502, {"detail": f"FuLens tidak dapat dihubungi ({detail})"}
