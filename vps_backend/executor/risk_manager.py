"""Perhitungan lot, SL/TP berbasis ATR, trailing stop, dan proteksi akun."""
import logging
from dataclasses import dataclass

from config import BotSettings

log = logging.getLogger("risk")


@dataclass
class TradePlan:
    volume: float
    sl: float
    tp: float


class RiskManager:
    def __init__(self, connector, settings: BotSettings):
        self.mt5 = connector
        self.s = settings
        self.day_start_equity: float | None = None

    def check_daily_drawdown(self) -> bool:
        """True jika masih boleh trading."""
        acc = self.mt5.account_info()
        if not acc:
            return False
        if self.day_start_equity is None:
            self.day_start_equity = acc["equity"]
        dd = (self.day_start_equity - acc["equity"]) / self.day_start_equity * 100
        if dd >= self.s.max_daily_drawdown_pct:
            log.warning("Drawdown harian %.2f%% >= batas %.2f%% — trading dihentikan",
                        dd, self.s.max_daily_drawdown_pct)
            return False
        return True

    def reset_day(self):
        acc = self.mt5.account_info()
        self.day_start_equity = acc.get("equity") if acc else None

    def build_plan(self, symbol: str, direction: str, atr: float,
                   risk_percent: float | None = None,
                   tp_mult: float | None = None) -> TradePlan | None:
        """SL = sl_atr_mult × ATR. TP = (tp_mult atau tp_atr_mult) × ATR.
        `tp_mult` dipakai untuk entry tambahan yang TP-nya mengecil bertahap."""
        info = self.mt5.symbol_info(symbol)
        price = self.mt5.current_price(symbol)
        acc = self.mt5.account_info()
        if not info or not price or not acc:
            return None
        bid, ask = price
        entry = ask if direction == "BUY" else bid

        sl_dist = atr * self.s.sl_atr_mult
        tp_dist = atr * (self.s.tp_atr_mult if tp_mult is None else tp_mult)
        if direction == "BUY":
            sl, tp = entry - sl_dist, entry + tp_dist
        else:
            sl, tp = entry + sl_dist, entry - tp_dist

        # Ukuran lot dari % risiko (per entry)
        risk_money = acc["equity"] * (risk_percent or self.s.risk_percent) / 100
        tick_value = info.trade_tick_value or 0
        tick_size = info.trade_tick_size or info.point
        if tick_value <= 0 or tick_size <= 0:
            log.warning("%s: tick value/size tidak valid", symbol)
            return None
        loss_per_lot = (sl_dist / tick_size) * tick_value
        volume = risk_money / loss_per_lot if loss_per_lot > 0 else 0

        # Normalisasi ke step broker
        step = info.volume_step or 0.01
        volume = max(info.volume_min, min(info.volume_max, round(volume / step) * step))
        volume = round(volume, 2)

        digits = info.digits
        return TradePlan(volume=volume, sl=round(sl, digits), tp=round(tp, digits))

    def trailing_updates(self, atr_map: dict[str, float]) -> list[dict]:
        """Hitung SL baru untuk posisi profit. Return daftar {ticket, symbol, sl, tp}."""
        if not self.s.trailing_enabled:
            return []
        updates = []
        for pos in self.mt5.open_positions(self.s.magic_number):
            if pos.get("comment", "").startswith("scalp"):
                continue  # posisi scalp pakai SL/TP ketat, tanpa trailing
            atr = atr_map.get(pos["symbol"])
            if not atr:
                continue
            start = atr * self.s.trail_start_atr
            dist = atr * self.s.trail_dist_atr
            cur, opened = pos["price_current"], pos["price_open"]
            if pos["type"] == "BUY" and cur - opened >= start:
                new_sl = cur - dist
                if new_sl > pos["sl"]:
                    updates.append({"ticket": pos["ticket"], "symbol": pos["symbol"],
                                    "sl": new_sl, "tp": pos["tp"]})
            elif pos["type"] == "SELL" and opened - cur >= start:
                new_sl = cur + dist
                if pos["sl"] == 0 or new_sl < pos["sl"]:
                    updates.append({"ticket": pos["ticket"], "symbol": pos["symbol"],
                                    "sl": new_sl, "tp": pos["tp"]})
        return updates
