"""State yang dilaporkan EA — menggantikan peran MT5Connector di gerbang.

Dulu gerbang query MT5 langsung (library MetaTrader5 Python, Windows-only). Kini
EA yang jadi tangan+mata: ia melaporkan akun/posisi/fill tiap siklus, gerbang
menyimpannya di sini, dan endpoint Flutter membaca dari sini. Gerbang tak lagi
butuh koneksi MT5 sama sekali.

Juga menampung: antrean perintah manual (close/stop dari Flutter) yang ditarik EA
saat sinkron berikutnya, dan pub/sub untuk WebSocket realtime.
"""
import asyncio
import logging
import time
from datetime import datetime, timezone

log = logging.getLogger("ea_state")

MAX_SIGNALS = 200
MAX_HISTORY = 500

# Durasi satu bar per timeframe (detik). EA sync sekali per bar tertutup, jadi
# "terhubung" harus dinilai relatif terhadap timeframe — bukan ambang tetap.
# Di H1, sync 1 jam sekali; ambang 90 dtk akan salah menandai "putus" 58 menit
# tiap jam. Ambang = beberapa kali durasi bar + grace.
_TF_SECONDS = {"M1": 60, "M5": 300, "M15": 900, "M30": 1800,
               "H1": 3600, "H4": 14400, "D1": 86400, "W1": 604800}


class EaState:
    def __init__(self):
        self.account: dict = {}
        self.positions: list[dict] = []      # bentuk MT5 (sama seperti dulu)
        self.history: list[dict] = []        # trade tertutup (dari fill EA)
        self.signals: list[dict] = []        # keputusan bot (untuk /signals)
        self.commands: list[dict] = []       # perintah menunggu untuk EA
        self.running: bool = True            # bot aktif? EA cek ini
        self.last_sync: float = 0.0          # epoch sinkron EA terakhir
        # Simbol & timeframe yang BENAR-BENAR dipakai bot — datang dari EA
        # (input SignalTF di chart), BUKAN dari selektor timeframe di aplikasi.
        # Dipublikasikan lewat /status supaya Flutter bisa menampilkan yang nyata.
        self.last_tf: str = "H1"
        self.last_symbol: str = ""
        self._hist_ids: set = set()          # dedupe history by position_id
        # Tiket per SIMBOL (bukan global). Tiap EA hanya melaporkan posisi
        # simbolnya sendiri; kalau dilacak global, EA simbol lain akan terlihat
        # "menutup" semua posisi yang tidak ia laporkan.
        self._pos_tickets: dict[str, set] = {}
        self.subscribers: set[asyncio.Queue] = set()

    # ── pub/sub (dipanggil dari event loop; aman) ────────────────────
    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=100)
        self.subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue):
        self.subscribers.discard(q)

    def publish(self, event: str, data: dict):
        msg = {"event": event, "data": data,
               "ts": datetime.now(timezone.utc).isoformat()}
        for q in list(self.subscribers):
            try:
                q.put_nowait(msg)
            except asyncio.QueueFull:
                pass

    # ── laporan dari EA ──────────────────────────────────────────────
    def apply_sync(self, symbol: str, account: dict,
                   positions: list[dict], fills: list[dict]):
        """Terapkan satu sinkron EA: perbarui akun/posisi, catat fill ke history,
        publish event realtime. Dipanggil dari event loop (publish aman).

        PENTING — posisi di-MERGE per simbol, bukan diganti seluruhnya. Tiap EA
        satu chart, jadi ia hanya melaporkan posisi simbolnya sendiri. Kalau
        daftar global ditimpa, EA BTCUSD akan menghapus posisi XAUUSD dari
        tampilan, lalu EA XAUUSD mengembalikannya — persis gejala "posisi kadang
        muncul kadang hilang". (Akun tak kena masalah ini karena sama untuk semua
        EA — itu sebabnya equity selalu terlihat mulus.)
        """
        sym = (symbol or "").strip().upper()
        self.last_sync = time.time()
        if account:
            self.account = account
            self.publish("account", account)

        positions = positions or []
        new_tickets = {p.get("ticket") for p in positions if p.get("ticket")}
        prev_tickets = self._pos_tickets.get(sym, set())

        # Event open/close (kosmetik untuk WS; history sebenarnya dari fills).
        for t in new_tickets - prev_tickets:
            p = next((x for x in positions if x.get("ticket") == t), {})
            self.publish("trade_opened", {
                "symbol": p.get("symbol"), "direction": p.get("type"),
                "volume": p.get("volume"), "sl": p.get("sl"), "tp": p.get("tp"),
                "mode": "ea",
            })
        for t in prev_tickets - new_tickets:
            self.publish("trade_closed", {"ticket": t, "symbol": sym})

        self._pos_tickets[sym] = new_tickets
        # Pertahankan posisi simbol LAIN; ganti hanya milik simbol pelapor.
        others = [p for p in self.positions
                  if (p.get("symbol") or "").strip().upper() != sym]
        self.positions = others + positions

        # History: dari fill yang dilaporkan EA (akurat: harga & profit close asli).
        for f in (fills or []):
            pid = f.get("position_id") or f.get("ticket")
            if pid is None or pid in self._hist_ids:
                continue
            self._hist_ids.add(pid)
            self.history.insert(0, {
                "position_id": pid,
                "symbol": f.get("symbol", ""),
                "type": f.get("type", ""),
                "volume": float(f.get("volume", 0) or 0),
                "open_price": float(f.get("open_price", 0) or 0),
                "close_price": float(f.get("close_price", 0) or 0),
                "profit": float(f.get("profit", 0) or 0),
                "open_time": int(f.get("open_time", 0) or 0),
                "close_time": int(f.get("close_time", 0) or 0),
            })
        self.history = self.history[:MAX_HISTORY]

    def record_signal(self, sig: dict):
        """Simpan satu keputusan bot untuk /signals + publish ke WS."""
        sig = {**sig, "time": datetime.now(timezone.utc).isoformat()}
        self.signals.append(sig)
        self.signals = self.signals[-MAX_SIGNALS:]
        self.publish("signal", sig)

    # ── perintah manual dari Flutter → EA ────────────────────────────
    def enqueue_command(self, cmd: dict):
        self.commands.append(cmd)

    def take_commands(self) -> list[dict]:
        """EA menariknya saat sinkron; konsumsi (kosongkan antrean)."""
        cmds, self.commands = self.commands, []
        return cmds

    # ── util ─────────────────────────────────────────────────────────
    def ea_connected(self) -> bool:
        """Dianggap terhubung bila sync terakhir masih dalam jangkauan wajar untuk
        timeframe-nya (EA sync sekali per bar tertutup). 2.5× durasi bar + 2 menit
        grace: cukup longgar agar tak flapping antar-bar, cukup ketat untuk
        mendeteksi EA yang benar-benar berhenti (~lewat 2-3 bar tanpa kabar)."""
        if self.last_sync <= 0:
            return False
        bar = _TF_SECONDS.get((self.last_tf or "H1").upper(), 3600)
        grace = max(2.5 * bar, 120)
        return (time.time() - self.last_sync) <= grace
