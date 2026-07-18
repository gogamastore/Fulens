// lib/state/symbol_state.dart
import 'package:flutter/foundation.dart';
import '../services/api_service.dart';
import 'selected_symbol.dart';

/// Konteks global: simbol + timeframe terpilih, plus daftar dari backend.
/// Semua layar mengikuti konteks ini (chart, prediksi, teknikal, backtest,
/// dan timeframe eksekusi bot).
class SymbolState extends ChangeNotifier {
  SymbolState._();
  static final SymbolState instance = SymbolState._();

  final _api = ApiService();
  List<SymbolInfo> symbols = [];
  List<String> timeframes = const ['M1', 'M5', 'M15', 'M30', 'H1', 'H4', 'D1', 'W1'];
  bool loaded = false;

  String get symbol => selectedSymbol;
  String get timeframe => selectedTimeframe;

  SymbolInfo? get current {
    for (final s in symbols) {
      if (s.symbol == selectedSymbol) return s;
    }
    return null;
  }

  void setSymbol(String s) {
    if (s.isNotEmpty && s != selectedSymbol) {
      selectedSymbol = s;
      notifyListeners();
    }
  }

  /// Ganti timeframe global. Selain memengaruhi tampilan semua tab, timeframe
  /// ini juga menjadi timeframe eksekusi bot (di-push ke eksekutor).
  void setTimeframe(String tf) {
    if (tf.isNotEmpty && tf != selectedTimeframe) {
      selectedTimeframe = tf;
      notifyListeners();
      // Best-effort: buat bot mengikuti timeframe global.
      _api.setBotSignalTimeframe(tf).catchError((_) {});
    }
  }

  Future<void> load() async {
    try {
      final list = await _api.getSymbols();
      symbols = list;
      if (list.isNotEmpty && !list.any((e) => e.symbol == selectedSymbol)) {
        selectedSymbol = list.first.symbol;
      }
    } catch (_) {/* biarkan default */}
    try {
      final tfs = await _api.getTimeframes();
      if (tfs.isNotEmpty) timeframes = tfs;
      if (!timeframes.contains(selectedTimeframe)) {
        selectedTimeframe = timeframes.contains('D1') ? 'D1' : timeframes.first;
      }
    } catch (_) {}
    // Selaraskan timeframe global dengan setelan bot saat ini (bila ada).
    try {
      final s = await _api.getBotSettings();
      final tf = (s['signal_timeframe'] ?? '').toString();
      if (tf.isNotEmpty && timeframes.contains(tf)) selectedTimeframe = tf;
    } catch (_) {}
    loaded = true;
    notifyListeners();
  }
}
