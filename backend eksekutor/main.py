"""Gerbang tunggal untuk aplikasi Flutter (REST + WebSocket).

Jalan di VPS Windows yang sama dengan terminal MT5 & otak FuLens:
    pip install -r requirements.txt
    uvicorn main:app --host 0.0.0.0 --port 8000

Dua kelompok endpoint:
  • Trading  (/status, /bot/*, /positions, /history, /signals, /settings, /ws)
      → dilayani lokal oleh BotEngine, butuh header X-API-Key.
  • Analisis (/api/v1/*)  → di-proxy ke otak FuLens (localhost:8500)
      sehingga layar chart/prediksi/fundamental Flutter tetap satu pintu.
"""
import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

from fastapi import (Depends, FastAPI, Header, HTTPException, Request,
                     WebSocket)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

import fulens_client
from bot_engine import BotEngine
from config import BotSettings, ServerConfig, settings

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(name)s %(levelname)s %(message)s")
logging.getLogger("asyncio").setLevel(logging.ERROR)

engine = BotEngine(settings)


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(engine.run())
    try:
        yield
    finally:
        task.cancel()


app = FastAPI(title="FuLens Executor Gateway", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                   allow_headers=["*"])  # untuk build web Flutter


def check_key(x_api_key: str = Header(default="")):
    if x_api_key != ServerConfig.API_KEY:
        raise HTTPException(status_code=401, detail="API key salah")


# ---------- Info / health (tanpa key, untuk cek koneksi Flutter) ----------
@app.get("/health")
async def health():
    status, _ = await fulens_client.proxy_get("/health")
    return {
        "status": "ok",
        "gateway": True,
        "mt5_connected": engine.mt5.connected,
        "bot_running": engine.running,
        "fulens_reachable": status == 200,
        "timestamp": datetime.now().isoformat(),
    }


# ---------- Trading (butuh key) ----------
@app.get("/status", dependencies=[Depends(check_key)])
def status():
    return {"running": engine.running, "mt5_connected": engine.mt5.connected,
            "account": engine.mt5.account_info(), "symbols": engine.s.symbols}


@app.post("/bot/start", dependencies=[Depends(check_key)])
def bot_start():
    if not engine.start():
        raise HTTPException(500, "Gagal terhubung ke terminal MT5")
    return {"running": True}


@app.post("/bot/stop", dependencies=[Depends(check_key)])
def bot_stop():
    engine.stop()
    return {"running": False}


@app.get("/positions", dependencies=[Depends(check_key)])
def positions():
    return engine.mt5.open_positions(engine.s.magic_number)


@app.post("/positions/{ticket}/close", dependencies=[Depends(check_key)])
def close_position(ticket: int):
    result = engine.executor.close_position(ticket)
    if not result["ok"]:
        raise HTTPException(400, result["error"])
    return result


@app.get("/history", dependencies=[Depends(check_key)])
def history(date_from: str | None = None, date_to: str | None = None):
    """Riwayat posisi tertutup bot. Format tanggal: YYYY-MM-DD. Default 7 hari terakhir."""
    try:
        f = datetime.fromisoformat(date_from) if date_from else datetime.now() - timedelta(days=7)
        t = (datetime.fromisoformat(date_to) + timedelta(days=1)) if date_to \
            else datetime.now() + timedelta(days=1)
    except ValueError:
        raise HTTPException(400, "Format tanggal salah, pakai YYYY-MM-DD")
    return engine.mt5.trade_history(f, t, engine.s.magic_number)


@app.get("/signals", dependencies=[Depends(check_key)])
def signals(limit: int = 50):
    return engine.signals[-limit:][::-1]


@app.get("/settings", dependencies=[Depends(check_key)])
def get_settings():
    return engine.s.model_dump()


@app.put("/settings", dependencies=[Depends(check_key)])
def update_settings(new: BotSettings):
    engine.s = new
    engine.risk.s = new
    return engine.s.model_dump()


# ---------- Proxy analisis → otak FuLens (butuh key) ----------
@app.get("/api/v1/{path:path}", dependencies=[Depends(check_key)])
async def fulens_proxy(path: str, request: Request):
    """Teruskan endpoint analisis FuLens (price/predict/indicators/... ) ke :8500."""
    params = dict(request.query_params)
    code, body = await fulens_client.proxy_get(f"/api/v1/{path}", params)
    return JSONResponse(status_code=code, content=body)


# ---------- WebSocket ----------
@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    if ws.query_params.get("key") != ServerConfig.API_KEY:
        await ws.close(code=4401)
        return
    await ws.accept()
    q = engine.subscribe()
    try:
        while True:
            msg = await q.get()
            await ws.send_json(msg)
    except Exception:
        pass
    finally:
        engine.unsubscribe(q)


if __name__ == "__main__":
    import uvicorn
    # ws="wsproto": handler WebSocket yang stabil (hindari inkompatibilitas
    # library `websockets` versi baru dengan handler bawaan uvicorn).
    uvicorn.run(app, host=ServerConfig.HOST, port=ServerConfig.PORT, ws="wsproto")
