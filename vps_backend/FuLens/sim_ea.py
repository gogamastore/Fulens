"""Simulator EA — uji gerbang + otak TANPA MT5/MQL5.

Meniru apa yang dilakukan FuLensEA.mq5 tiap bar: kirim OHLC + state akun ke
POST /ea/sync, lalu cetak rencana yang dibalas gerbang. Berguna untuk memverifikasi
seluruh pipa (EA → gerbang → otak → gerbang) sebelum menyentuh MQL5.

Hanya pakai stdlib — jalan di mana saja tanpa install apa pun.

Contoh:
  # jalankan brain (:8500) dan gateway (:8000) dulu, lalu:
  python sim_ea.py --gateway http://127.0.0.1:8000 \
                   --key <API_KEY> --symbol XAUUSD --timeframe D1 \
                   --csv ../brain/data/processed/gold_processed.csv
"""
import argparse
import csv
import json
import time
import urllib.request
from datetime import datetime


def load_bars(path: str, n: int) -> list[dict]:
    """Baca CSV (kolom gold_*, kolom pertama = tanggal) → daftar bar OHLC."""
    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
        # Kolom pertama = index tanggal (tak bernama saat ditulis pandas).
        idx = {name: i for i, name in enumerate(header)}
        oc = idx.get("gold_open"); hc = idx.get("gold_high")
        lc = idx.get("gold_low");  cc = idx.get("gold_close")
        vc = idx.get("gold_volume")
        if None in (oc, hc, lc, cc):
            raise SystemExit("CSV tak punya kolom gold_open/high/low/close")
        for r in reader:
            try:
                ts = _to_epoch(r[0])
                rows.append({
                    "time": ts,
                    "open": float(r[oc]), "high": float(r[hc]),
                    "low": float(r[lc]), "close": float(r[cc]),
                    "volume": float(r[vc]) if vc is not None and r[vc] else 0.0,
                })
            except (ValueError, IndexError):
                continue
    return rows[-n:]


def _to_epoch(s: str) -> int:
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S"):
        try:
            return int(datetime.strptime(s.strip(), fmt).timestamp())
        except ValueError:
            continue
    # sudah epoch?
    return int(float(s))


def sync(gateway: str, key: str, body: dict) -> dict:
    req = urllib.request.Request(
        gateway.rstrip("/") + "/ea/sync",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "X-API-Key": key},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gateway", default="http://127.0.0.1:8000")
    ap.add_argument("--key", required=True)
    ap.add_argument("--symbol", default="XAUUSD")
    ap.add_argument("--timeframe", default="D1")
    ap.add_argument("--csv", default="../brain/data/processed/gold_processed.csv")
    ap.add_argument("--bars", type=int, default=200)
    ap.add_argument("--equity", type=float, default=10000.0)
    args = ap.parse_args()

    bars = load_bars(args.csv, args.bars)
    print(f"Memuat {len(bars)} bar dari {args.csv} "
          f"(terakhir close={bars[-1]['close']})")

    body = {
        "symbol": args.symbol,
        "timeframe": args.timeframe,
        "bars": bars,
        "account": {"login": 999, "balance": args.equity, "equity": args.equity,
                    "margin": 0, "free_margin": args.equity, "profit": 0,
                    "currency": "USD"},
        "positions": [],   # sim mulai tanpa posisi
        "fills": [],
    }

    t0 = time.time()
    plan = sync(args.gateway, args.key, body)
    dt = (time.time() - t0) * 1000
    print(f"\n=== RENCANA dari gerbang ({dt:.0f} ms) ===")
    for k in ("symbol", "signal", "target", "actionable", "confidence",
              "atr", "sl_distance", "tp_distance", "running",
              "close_on_neutral", "close_on_flip", "risk_percent",
              "magic_number", "close_tickets"):
        print(f"  {k:<18}: {plan.get(k)}")
    print("\n  reasons:")
    for r in plan.get("reasons", []):
        print(f"    - {r}")

    # Ringkasan aksi yang AKAN diambil EA (v1: satu entry).
    print("\n=== Yang akan dilakukan EA ===")
    if plan.get("close_tickets"):
        print(f"  tutup tiket manual: {plan['close_tickets']}")
    if not plan.get("running"):
        print("  bot OFF — tidak buka posisi")
    elif plan.get("actionable") and plan.get("target"):
        sl = plan.get("sl_distance"); tp = plan.get("tp_distance")
        print(f"  BUKA {plan['target']} — SL jarak {sl}, TP jarak {tp} "
              f"(lot dihitung dari equity ÷ SL)")
    elif plan.get("target") is None and plan.get("close_on_neutral"):
        print("  NETRAL — tutup posisi (jika ada)")
    else:
        print("  HOLD — belum ada setup yang lolos gerbang")


if __name__ == "__main__":
    main()
