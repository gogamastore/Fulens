"""Jembatan ke terminal MetaTrader 5 (hanya berjalan di Windows)."""
import logging

import MetaTrader5 as mt5
import pandas as pd

from config import ServerConfig

log = logging.getLogger("mt5")

TIMEFRAMES = {
    "M1": mt5.TIMEFRAME_M1, "M5": mt5.TIMEFRAME_M5, "M15": mt5.TIMEFRAME_M15,
    "M30": mt5.TIMEFRAME_M30, "H1": mt5.TIMEFRAME_H1, "H4": mt5.TIMEFRAME_H4,
    "D1": mt5.TIMEFRAME_D1, "W1": mt5.TIMEFRAME_W1,
}


class MT5Connector:
    def __init__(self):
        self.connected = False

    def connect(self) -> bool:
        kwargs = {}
        if ServerConfig.MT5_PATH:
            kwargs["path"] = ServerConfig.MT5_PATH
        if ServerConfig.MT5_LOGIN:
            kwargs.update(login=ServerConfig.MT5_LOGIN,
                          password=ServerConfig.MT5_PASSWORD,
                          server=ServerConfig.MT5_SERVER)
        self.connected = mt5.initialize(**kwargs)
        if not self.connected:
            log.error("MT5 init gagal: %s", mt5.last_error())
        return self.connected

    def shutdown(self):
        mt5.shutdown()
        self.connected = False

    def get_rates(self, symbol: str, timeframe: str, count: int = 300) -> pd.DataFrame | None:
        """OHLCV sebagai DataFrame, candle terakhir = bar berjalan."""
        rates = mt5.copy_rates_from_pos(symbol, TIMEFRAMES[timeframe], 0, count)
        if rates is None or len(rates) == 0:
            log.warning("Tidak ada data %s %s: %s", symbol, timeframe, mt5.last_error())
            return None
        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s")
        return df

    def account_info(self) -> dict:
        info = mt5.account_info()
        if info is None:
            return {}
        return {
            "login": info.login, "balance": info.balance, "equity": info.equity,
            "margin": info.margin, "free_margin": info.margin_free,
            "profit": info.profit, "currency": info.currency,
        }

    def symbol_info(self, symbol: str):
        mt5.symbol_select(symbol, True)
        return mt5.symbol_info(symbol)

    def current_price(self, symbol: str) -> tuple[float, float] | None:
        tick = mt5.symbol_info_tick(symbol)
        return (tick.bid, tick.ask) if tick else None

    def order_margin(self, symbol: str, direction: str, volume: float) -> float | None:
        """Margin yang dibutuhkan untuk membuka order market sebesar `volume`."""
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            return None
        order_type = mt5.ORDER_TYPE_BUY if direction == "BUY" else mt5.ORDER_TYPE_SELL
        price = tick.ask if direction == "BUY" else tick.bid
        return mt5.order_calc_margin(order_type, symbol, volume, price)

    def server_time(self, symbol: str) -> int | None:
        """Waktu server broker (epoch) dari tick terakhir simbol."""
        tick = mt5.symbol_info_tick(symbol)
        return tick.time if tick else None

    def trade_history(self, date_from, date_to, magic: int | None = None) -> list[dict]:
        """Riwayat posisi TERTUTUP: gabungkan deal masuk & keluar per position_id."""
        deals = mt5.history_deals_get(date_from, date_to) or []
        trades: dict[int, dict] = {}
        for d in sorted(deals, key=lambda x: x.time):
            if not d.symbol:
                continue  # deal balance/deposit
            if magic and d.magic != magic:
                continue
            t = trades.setdefault(d.position_id, {
                "position_id": d.position_id, "symbol": d.symbol,
                "profit": 0.0, "closed": False,
            })
            if d.entry == mt5.DEAL_ENTRY_IN:
                t.update(type="BUY" if d.type == mt5.DEAL_TYPE_BUY else "SELL",
                         volume=d.volume, open_price=d.price,
                         open_time=d.time, comment=d.comment or "")
            else:  # OUT / INOUT / OUT_BY
                t["close_price"] = d.price
                t["close_time"] = d.time
                t["profit"] += d.profit + d.commission + d.swap
                t["closed"] = True
        return sorted([t for t in trades.values() if t["closed"]],
                      key=lambda x: x["close_time"], reverse=True)

    def open_positions(self, magic: int | None = None) -> list[dict]:
        positions = mt5.positions_get() or []
        out = []
        for p in positions:
            if magic and p.magic != magic:
                continue
            out.append({
                "ticket": p.ticket, "symbol": p.symbol,
                "type": "BUY" if p.type == mt5.ORDER_TYPE_BUY else "SELL",
                "volume": p.volume, "price_open": p.price_open,
                "price_current": p.price_current, "sl": p.sl, "tp": p.tp,
                "profit": p.profit, "time": p.time, "comment": p.comment or "",
            })
        return out
