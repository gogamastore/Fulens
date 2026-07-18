"""Gerbang tunggal untuk Flutter DAN EA MQL5 (REST + WebSocket).

Model baru: EA (MQL5) = tangan + mata. Gerbang TIDAK lagi memakai library
MetaTrader5 Python — EA yang membaca chart & mengeksekusi, lalu melapor balik.
Gerbang cuma: terima laporan EA (simpan state), beri EA rencana aksi (sinyal otak
+ ambang keputusan), teruskan analisis ke otak, dan sajikan semuanya ke Flutter.

Jalan di VPS (tak harus Windows lagi — tak ada dependensi MT5):
    uvicorn main:app --host 0.0.0.0 --port 8000

Kelompok endpoint:
  • EA       (/ea/sync)                → dipakai Expert Advisor tiap penutupan bar.
  • Trading  (/status /bot/* /positions /history /signals /settings /ws)
             → dibaca dari state laporan EA (bukan lagi query MT5).
  • Analisis (/api/v1/*)               → di-proxy ke otak FuLens (localhost:8500).

Catatan: bot_engine/mt5_connector/risk_manager/strategy/scalp.py TIDAK diimpor
lagi (peran eksekusi pindah ke EA). File-nya sengaja dibiarkan di repo sampai EA
terbukti di demo, baru dihapus (milestone cleanup terakhir).
"""
import asyncio
import logging
from datetime import datetime, timedelta

from fastapi import Depends, FastAPI, Header, HTTPException, Request, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

import fulens_client
from config import BotSettings, ServerConfig, save_settings, settings
from ea_state import EaState

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(name)s %(levelname)s %(message)s")
logging.getLogger("asyncio").setLevel(logging.ERROR)
log = logging.getLogger("gateway")

state = EaState()
# Setelan aktif (diubah lewat PUT /settings; bertahan restart lewat save_settings).
SET: BotSettings = settings

app = FastAPI(title="FuLens Gateway (EA-driven)")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                   allow_headers=["*"])  # untuk build web Flutter


def check_key(x_api_key: str = Header(default="")):
    if x_api_key != ServerConfig.API_KEY:
        raise HTTPException(status_code=401, detail="API key salah")


def _norm(sym: str) -> str:
    return (sym or "").strip().upper()


# ─────────────────────────────────────────────────────────
#  ENDPOINT EA (dipakai Expert Advisor)
# ─────────────────────────────────────────────────────────
class SyncBar(BaseModel):
    time: float | str          # epoch detik atau ISO string
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


class FeedItem(BaseModel):
    """Satu timeframe berikut bar-nya (EA mendorong beberapa sekaligus)."""
    timeframe: str
    bars: list[SyncBar] = []


class EaSync(BaseModel):
    symbol: str
    # BARU: EA mendorong banyak timeframe agar SEMUA layar analisis memakai harga
    # broker asli. Yang dieksekusi tetap satu — `exec_timeframe` dari setelan.
    feeds: list[FeedItem] = []
    # Bentuk lama (satu timeframe) — dipertahankan agar EA versi lama tetap jalan.
    timeframe: str = ""
    bars: list[SyncBar] = []
    account: dict = {}
    positions: list[dict] = []
    fills: list[dict] = []

    def all_feeds(self) -> list[FeedItem]:
        """Gabungkan bentuk baru & lama jadi satu daftar feed."""
        out = list(self.feeds)
        if self.bars and self.timeframe:
            out.append(FeedItem(timeframe=self.timeframe, bars=self.bars))
        return out


def _build_plan(dec: fulens_client.SignalDecision | None, sym: str) -> dict:
    """Rencana aksi untuk EA: target arah + apakah boleh entry + mekanika risiko.

    Ambang KEPUTUSAN (min_confidence, require_strong, mode fokus) diterapkan DI
    SINI — EA tinggal mengeksekusi. Arah & jarak SL/TP dari otak; lot dihitung EA
    dari equity live.
    """
    s = SET
    # Tidak ada lagi filter simbol di sini: mode berlaku untuk SEMUA simbol, dan
    # simbol mana yang ditradingkan ditentukan chart tempat EA dipasang.
    actionable = bool(
        dec and dec.direction
        and dec.confidence >= s.min_confidence
        and (not s.require_strong or dec.strong)
    )

    return {
        "symbol": _norm(sym),
        "target": dec.direction if dec else None,      # "BUY"/"SELL"/None
        "actionable": actionable,
        "signal": dec.raw_signal if dec else "NETRAL",
        "confidence": dec.confidence if dec else 0.0,
        "reasons": dec.reasons if dec else [],
        # mekanika risiko (dari otak) — EA pakai untuk SL/TP & ukuran lot:
        "atr": dec.atr if dec else None,
        "sl_distance": dec.sl_distance if dec else None,
        "tp_distance": dec.tp_distance if dec else None,
        # kebijakan yang diterapkan EA:
        "running": state.running,
        "close_on_neutral": s.close_on_neutral,
        "close_on_flip": s.close_on_flip,
        "risk_percent": s.risk_percent,
        "trail_enabled": s.trailing_enabled,
        "trail_start_atr": s.trail_start_atr,
        "trail_dist_atr": s.trail_dist_atr,
        "max_positions": s.max_positions_per_symbol,
        "magic_number": s.magic_number,
        "max_daily_drawdown_pct": s.max_daily_drawdown_pct,
    }


@app.post("/ea/sync", dependencies=[Depends(check_key)])
async def ea_sync(payload: EaSync):
    """Satu siklus EA: dorong OHLC + lapor state, terima rencana + perintah.

    1. Teruskan OHLC ke otak (jadikan harga broker asli sumber gerbang otak).
    2. Simpan akun/posisi/fill sebagai state (dibaca layar Flutter).
    3. Ambil sinyal otak, susun rencana aksi.
    4. Balas rencana + perintah manual tertunda (close/stop dari Flutter).
    """
    # 1) Teruskan SEMUA feed ke otak — inilah yang membuat setiap timeframe di
    #    layar analisis memakai harga broker asli, bukan fallback yfinance.
    #    PARALEL, bukan berurutan: kalau otak lambat, waktu tunggunya menumpuk
    #    (n × timeout) dan gerbang ikut terlihat mati dari Flutter.
    pushes = [
        fulens_client.push_ohlc(payload.symbol, f.timeframe,
                                [b.model_dump() for b in f.bars])
        for f in payload.all_feeds() if f.bars
    ]
    if pushes:
        await asyncio.gather(*pushes, return_exceptions=True)

    # 2) Simpan state. TF yang dilaporkan = TF EKSEKUSI (dari setelan Flutter),
    #    bukan TF mana pun yang kebetulan didorong EA.
    exec_tf = SET.exec_timeframe
    state.last_tf = exec_tf
    state.last_symbol = payload.symbol
    state.apply_sync(payload.symbol, payload.account,
                     payload.positions, payload.fills)

    # 3) Rencana dihitung HANYA untuk timeframe eksekusi.
    #    fetch_signal memakai httpx sinkron → jalankan di thread agar tak memblokir loop.
    dec = await asyncio.to_thread(
        fulens_client.fetch_signal, payload.symbol, exec_tf, SET.trading_mode)

    plan = _build_plan(dec, payload.symbol)
    plan["exec_timeframe"] = exec_tf
    state.record_signal({
        "symbol": plan["symbol"], "raw_signal": plan["signal"],
        "direction": plan["target"], "confidence": plan["confidence"],
        "atr": plan["atr"] or 0.0, "reasons": plan["reasons"],
        "executed": False, "executed_entries": 0,
        "planned_entries": 1 if plan["actionable"] else 0,
    })

    # Respons FLAT (bukan nested) — MQL5 tak punya JSON native, jadi struktur
    # datar jauh lebih mudah diparse EA. Perintah manual diratakan jadi daftar
    # tiket yang harus ditutup. (Perintah "stop" tidak perlu: /bot/stop mengubah
    # `running`, dan EA berhenti membuka posisi saat running=false.)
    cmds = state.take_commands()
    close_tickets = [c["ticket"] for c in cmds
                     if c.get("type") == "close" and "ticket" in c]
    return {**plan, "close_tickets": close_tickets}


# ─────────────────────────────────────────────────────────
#  INFO / HEALTH (tanpa key)
# ─────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    code, _ = await fulens_client.proxy_get("/health")
    return {
        "status": "ok",
        "gateway": True,
        # "mt5_connected" dipertahankan namanya (kontrak Flutter) tapi kini berarti
        # "EA masih melapor". Flutter menampilkannya sebagai status koneksi.
        "mt5_connected": state.ea_connected(),
        "bot_running": state.running,
        "fulens_reachable": code == 200,
        "timestamp": datetime.now().isoformat(),
    }


# ─────────────────────────────────────────────────────────
#  TRADING (butuh key) — dibaca dari state laporan EA
# ─────────────────────────────────────────────────────────
@app.get("/status", dependencies=[Depends(check_key)])
def status():
    return {
        "running": state.running,
        "mt5_connected": state.ea_connected(),
        "account": state.account,
        "symbols": SET.symbols,
        # Apa yang BENAR-BENAR ditradingkan bot — ditentukan EA (chart + SignalTF),
        # bukan selektor timeframe di aplikasi. Flutter menampilkannya agar tak
        # ada lagi kesan "bot mengikuti timeframe yang saya pilih di app".
        "ea_symbol": state.last_symbol,
        "ea_timeframe": state.last_tf,
        "trading_mode": SET.trading_mode,
    }


@app.post("/bot/start", dependencies=[Depends(check_key)])
def bot_start():
    """Aktifkan bot. EA membaca `running` dari rencana; saat False ia berhenti
    membuka posisi baru (posisi terbuka tetap dikelola)."""
    state.running = True
    return {"running": True}


@app.post("/bot/stop", dependencies=[Depends(check_key)])
def bot_stop():
    state.running = False
    return {"running": False}


@app.get("/positions", dependencies=[Depends(check_key)])
def positions():
    return state.positions


@app.post("/positions/{ticket}/close", dependencies=[Depends(check_key)])
def close_position(ticket: int):
    """Titip perintah close; EA menjalankannya saat sinkron berikutnya.
    (Gerbang tak lagi punya koneksi MT5 langsung.)"""
    state.enqueue_command({"type": "close", "ticket": ticket})
    return {"ok": True, "queued": True, "ticket": ticket}


@app.get("/history", dependencies=[Depends(check_key)])
def history(date_from: str | None = None, date_to: str | None = None):
    """Riwayat posisi tertutup (dari fill yang dilaporkan EA). Filter YYYY-MM-DD."""
    items = state.history
    try:
        if date_from:
            f = datetime.fromisoformat(date_from).timestamp()
            items = [h for h in items if h.get("close_time", 0) >= f]
        if date_to:
            t = (datetime.fromisoformat(date_to) + timedelta(days=1)).timestamp()
            items = [h for h in items if h.get("close_time", 0) < t]
    except ValueError:
        raise HTTPException(400, "Format tanggal salah, pakai YYYY-MM-DD")
    return items


@app.get("/signals", dependencies=[Depends(check_key)])
def signals(limit: int = 50):
    return state.signals[-limit:][::-1]


@app.get("/settings", dependencies=[Depends(check_key)])
def get_settings():
    return SET.model_dump()


@app.put("/settings", dependencies=[Depends(check_key)])
def update_settings(new: BotSettings):
    global SET
    SET = new
    save_settings(new)  # bertahan setelah restart
    return SET.model_dump()


# ─────────────────────────────────────────────────────────
#  PROXY ANALISIS → otak FuLens (butuh key)
# ─────────────────────────────────────────────────────────
@app.get("/api/v1/{path:path}", dependencies=[Depends(check_key)])
async def fulens_proxy(path: str, request: Request):
    """Teruskan endpoint analisis FuLens (price/predict/indicators/signal/...).

    Menyuntikkan `mode` = trading_mode bot untuk endpoint yang bergantung mode,
    bila pemanggil tak menyebutkannya. Tanpa ini, layar analisis Flutter memakai
    mode yang DISIMPULKAN dari timeframe (M1 → scalping) sementara bot memakai
    `trading_mode` dari setelan (mis. swing) — layar menampilkan gerbang hijau
    padahal keputusan bot memakai rantai gerbang lain, dan log keputusan 0%.
    """
    params = dict(request.query_params)
    if path.split("/")[0] in ("indicators", "signal") and "mode" not in params:
        params["mode"] = SET.trading_mode
    code, body = await fulens_client.proxy_get(f"/api/v1/{path}", params)
    return JSONResponse(status_code=code, content=body)


# ─────────────────────────────────────────────────────────
#  WEBSOCKET
# ─────────────────────────────────────────────────────────
@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    if ws.query_params.get("key") != ServerConfig.API_KEY:
        await ws.close(code=4401)
        return
    await ws.accept()
    q = state.subscribe()
    try:
        while True:
            msg = await q.get()
            await ws.send_json(msg)
    except Exception:
        pass
    finally:
        state.unsubscribe(q)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=ServerConfig.HOST, port=ServerConfig.PORT, ws="wsproto")
