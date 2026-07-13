# FuLens — Setup Guide (Windows)

## Struktur Project
```
fulens/
├── SETUP.md              ← Panduan ini
├── requirements.txt      ← Library yang dibutuhkan
├── config.py             ← Konfigurasi & API keys
├── data_pipeline.py      ← Fetch & proses data (jalankan ini dulu)
├── indicators.py         ← Kalkulasi 20+ indikator teknikal
├── ml_model.py           ← Training LSTM + XGBoost (Phase 2)
├── api_server.py         ← FastAPI server (Phase 3)
└── data/                 ← Folder data otomatis dibuat
    ├── raw/
    └── processed/
```

## Langkah Setup (ikuti urutan ini)

### 1. Buat folder project
Buka Command Prompt atau PowerShell, lalu jalankan:
```
mkdir C:\fulens
cd C:\fulens
```

### 2. Buat virtual environment
```
python -m venv venv
venv\Scripts\activate
```
> Kamu akan lihat (venv) di depan prompt — artinya berhasil

### 3. Install semua library
```
pip install -r requirements.txt
```
> Proses ini 3-5 menit tergantung kecepatan internet

### 4. Jalankan data pipeline (fetch data pertama kali)
```
python data_pipeline.py
```
> Akan mendownload data harga emas + fundamental otomatis

### 5. Cek hasil
```
python indicators.py
```
> Akan menampilkan tabel indikator teknikal lengkap di terminal

---
## API Keys yang Dibutuhkan (GRATIS)

| Sumber Data       | Kebutuhan           | Link Daftar                        |
|-------------------|---------------------|------------------------------------|
| Yahoo Finance     | ❌ Tidak perlu key  | Otomatis via yfinance              |
| FRED (Fed/CPI)    | ✅ Gratis           | https://fred.stlouisfed.gov/docs/api/api_key.html |
| Alpha Vantage     | ✅ Gratis (500/hari)| https://www.alphavantage.co/support/#api-key |

Setelah dapat API key, isi di file `config.py`
