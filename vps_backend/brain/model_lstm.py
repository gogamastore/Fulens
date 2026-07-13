"""
FuLens — Model LSTM (PyTorch)
Training, evaluasi, dan prediksi menggunakan LSTM Neural Network.

Jalankan: python model_lstm.py
"""

import warnings
warnings.filterwarnings("ignore")

import pandas as pd
import numpy as np
import joblib
import json
from datetime import datetime, timedelta
from colorama import init, Fore, Style
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

init(autoreset=True)
import config
from data_pipeline import load_processed_data
from features import build_feature_set, prepare_ml_dataset, prepare_lstm_dataset, get_feature_columns

def log(msg, level="INFO"):
    colors = {"INFO": Fore.CYAN, "OK": Fore.GREEN, "WARN": Fore.YELLOW, "ERR": Fore.RED}
    prefix = {"INFO": "●", "OK": "✓", "WARN": "⚠", "ERR": "✗"}
    print(f"{colors.get(level,'')}[{prefix.get(level,'·')}] {msg}{Style.RESET_ALL}")


# ─────────────────────────────────────────────────────────
#  CEK PYTORCH
# ─────────────────────────────────────────────────────────
try:
    import torch
    import torch.nn as nn
    from torch.utils.data import DataLoader, TensorDataset
    TORCH_OK = True
    log(f"PyTorch {torch.__version__} siap", "OK")
    DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    log(f"Device: {DEVICE}", "OK")
except ImportError:
    TORCH_OK = False
    log("PyTorch tidak ditemukan!", "ERR")
    log("Install: pip install torch --index-url https://download.pytorch.org/whl/cpu", "WARN")


# ─────────────────────────────────────────────────────────
#  ARSITEKTUR LSTM
# ─────────────────────────────────────────────────────────
class GoldLSTM(nn.Module):
    """
    LSTM multi-layer untuk prediksi harga emas.
    Arsitektur: LSTM → Dropout → LSTM → Dropout → FC layers
    """
    def __init__(self, input_size, hidden_sizes, dropout=0.2):
        super().__init__()
        self.hidden_sizes = hidden_sizes

        # Layer LSTM bertumpuk
        self.lstm_layers = nn.ModuleList()
        in_sz = input_size
        for i, h_sz in enumerate(hidden_sizes):
            self.lstm_layers.append(
                nn.LSTM(in_sz, h_sz, batch_first=True,
                        dropout=dropout if i < len(hidden_sizes)-1 else 0)
            )
            in_sz = h_sz

        self.dropout = nn.Dropout(dropout)

        # Fully connected layers
        self.fc = nn.Sequential(
            nn.Linear(hidden_sizes[-1], 64),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(64, 32),
            nn.ReLU(),
            nn.Linear(32, 1)
        )

    def forward(self, x):
        out = x
        for lstm in self.lstm_layers:
            out, _ = lstm(out)
            out = self.dropout(out)
        # Ambil output timestep terakhir
        out = out[:, -1, :]
        return self.fc(out).squeeze(-1)


# ─────────────────────────────────────────────────────────
#  TRAINING LOOP
# ─────────────────────────────────────────────────────────
def train_lstm(X_train_seq, y_train_seq, X_val_seq, y_val_seq,
               input_size, epochs=None, batch_size=None):
    """Training LSTM dengan early stopping."""
    if not TORCH_OK:
        log("PyTorch tidak tersedia, skip LSTM", "ERR")
        return None, []

    epochs     = epochs     or config.LSTM_EPOCHS
    batch_size = batch_size or config.LSTM_BATCH_SIZE

    # Konversi ke tensor
    X_tr = torch.FloatTensor(X_train_seq).to(DEVICE)
    y_tr = torch.FloatTensor(y_train_seq[-len(X_train_seq):]).to(DEVICE)
    X_vl = torch.FloatTensor(X_val_seq).to(DEVICE)
    y_vl = torch.FloatTensor(y_val_seq[-len(X_val_seq):]).to(DEVICE)

    dataset    = TensorDataset(X_tr, y_tr)
    dataloader = DataLoader(dataset, batch_size=batch_size, shuffle=False)

    # Model
    model = GoldLSTM(
        input_size   = input_size,
        hidden_sizes = config.LSTM_UNITS,
        dropout      = config.LSTM_DROPOUT,
    ).to(DEVICE)

    optimizer = torch.optim.Adam(model.parameters(), lr=1e-3, weight_decay=1e-5)
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
        optimizer, patience=10, factor=0.5, min_lr=1e-6
    )
    criterion = nn.HuberLoss()  # Lebih robust dari MSE

    # Early stopping
    best_val_loss  = float("inf")
    patience_count = 0
    patience_limit = 20
    best_state     = None
    history        = []

    log(f"Training LSTM: {epochs} epochs, batch={batch_size}, device={DEVICE}", "INFO")
    log(f"Arsitektur: input={input_size} → {config.LSTM_UNITS} → 1", "INFO")

    for epoch in range(1, epochs + 1):
        # ── Train ──
        model.train()
        train_loss = 0.0
        for X_batch, y_batch in dataloader:
            optimizer.zero_grad()
            pred = model(X_batch)
            loss = criterion(pred, y_batch)
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
            optimizer.step()
            train_loss += loss.item() * len(X_batch)
        train_loss /= len(X_tr)

        # ── Validasi ──
        model.eval()
        with torch.no_grad():
            if len(X_vl) == 0:
                val_loss = train_loss  # pakai train loss jika val kosong
            else:
                val_pred = model(X_vl)
                val_loss = criterion(val_pred, y_vl).item()

        scheduler.step(val_loss)
        history.append({"epoch": epoch, "train_loss": train_loss, "val_loss": val_loss})

        # Log setiap 10 epoch
        if epoch % 10 == 0 or epoch == 1:
            lr = optimizer.param_groups[0]["lr"]
            log(f"  Epoch {epoch:3d}/{epochs} | Train: {train_loss:.5f} | Val: {val_loss:.5f} | LR: {lr:.6f}",
                "OK" if val_loss < best_val_loss else "INFO")

        # Early stopping
        if val_loss < best_val_loss:
            best_val_loss  = val_loss
            patience_count = 0
            best_state     = {k: v.clone() for k, v in model.state_dict().items()}
        else:
            patience_count += 1
            if patience_count >= patience_limit:
                log(f"Early stopping di epoch {epoch} (patience={patience_limit})", "WARN")
                break

    # Load best weights
    if best_state:
        model.load_state_dict(best_state)

    log(f"Training selesai. Best val loss: {best_val_loss:.5f}", "OK")
    return model, history


# ─────────────────────────────────────────────────────────
#  EVALUASI
# ─────────────────────────────────────────────────────────
def evaluate_lstm(model, X_seq, y_true_scaled, scaler_y, label=""):
    """Evaluasi LSTM model."""
    if not TORCH_OK or model is None:
        return {}

    model.eval()
    X_tensor = torch.FloatTensor(X_seq).to(DEVICE)
    with torch.no_grad():
        y_pred_scaled = model(X_tensor).cpu().numpy()

    # Trim y_true agar panjangnya sama dengan sequence output
    y_true_trim = y_true_scaled[-len(y_pred_scaled):]

    y_true_real = scaler_y.inverse_transform(y_true_trim.reshape(-1,1)).ravel()
    y_pred_real = scaler_y.inverse_transform(y_pred_scaled.reshape(-1,1)).ravel()

    mae  = mean_absolute_error(y_true_real, y_pred_real)
    rmse = np.sqrt(mean_squared_error(y_true_real, y_pred_real))
    r2   = r2_score(y_true_real, y_pred_real)
    mape = np.mean(np.abs((y_true_real - y_pred_real) / y_true_real.clip(min=1))) * 100
    acc  = 100 - mape

    dir_true = np.sign(np.diff(y_true_real))
    dir_pred = np.sign(np.diff(y_pred_real))
    dir_acc  = np.mean(dir_true == dir_pred) * 100

    log(f"{'─'*40}", "INFO")
    log(f"Evaluasi LSTM — {label}", "INFO")
    log(f"  MAE         : ${mae:,.2f}", "OK")
    log(f"  RMSE        : ${rmse:,.2f}", "OK")
    log(f"  R²          : {r2:.4f}", "OK")
    log(f"  MAPE        : {mape:.2f}%", "OK")
    log(f"  Akurasi     : {acc:.2f}%", "OK")
    log(f"  Akurasi Arah: {dir_acc:.2f}%", "OK")

    return {"mae": round(mae,2), "rmse": round(rmse,2), "r2": round(r2,4),
            "mape": round(mape,2), "accuracy": round(acc,2),
            "direction_accuracy": round(dir_acc,2)}


# ─────────────────────────────────────────────────────────
#  PREDIKSI
# ─────────────────────────────────────────────────────────
def predict_lstm_future(model, X_test_seq, scaler_X, scaler_y,
                        feature_cols, df_features,
                        horizons=[1, 3, 7, 14, 30]):
    """Prediksi multi-horizon dengan LSTM."""
    if not TORCH_OK or model is None:
        return {}, 0.0

    cur = float(df_features["gold_close"].iloc[-1])

    # Ambil data terakhir, gunakan lookback fleksibel
    last_data = df_features[feature_cols].copy()
    last_data = last_data.ffill().bfill()
    last_data = last_data.replace([np.inf, -np.inf], np.nan).fillna(0)
    last_data = last_data.values

    # Gunakan lookback sesuai data yang tersedia (min 5)
    lb = min(config.LSTM_LOOKBACK, max(5, len(last_data) // 4))
    if len(last_data) < lb:
        log(f"Data tidak cukup untuk LSTM sequence (butuh {lb}, ada {len(last_data)})", "WARN")
        return {}, cur

    last_seq = scaler_X.transform(last_data[-lb:])

    model.eval()
    predictions = {}

    # Prediksi 1 hari langsung (paling akurat)
    x_tensor = torch.FloatTensor(last_seq[np.newaxis, :, :]).to(DEVICE)
    with torch.no_grad():
        pred_1d_scaled = model(x_tensor).cpu().numpy()[0]

    pred_1d_price = float(scaler_y.inverse_transform([[pred_1d_scaled]])[0][0])

    # Return harian — clip ±2.5% (LSTM lebih smooth)
    daily_return = (pred_1d_price - cur) / cur
    daily_return = float(np.clip(daily_return, -0.025, 0.025))

    # LSTM: decay lebih lambat (lebih persistent, berbasis time-series panjang)
    DECAY = 0.80
    for h in horizons:
        cumulative_return = 0.0
        r = daily_return
        for day in range(h):
            cumulative_return += r
            r *= DECAY

        final_price = cur * (1 + cumulative_return)
        # Batas ±0.5% per hari
        max_chg = 0.005 * h
        final_price = float(np.clip(
            final_price,
            cur * (1 - max_chg),
            cur * (1 + max_chg)
        ))

        predictions[h] = {
            "horizon_days"   : h,
            "predicted_price": round(final_price, 2),
            "change_usd"     : round(final_price - cur, 2),
            "change_pct"     : round((final_price - cur) / cur * 100, 2),
            "signal"         : "BELI" if final_price > cur else "JUAL",
            "date"           : (datetime.now() + timedelta(days=h)).strftime("%Y-%m-%d"),
        }

    return predictions, cur


def print_lstm_predictions(predictions, current_price):
    print("\n" + "═"*68)
    print(f"  {'PREDIKSI HARGA EMAS — LSTM':^64}")
    print(f"  {'Harga Saat Ini: $' + f'{current_price:,.2f}':^64}")
    print("═"*68)
    print(f"  {'Horizon':<12} {'Tanggal':<14} {'Prediksi':>12} {'Δ USD':>10} {'Δ %':>8}  Sinyal")
    print("  " + "─"*62)
    for h, p in predictions.items():
        clr  = Fore.GREEN if p["signal"] == "BELI" else Fore.RED
        icon = "▲" if p["signal"] == "BELI" else "▼"
        print(f"  {str(h)+' Hari':<12} {p['date']:<14} "
              f"${p['predicted_price']:>10,.2f} "
              f"{p['change_usd']:>+10.2f} "
              f"{p['change_pct']:>+7.2f}%  "
              f"{clr}{icon} {p['signal']}{Style.RESET_ALL}")
    print("═"*68 + "\n")


# ─────────────────────────────────────────────────────────
#  SIMPAN MODEL
# ─────────────────────────────────────────────────────────
def save_lstm_model(model, metrics, input_size):
    if not TORCH_OK or model is None:
        return
    path = config.MODEL_DIR / "lstm_model.pt"
    torch.save({
        "model_state": model.state_dict(),
        "input_size" : input_size,
        "hidden_sizes": config.LSTM_UNITS,
        "dropout"    : config.LSTM_DROPOUT,
    }, str(path))
    meta = {
        "model_type" : "LSTM-PyTorch",
        "trained_at" : datetime.now().isoformat(),
        "metrics"    : metrics,
        "architecture": {
            "input_size"  : input_size,
            "hidden_sizes": config.LSTM_UNITS,
            "dropout"     : config.LSTM_DROPOUT,
            "lookback"    : config.LSTM_LOOKBACK,
        }
    }
    with open(config.MODEL_DIR / "lstm_meta.json", "w") as f:
        json.dump(meta, f, indent=2)
    log(f"LSTM model disimpan: {path}", "OK")


def load_lstm_model(input_size):
    path = config.MODEL_DIR / "lstm_model.pt"
    if not path.exists():
        raise FileNotFoundError("LSTM model belum ditraining.")
    ckpt  = torch.load(str(path), map_location=DEVICE)
    model = GoldLSTM(ckpt["input_size"], ckpt["hidden_sizes"], ckpt["dropout"]).to(DEVICE)
    model.load_state_dict(ckpt["model_state"])
    model.eval()
    return model


# ─────────────────────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────────────────────
if __name__ == "__main__":
    if not TORCH_OK:
        print("\nInstall PyTorch dulu:")
        print("pip install torch --index-url https://download.pytorch.org/whl/cpu\n")
        exit(1)

    print("\n" + "═"*60)
    print("   🧠 FuLens — LSTM Training (PyTorch)")
    print("═"*60 + "\n")

    # 1. Load & features
    log("Memuat data...", "INFO")
    df = load_processed_data()
    df = build_feature_set(df)

    # 2. Siapkan dataset
    (X_train, X_val, X_test,
     y_train, y_val, y_test,
     scaler_X, scaler_y, feature_cols) = prepare_ml_dataset(df, "target_price_1d")

    input_size = X_train.shape[1]

    # 3. Buat sequences LSTM
    lb = max(5, min(config.LSTM_LOOKBACK, len(X_train) // 4))
    log(f"LSTM lookback: {lb} hari", "INFO")

    X_tr_seq, X_vl_seq, X_ts_seq = prepare_lstm_dataset(X_train, X_val, X_test, lb)

    if len(X_tr_seq) == 0:
        log("Data terlalu sedikit untuk LSTM sequences!", "ERR")
        exit(1)

    # Trim y sesuai sequence
    y_tr_seq = y_train[lb:]
    y_vl_seq = y_val[lb:] if len(y_val) > lb else y_val
    y_ts_seq = y_test[lb:] if len(y_test) > lb else y_test

    if len(X_vl_seq) == 0:
        log("Val sequence kosong — LSTM pakai train loss untuk early stopping", "WARN")

    # 4. Training
    model, history = train_lstm(
        X_tr_seq, y_tr_seq,
        X_vl_seq, y_vl_seq,
        input_size = input_size,
    )

    # 5. Evaluasi
    val_metrics  = {"accuracy": 0, "note": "Val sequence kosong (data kurang)"}
    test_metrics = {"accuracy": 0, "note": "Test sequence kosong (data kurang)"}
    if model and len(X_vl_seq) > 0:
        val_metrics  = evaluate_lstm(model, X_vl_seq, y_vl_seq, scaler_y, "Validasi")
    else:
        log("Val sequence kosong — evaluasi dilewati", "WARN")
    if model and len(X_ts_seq) > 0:
        test_metrics = evaluate_lstm(model, X_ts_seq, y_ts_seq, scaler_y, "Test")
    else:
        log("Test sequence kosong — evaluasi dilewati", "WARN")

    # 6. Prediksi ke depan (pakai semua data untuk sequence)
    preds, cur = predict_lstm_future(
        model, None, scaler_X, scaler_y,
        feature_cols, df, horizons=[1, 3, 7, 14, 30]
    )
    if preds:
        print_lstm_predictions(preds, cur)
    else:
        log("Prediksi dilewati — data tidak cukup untuk sequence", "WARN")

    # 7. Simpan
    save_lstm_model(model, {"validation": val_metrics, "test": test_metrics}, input_size)

    log("LSTM selesai! Lanjut: python ensemble.py", "OK")
