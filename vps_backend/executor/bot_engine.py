"""Loop utama eksekutor.

TIDAK ADA otak/strategi di sini. Setiap siklus:
  1. Tanya arah ke FuLens (fetch_signal) untuk tiap simbol.
  2. Terjemahkan ke aksi: buka / tutup / balik arah posisi.
  3. Ukuran lot & SL/TP dihitung dari ATR (mekanika risiko), lalu kirim ke MT5.
  4. Kelola trailing stop + proteksi drawdown harian.
"""
import asyncio
import logging
from datetime import date, datetime, timezone

import fulens_client
from config import BotSettings
from mt5_connector import MT5Connector
from risk_manager import RiskManager
from strategy.indicators import enrich
from trade_executor import TradeExecutor

log = logging.getLogger("engine")


class BotEngine:
    def __init__(self, settings: BotSettings):
        self.s = settings
        self.mt5 = MT5Connector()
        self.risk = RiskManager(self.mt5, settings)
        self.executor = TradeExecutor(settings.magic_number)
        self.running = False
        self.signals: list[dict] = []
        self.subscribers: set[asyncio.Queue] = set()
        self._day = date.today()
        self._last_dir: dict[str, str | None] = {}  # arah FuLens terakhir per simbol

    # ---------- pub/sub ----------
    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=100)
        self.subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue):
        self.subscribers.discard(q)

    def _publish(self, event: str, data: dict):
        msg = {"event": event, "data": data,
               "ts": datetime.now(timezone.utc).isoformat()}
        for q in list(self.subscribers):
            try:
                q.put_nowait(msg)
            except asyncio.QueueFull:
                pass

    # ---------- kontrol ----------
    def start(self) -> bool:
        if not self.mt5.connected and not self.mt5.connect():
            return False
        self.running = True
        return True

    def stop(self):
        self.running = False

    # ---------- loop ----------
    async def run(self):
        while True:
            if self.running:
                try:
                    await asyncio.to_thread(self._cycle)
                except Exception:
                    log.exception("Error pada siklus bot")
                self._publish("account", self.mt5.account_info())
            await asyncio.sleep(self.s.loop_interval)

    def _cycle(self):
        # Reset proteksi harian saat ganti hari.
        if date.today() != self._day:
            self._day = date.today()
            self.risk.reset_day()
        if not self.risk.check_daily_drawdown():
            return

        all_pos = self.mt5.open_positions(self.s.magic_number)
        atr_map: dict[str, float] = {}

        # Mode eksekusi: "auto" = semua simbol; "selected" = satu simbol fokus.
        if self.s.execution_mode == "selected":
            active = [self.s.selected_symbol] if self.s.selected_symbol else []
        else:
            active = self.s.symbols

        for symbol in active:
            try:
                self._handle_symbol(symbol, all_pos, atr_map)
            except Exception:
                log.exception("Gagal memproses %s", symbol)

        # Trailing stop untuk posisi yang sedang profit.
        for upd in self.risk.trailing_updates(atr_map):
            if self.executor.modify_sltp(upd["ticket"], upd["symbol"],
                                         upd["sl"], upd["tp"]):
                self._publish("trailing", upd)

    # ---------- keputusan per simbol (100% dari FuLens) ----------
    def _handle_symbol(self, symbol: str, all_pos: list, atr_map: dict):
        decision = fulens_client.fetch_signal(symbol, self.s.signal_timeframe)
        if decision is None:
            return  # otak tak terjangkau / simbol di luar cakupan FuLens

        # Rate pada TIMEFRAME SINYAL: sumber timing stochastic + jarak scaling entry.
        # (Jarak SL/TP TIDAK dari sini — lihat atr_risk di bawah.) Mekanika eksekusi,
        # bukan penentu arah.
        df = self.mt5.get_rates(symbol, self.s.signal_timeframe)
        need_bars = max(self.s.atr_period, 20) + 5
        if df is None or len(df) < need_bars:
            return
        df = enrich(df, self.s.atr_period)
        atr = float(df["atr"].iloc[-1])          # ATR timeframe sinyal → dipakai untuk
        stoch_k = float(df["stoch_k"].iloc[-1])  # timing stochastic & jarak scaling entry.

        # ATR untuk JARAK SL/TP (+trailing), sumbernya diatur `atr_timeframe`:
        #  • "auto" → ikut timeframe pilihan pengguna di Flutter (signal_timeframe),
        #             sehingga SL/TP menyesuaikan horizon trading yang sedang dipakai.
        #  • nilai eksplisit (mis. "M30"/"H1") → di-PIN, tak ikut pilihan pengguna.
        # Saat sama dengan signal_timeframe, pakai ulang `atr` — tak perlu fetch lagi.
        atr_risk = atr
        risk_tf = (self.s.atr_timeframe or "auto").strip()
        if risk_tf.lower() in ("auto", "signal", "ikut"):
            risk_tf = self.s.signal_timeframe
        if risk_tf and risk_tf != self.s.signal_timeframe:
            dfr = self.mt5.get_rates(symbol, risk_tf)
            if dfr is not None and len(dfr) >= need_bars:
                dfr = enrich(dfr, self.s.atr_period)
                atr_risk = float(dfr["atr"].iloc[-1])
        atr_map[symbol] = atr_risk  # trailing stop ikut ATR risiko (selaras SL/TP)

        sym_pos = [p for p in all_pos if p["symbol"] == symbol]
        target = decision.direction  # "BUY" / "SELL" / None
        actionable = (
            target is not None
            and decision.confidence >= self.s.min_confidence
            and (not self.s.require_strong or decision.strong)
        )

        rec = decision.to_dict()
        rec.update(mode="fulens", executed=False, executed_entries=0,
                   planned_entries=0, atr=atr_risk, stoch_k=round(stoch_k, 2))

        closed = 0
        # 1) NETRAL → tutup semua posisi simbol ini (jika diaktifkan).
        if target is None:
            if self.s.close_on_neutral:
                closed += self._close_all(sym_pos, "FuLens NETRAL")
            rec["closed_positions"] = closed
            self._last_dir[symbol] = None
            self._record_signal(rec)
            return

        # 2) Arah berbalik → tutup posisi lawan arah.
        opposite = [p for p in sym_pos if p["type"] != target]
        if opposite and self.s.close_on_flip:
            closed += self._close_all(opposite, f"FuLens balik arah → {target}")
        rec["closed_positions"] = closed

        same_dir = [p for p in sym_pos if p["type"] == target]
        m = len(same_dir)  # jumlah entry searah yang sudah terbuka
        total_open = len(all_pos) - closed

        # 3) Timing entry (Stochastic) — HANYA di M15 dan HANYA untuk entry PERTAMA.
        #    SELL tunggu overbought (%K ≥ atas); BUY tunggu oversold (%K ≤ bawah).
        #    Entry tambahan TIDAK ikut gerbang ini: ia punya gerbang sendiri (jarak
        #    ATR di bawah). Kalau ikut, mode "pyramid" mustahil tereksekusi — BUY
        #    menuntut %K ≤ 20 padahal pyramiding menambah justru saat harga naik
        #    (%K tinggi). Timeframe lain: entry mengikuti sinyal saja.
        timing_ok = True
        if (self.s.entry_timing_enabled and self.s.signal_timeframe == "M15"
                and m == 0):
            timing_ok = (stoch_k >= self.s.stoch_upper if target == "SELL"
                         else stoch_k <= self.s.stoch_lower)

        # 4) Entry bertahap (scaling). Maks 1 entry per siklus.
        max_entries = (self.s.max_positions_per_symbol
                       if self.s.scaling_mode != "off" else 1)

        allow_add = (
            actionable and timing_ok
            and m < max_entries
            and total_open < self.s.max_open_positions
        )
        # Entry ke-2 dst: harga harus sudah bergerak ≥ m × add_step_atr × ATR dari
        # entry PERTAMA. Arah yang dituntut tergantung scaling_mode:
        #   • pyramid      → gerakan SEARAH profit (BUY: naik, SELL: turun).
        #   • average_down → gerakan MELAWAN posisi (BUY: turun, SELL: naik).
        if allow_add and m >= 1 and atr > 0:
            anchor = min(same_dir, key=lambda p: p["time"])
            cur = same_dir[0]["price_current"]
            favor = (cur - anchor["price_open"]) if target == "BUY" \
                else (anchor["price_open"] - cur)   # >0 = profit, <0 = melawan
            moved = favor if self.s.scaling_mode == "pyramid" else -favor
            need = m * self.s.add_step_atr * atr
            if moved < need:
                allow_add = False
            else:
                rec["scaling"] = (f"{self.s.scaling_mode} e{m + 1}: gerak "
                                  f"{moved:.2f} ≥ {need:.2f} ({m * self.s.add_step_atr}×ATR)")

        rec["planned_entries"] = 1 if allow_add else 0
        if actionable and not timing_ok:
            thr = self.s.stoch_upper if target == "SELL" else self.s.stoch_lower
            op = "≥" if target == "SELL" else "≤"
            rec["timing_wait"] = f"menunggu Stoch %K {op} {thr} (kini {stoch_k:.1f})"

        if allow_add:
            # TP mengecil tiap entry tambahan: entry-1 = tp_atr_mult (2.5),
            # entry-2 = 2.0, entry-3 = 1.5, ... dibatasi min_tp_atr_mult.
            tp_mult = max(self.s.tp_atr_mult - m * self.s.tp_step_atr,
                          self.s.min_tp_atr_mult)
            plan = self.risk.build_plan(symbol, target, atr_risk, self.s.risk_percent,
                                        tp_mult=tp_mult)
            if plan and plan.volume > 0:
                acc = self.mt5.account_info()
                need = self.mt5.order_margin(symbol, target, plan.volume)
                if acc and need is not None and acc.get("free_margin", 0) >= need:
                    result = self.executor.open_market(
                        symbol, target, plan.volume, plan.sl, plan.tp,
                        comment=f"fulens {decision.raw_signal} e{m + 1}"[:26])
                    if result["ok"]:
                        rec["executed"] = True
                        rec["executed_entries"] = 1
                        rec["entry_index"] = m + 1
                        self._publish("trade_opened", {
                            "symbol": symbol, "direction": target, "mode": "fulens",
                            "volume": plan.volume, "sl": plan.sl, "tp": plan.tp,
                            "confidence": decision.confidence,
                            "entry": f"{m + 1}/{max_entries}",
                            "reasons": decision.reasons,
                        })
                else:
                    log.info("%s: margin tak cukup untuk entry FuLens", symbol)

        self._last_dir[symbol] = target
        self._record_signal(rec)

    # ---------- util ----------
    def _close_all(self, positions: list, reason: str) -> int:
        n = 0
        for p in positions:
            result = self.executor.close_position(p["ticket"])
            if result["ok"]:
                n += 1
                self._publish("trade_closed", {
                    "symbol": p["symbol"], "ticket": p["ticket"],
                    "reason": reason, "profit": p.get("profit", 0),
                })
        return n

    def _record_signal(self, sig: dict):
        sig["time"] = datetime.now(timezone.utc).isoformat()
        self.signals.append(sig)
        self.signals = self.signals[-200:]
        self._publish("signal", sig)
