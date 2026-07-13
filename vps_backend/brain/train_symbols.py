"""CLI: latih model ML (XGBoost) per simbol.

Contoh:
    python train_symbols.py                      # semua simbol, timeframe D1
    python train_symbols.py --tf D1,H1           # dua timeframe
    python train_symbols.py --symbols XAUUSD,EURUSD --tf H1

Model tersimpan di models/sym_<SYMBOL>_<TF>_xgb.json. Jalankan ulang berkala
(mis. mingguan) agar model belajar data terbaru.
"""
import argparse
import logging

import ml_symbol
import symbols as sym

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")


def main():
    ap = argparse.ArgumentParser(description="Latih ML per simbol (XGBoost)")
    ap.add_argument("--symbols", default="",
                    help="daftar simbol dipisah koma (default: semua)")
    ap.add_argument("--tf", default="D1",
                    help="daftar timeframe dipisah koma (mis. D1,H1)")
    args = ap.parse_args()

    syms = ([s.strip().upper() for s in args.symbols.split(",") if s.strip()]
            or [s["symbol"] for s in sym.all_symbols()])
    tfs = [t.strip().upper() for t in args.tf.split(",") if t.strip()]

    print(f"\nMelatih {len(syms)} simbol × {len(tfs)} timeframe...\n")
    ok, fail = 0, 0
    for s in syms:
        for tf in tfs:
            print(f"→ {s} {tf} ... ", end="", flush=True)
            try:
                meta = ml_symbol.train(s, tf)
                if meta:
                    print(f"akurasi test {meta['test_accuracy']:.3f} "
                          f"(baseline {meta['baseline']:.3f})")
                    ok += 1
                else:
                    print("dilewati (data kurang)")
                    fail += 1
            except Exception as e:
                print(f"GAGAL: {e}")
                fail += 1

    print(f"\nSelesai. Berhasil: {ok}, gagal/dilewati: {fail}\n")


if __name__ == "__main__":
    main()
