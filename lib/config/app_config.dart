// lib/config/app_config.dart

/// Konfigurasi koneksi ke backend Python (gerbang eksekutor :8000).
///
/// Flutter cukup bicara ke SATU pintu: gerbang eksekutor. Gerbang ini melayani
/// endpoint trading secara lokal dan mem-proxy endpoint analisis FuLens.
class AppConfig {
  // Ganti dengan IP/host VPS Windows tempat backend berjalan.
  // Contoh: '100.78.56.14:8000' (Tailscale) atau 'localhost:8000' saat lokal.
  static const String host = '93.127.140.99:8000';

  // WAJIB sama dengan ServerConfig.API_KEY di 'backend eksekutor/config.py'.
  static const String apiKey = 'CN9-5UB1TBJMD5wM_WR5dNiPr_Gbq9CXz6dt8Pa1spg';

  static String get baseUrl => 'http://$host';
  static String get wsUrl => 'ws://$host/ws?key=$apiKey';

  /// Header wajib untuk endpoint bergerbang (trading + proxy analisis).
  static Map<String, String> get headers => {
        'X-API-Key': apiKey,
        'Content-Type': 'application/json',
      };
}
