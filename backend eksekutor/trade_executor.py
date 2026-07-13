"""Eksekusi order ke MT5."""
import logging

import MetaTrader5 as mt5

log = logging.getLogger("executor")


def pick_filling_mode(symbol: str) -> int:
    """Pilih filling mode yang didukung broker untuk simbol ini."""
    info = mt5.symbol_info(symbol)
    if info:
        fm = info.filling_mode  # bitmask: 1=FOK, 2=IOC
        if fm & 2:
            return mt5.ORDER_FILLING_IOC
        if fm & 1:
            return mt5.ORDER_FILLING_FOK
    return mt5.ORDER_FILLING_RETURN


class TradeExecutor:
    def __init__(self, magic: int):
        self.magic = magic

    def open_market(self, symbol: str, direction: str, volume: float,
                    sl: float, tp: float, comment: str = "bot") -> dict:
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            return {"ok": False, "error": "no tick"}
        order_type = mt5.ORDER_TYPE_BUY if direction == "BUY" else mt5.ORDER_TYPE_SELL
        price = tick.ask if direction == "BUY" else tick.bid
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol, "volume": volume, "type": order_type,
            "price": price, "sl": sl, "tp": tp,
            "deviation": 20, "magic": self.magic, "comment": comment[:26],
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": pick_filling_mode(symbol),
        }
        result = mt5.order_send(request)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            err = result.comment if result else str(mt5.last_error())
            log.error("Order %s %s gagal: %s", direction, symbol, err)
            return {"ok": False, "error": err}
        log.info("Order %s %s %.2f lot @ %.5f (SL %.5f TP %.5f) ticket %s",
                 direction, symbol, volume, price, sl, tp, result.order)
        return {"ok": True, "ticket": result.order, "price": price}

    def modify_sltp(self, ticket: int, symbol: str, sl: float, tp: float) -> bool:
        request = {"action": mt5.TRADE_ACTION_SLTP, "position": ticket,
                   "symbol": symbol, "sl": sl, "tp": tp}
        result = mt5.order_send(request)
        return result is not None and result.retcode == mt5.TRADE_RETCODE_DONE

    def close_position(self, ticket: int) -> dict:
        pos = mt5.positions_get(ticket=ticket)
        if not pos:
            return {"ok": False, "error": "posisi tidak ditemukan"}
        p = pos[0]
        tick = mt5.symbol_info_tick(p.symbol)
        close_type = mt5.ORDER_TYPE_SELL if p.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
        price = tick.bid if p.type == mt5.ORDER_TYPE_BUY else tick.ask
        request = {
            "action": mt5.TRADE_ACTION_DEAL, "position": ticket,
            "symbol": p.symbol, "volume": p.volume, "type": close_type,
            "price": price, "deviation": 20, "magic": self.magic,
            "comment": "manual close", "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": pick_filling_mode(p.symbol),
        }
        result = mt5.order_send(request)
        ok = result is not None and result.retcode == mt5.TRADE_RETCODE_DONE
        return {"ok": ok, "error": None if ok else (result.comment if result else "send gagal")}
