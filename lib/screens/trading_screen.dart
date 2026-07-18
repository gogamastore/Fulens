// lib/screens/trading_screen.dart
import 'dart:async';
import 'package:flutter/material.dart';
import 'package:syncfusion_flutter_charts/charts.dart';
import '../core/theme.dart';
import '../services/api_service.dart';
import '../services/ws_service.dart';
import '../state/symbol_state.dart';
import '../widgets/fibonacci_chart.dart';

/// Pusat kontrol eksekutor: status koneksi, start/stop bot, akun MT5,
/// sinyal FuLens terkini, live chart Fibonacci, dan log keputusan bot.
class TradingScreen extends StatefulWidget {
  const TradingScreen({super.key});

  @override
  State<TradingScreen> createState() => _TradingScreenState();
}

class _TradingScreenState extends State<TradingScreen> {
  final _api = ApiService();
  final _ws = WsService();
  StreamSubscription? _evtSub;
  StreamSubscription? _statSub;
  Timer? _poll;

  BotStatus? _status;
  List<OhlcData> _candles = [];
  List<BotSignal> _signals = [];
  double? _currentPrice;
  WsStatus _wsStatus = WsStatus.disconnected;
  bool _loading = true;
  bool _toggling = false;
  String? _error;

  // Mode kerja OTAK, bukan mode eksekusi simbol. Berlaku untuk semua simbol —
  // simbol mana yang ditradingkan ditentukan chart tempat EA dipasang.
  String _tradingMode = 'swing';    // 'swing' | 'scalping'
  // Timeframe yang DIEKSEKUSI bot. EA mendorong data SEMUA timeframe (agar layar
  // analisis memakai harga broker asli), tapi yang ditradingkan hanya yang ini.
  String _execTf = 'M15';
  bool _savingMode = false;
  BacktestResult? _backtest;
  bool _btLoading = false;

  int _maxEntries = 1;              // jumlah entry per simbol
  double _riskPct = 0.5;           // risk % per entry
  // Ambang kualitas setup (min_confidence di executor). Skala 50-100: dengan
  // gerbang AND, setup yang lolos SELALU >= 50, jadi 50 = tanpa saringan.
  double _minConf = 50.0;
  bool _closeOnNeutral = true;     // tutup posisi saat sinyal NETRAL
  bool _closeOnFlip = true;        // tutup posisi saat sinyal berbalik arah
  bool _savingEntry = false;

  // Timeframe eksekusi = timeframe global (diatur dari bar atas).
  String get _tf => SymbolState.instance.timeframe;

  @override
  void initState() {
    super.initState();
    _ws.connect();
    _wsStatus = _ws.currentStatus;
    _statSub = _ws.status.listen((s) {
      if (mounted) setState(() => _wsStatus = s);
    });
    _evtSub = _ws.events.listen(_onEvent);
    _loadAll();
    _poll = Timer.periodic(const Duration(seconds: 8), (_) => _loadStatus(silent: true));
  }

  @override
  void dispose() {
    _poll?.cancel();
    _evtSub?.cancel();
    _statSub?.cancel();
    super.dispose();
  }

  void _onEvent(BotEvent e) {
    if (!mounted) return;
    switch (e.event) {
      case 'account':
        setState(() {
          if (_status != null) {
            _status = BotStatus(
              running: _status!.running,
              mt5Connected: _status!.mt5Connected,
              account: AccountInfo.fromJson(e.data),
              symbols: _status!.symbols,
            );
          }
        });
        break;
      case 'signal':
        setState(() {
          _signals = [BotSignal.fromJson(e.data), ..._signals].take(30).toList();
          final p = (e.data['price'] ?? 0).toDouble();
          if (p > 0) _currentPrice = p;
        });
        break;
      case 'trade_opened':
      case 'trade_closed':
        _loadStatus(silent: true);
        break;
    }
  }

  Future<void> _loadAll() async {
    setState(() => _loading = true);
    await Future.wait([
      _loadStatus(silent: true),
      _loadChart(),
      _loadSignals(),
      _loadSettings(),
    ]);
    if (mounted) setState(() => _loading = false);
  }

  Future<void> _loadSettings() async {
    try {
      final s = await _api.getBotSettings();
      if (mounted) {
        setState(() {
          _tradingMode = (s['trading_mode'] ?? 'swing').toString();
          _execTf = (s['exec_timeframe'] ?? 'M15').toString();
          _maxEntries = (s['max_positions_per_symbol'] ?? 1) as int;
          _riskPct = ((s['risk_percent'] ?? 0.5) as num).toDouble();
          _minConf = ((s['min_confidence'] ?? 50.0) as num).toDouble();
          _closeOnNeutral = (s['close_on_neutral'] ?? true) as bool;
          _closeOnFlip = (s['close_on_flip'] ?? true) as bool;
        });
      }
    } catch (_) {}
  }

  Future<void> _saveEntrySettings() async {
    setState(() => _savingEntry = true);
    try {
      final s = await _api.getBotSettings();
      s['max_positions_per_symbol'] = _maxEntries;
      s['risk_percent'] = double.parse(_riskPct.toStringAsFixed(2));
      s['min_confidence'] = _minConf;
      s['close_on_neutral'] = _closeOnNeutral;
      s['close_on_flip'] = _closeOnFlip;
      await _api.updateBotSettings(s);
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text('Gagal simpan pengaturan: $e')));
      }
    } finally {
      if (mounted) setState(() => _savingEntry = false);
    }
  }

  Future<void> _setExecTimeframe(String tf) async {
    if (_savingMode) return;
    setState(() => _savingMode = true);
    try {
      final s = await _api.getBotSettings();
      s['exec_timeframe'] = tf;   // gerbang memakai ini untuk menghitung rencana
      await _api.updateBotSettings(s);
      if (mounted) setState(() => _execTf = tf);
      await _loadStatus();        // /status melaporkan TF eksekusi yang baru
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text('Gagal ubah timeframe: $e')));
      }
    } finally {
      if (mounted) setState(() => _savingMode = false);
    }
  }

  Future<void> _setTradingMode(String mode) async {
    if (_savingMode) return;
    setState(() => _savingMode = true);
    try {
      final s = await _api.getBotSettings();
      s['trading_mode'] = mode;   // otak memakai ini untuk memilih rantai gerbang
      await _api.updateBotSettings(s);
      if (mounted) setState(() => _tradingMode = mode);
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text('Gagal ubah mode: $e')));
      }
    } finally {
      if (mounted) setState(() => _savingMode = false);
    }
  }

  Future<void> _runBacktest() async {
    setState(() => _btLoading = true);
    try {
      final r = await _api.getBacktest(symbol: SymbolState.instance.symbol);
      if (mounted) setState(() => _backtest = r);
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text('Backtest gagal: $e')));
      }
    } finally {
      if (mounted) setState(() => _btLoading = false);
    }
  }

  Future<void> _loadStatus({bool silent = false}) async {
    try {
      final s = await _api.getStatus();
      if (mounted) {
        setState(() {
          _status = s;
          _error = null;
        });
      }
    } catch (e) {
      if (mounted && !silent) {
        setState(() => _error = '$e');
      }
    }
  }

  Future<void> _loadChart() async {
    try {
      final h = await _api.getHistory(days: 120); // ikut timeframe global
      if (mounted) {
        setState(() {
          _candles = h;
          if (h.isNotEmpty) _currentPrice = h.last.close;
        });
      }
    } catch (_) {/* chart opsional */}
  }

  Future<void> _loadSignals() async {
    try {
      final s = await _api.getBotSignals(limit: 30);
      if (mounted) setState(() => _signals = s);
    } catch (_) {}
  }

  Future<void> _toggleBot() async {
    if (_status == null) return;
    setState(() => _toggling = true);
    try {
      if (_status!.running) {
        await _api.stopBot();
      } else {
        await _api.startBot();
      }
      await _loadStatus();
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text('Gagal: $e')));
      }
    } finally {
      if (mounted) setState(() => _toggling = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Trading'),
        actions: [_wsDot(), const SizedBox(width: 12)],
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : RefreshIndicator(
              onRefresh: _loadAll,
              child: ListView(
                padding: const EdgeInsets.all(14),
                children: [
                  if (_error != null) _errorBanner(),
                  _botControlCard(),
                  const SizedBox(height: 12),
                  _execModeCard(),
                  const SizedBox(height: 12),
                  _entrySettingsCard(),
                  const SizedBox(height: 12),
                  _accountCard(),
                  const SizedBox(height: 12),
                  _latestSignalCard(),
                  const SizedBox(height: 12),
                  _chartCard(),
                  const SizedBox(height: 12),
                  _backtestCard(),
                  const SizedBox(height: 12),
                  _decisionsCard(),
                ],
              ),
            ),
    );
  }

  Widget _wsDot() {
    final (color, label) = switch (_wsStatus) {
      WsStatus.connected => (AppColors.green, 'Live'),
      WsStatus.connecting => (AppColors.gold, 'Menghubungkan'),
      WsStatus.disconnected => (AppColors.red, 'Terputus'),
    };
    return Row(children: [
      Container(width: 8, height: 8, decoration: BoxDecoration(color: color, shape: BoxShape.circle)),
      const SizedBox(width: 6),
      Text(label, style: TextStyle(color: color, fontSize: 12)),
    ]);
  }

  Widget _errorBanner() => Container(
        margin: const EdgeInsets.only(bottom: 12),
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          color: AppColors.redBg,
          borderRadius: BorderRadius.circular(10),
          border: Border.all(color: AppColors.red.withValues(alpha: 0.4)),
        ),
        child: Row(children: [
          const Icon(Icons.warning_amber, color: AppColors.red, size: 18),
          const SizedBox(width: 8),
          Expanded(child: Text(_error!, style: const TextStyle(color: AppColors.red, fontSize: 12))),
        ]),
      );

  Widget _card({required Widget child}) => Container(
        padding: const EdgeInsets.all(16),
        decoration: BoxDecoration(
          color: AppColors.surface,
          borderRadius: BorderRadius.circular(14),
          border: Border.all(color: AppColors.border),
        ),
        child: child,
      );

  Widget _botControlCard() {
    final running = _status?.running ?? false;
    final mt5 = _status?.mt5Connected ?? false;
    return _card(
      child: Row(
        children: [
          Container(
            width: 46,
            height: 46,
            decoration: BoxDecoration(
              color: running ? AppColors.greenBg : AppColors.surface2,
              borderRadius: BorderRadius.circular(12),
            ),
            child: Icon(running ? Icons.smart_toy : Icons.power_settings_new,
                color: running ? AppColors.green : AppColors.textSecondary),
          ),
          const SizedBox(width: 14),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(running ? 'Bot Aktif' : 'Bot Nonaktif',
                    style: const TextStyle(
                        color: AppColors.textPrimary,
                        fontWeight: FontWeight.bold,
                        fontSize: 16)),
                Text(mt5 ? 'MT5 terhubung' : 'MT5 belum terhubung',
                    style: TextStyle(
                        color: mt5 ? AppColors.green : AppColors.red, fontSize: 12)),
              ],
            ),
          ),
          _toggling
              ? const SizedBox(
                  width: 24, height: 24, child: CircularProgressIndicator(strokeWidth: 2))
              : Switch(
                  value: running,
                  activeThumbColor: AppColors.green,
                  onChanged: (_) => _toggleBot(),
                ),
        ],
      ),
    );
  }

  Widget _entrySettingsCard() {
    return _card(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(children: [
            const Icon(Icons.tune, size: 16, color: AppColors.textSecondary),
            const SizedBox(width: 8),
            const Text('Pengaturan Entry',
                style: TextStyle(color: AppColors.textSecondary, fontSize: 12)),
            const Spacer(),
            if (_savingEntry)
              const SizedBox(
                  width: 14, height: 14, child: CircularProgressIndicator(strokeWidth: 2)),
          ]),
          const SizedBox(height: 12),
          _stepperRow(
            'Jumlah entry / simbol',
            '$_maxEntries',
            onMinus: _maxEntries > 1
                ? () {
                    setState(() => _maxEntries--);
                    _saveEntrySettings();
                  }
                : null,
            onPlus: _maxEntries < 10
                ? () {
                    setState(() => _maxEntries++);
                    _saveEntrySettings();
                  }
                : null,
          ),
          const SizedBox(height: 10),
          _stepperRow(
            'Risk % / entry',
            '${_riskPct.toStringAsFixed(2)}%',
            onMinus: _riskPct > 0.1
                ? () {
                    setState(() =>
                        _riskPct = (_riskPct - 0.1).clamp(0.1, 5.0).toDouble());
                    _saveEntrySettings();
                  }
                : null,
            onPlus: _riskPct < 5.0
                ? () {
                    setState(() =>
                        _riskPct = (_riskPct + 0.1).clamp(0.1, 5.0).toDouble());
                    _saveEntrySettings();
                  }
                : null,
          ),
          const SizedBox(height: 8),
          Text(
            _maxEntries <= 1
                ? 'Satu entry per simbol. Naikkan untuk entry bertahap.'
                : 'Hingga $_maxEntries entry bertahap — entry berikutnya hanya '
                    'ditambah saat harga bergerak menguntungkan (pyramiding), '
                    'tiap entry berisiko ${_riskPct.toStringAsFixed(2)}%.',
            style: const TextStyle(color: AppColors.textSecondary, fontSize: 11),
          ),
          const Divider(height: 22, color: AppColors.border),
          const Text('Ambang sinyal',
              style: TextStyle(color: AppColors.textSecondary, fontSize: 11)),
          const SizedBox(height: 8),
          _stepperRow(
            'Kualitas minimum',
            '${_minConf.toStringAsFixed(0)}%',
            onMinus: _minConf > 50
                ? () {
                    setState(() =>
                        _minConf = (_minConf - 5).clamp(50.0, 95.0).toDouble());
                    _saveEntrySettings();
                  }
                : null,
            onPlus: _minConf < 95
                ? () {
                    setState(() =>
                        _minConf = (_minConf + 5).clamp(50.0, 95.0).toDouble());
                    _saveEntrySettings();
                  }
                : null,
          ),
          const SizedBox(height: 8),
          Text(
            _minConfNote(),
            style: const TextStyle(color: AppColors.textSecondary, fontSize: 11),
          ),
          const Divider(height: 22, color: AppColors.border),
          const Text('Cara keluar posisi',
              style: TextStyle(color: AppColors.textSecondary, fontSize: 11)),
          _toggleRow(
            'Tutup saat sinyal NETRAL',
            'Keluar saat keyakinan otak hilang, sebelum SL/TP. Matikan agar '
                'posisi berjalan sampai SL/TP/trailing.',
            _closeOnNeutral,
            (v) {
              setState(() => _closeOnNeutral = v);
              _saveEntrySettings();
            },
          ),
          _toggleRow(
            'Tutup saat sinyal berbalik arah',
            'Keluar saat arah otak berbalik (BELI↔JUAL).',
            _closeOnFlip,
            (v) {
              setState(() => _closeOnFlip = v);
              _saveEntrySettings();
            },
          ),
        ],
      ),
    );
  }

  /// Penjelasan ambang kualitas — sengaja JUJUR, termasuk saat menaikkannya
  /// tidak menguntungkan.
  ///
  /// Skor kualitas = 50 + 50 x rata-rata skor gerbang, jadi setup yang lolos
  /// SELALU >= 50 dan "50%" berarti tanpa saringan tambahan.
  ///
  /// Yang terukur (emas D1, SL/TP ditelusuri bar demi bar): skor kualitas TIDAK
  /// memprediksi hasil. Menaikkan ambang di scalping justru memperburuk
  /// ekspektansi (50%: +0.31R -> 70%: +0.14R -> 75%: -0.05R) sambil memangkas
  /// 80% peluang. Di swing skor selalu 76-98, jadi ambang di bawah 75 tak
  /// berefek sama sekali. Sengaja tidak disembunyikan: knob yang tampak berguna
  /// padahal merugikan itu lebih berbahaya daripada tidak ada knob.
  String _minConfNote() {
    final swing = _tradingMode == 'swing';
    if (_minConf <= 50) {
      return 'Semua setup yang lolos gerbang diterima. Skor kualitas = 50 + '
          '50 x rata-rata skor gerbang, jadi setup yang lolos selalu >= 50% — '
          'ini setelan tanpa saringan tambahan, dan yang terbaik menurut uji.';
    }
    if (swing) {
      return _minConf < 75
          ? 'Di mode swing skor kualitas hampir selalu 76-98%, jadi ambang '
              '${_minConf.toStringAsFixed(0)}% praktis TIDAK menyaring apa pun.'
          : 'Menyaring sedikit setup swing. Perlu diketahui: pada uji, skor '
              'kualitas tidak memprediksi hasil — menaikkan ambang hanya '
              'mengurangi peluang tanpa memperbaiki ekspektansi.';
    }
    if (_minConf >= 75) {
      return 'PERINGATAN: pada uji, ambang ${_minConf.toStringAsFixed(0)}% di '
          'mode scalping membuang ~80% peluang dan ekspektansinya berubah '
          'NEGATIF (-0.05R vs +0.31R di 50%). Skor tinggi bukan berarti '
          'peluang lebih baik.';
    }
    return 'Menyaring setup scalping berskor rendah. Tapi pada uji hal ini '
        'MENURUNKAN hasil, bukan menaikkan: 60% -> +0.25R dan 70% -> +0.14R, '
        'dibanding +0.31R di 50%. Naikkan hanya bila kamu ingin lebih sedikit '
        'transaksi, bukan untuk mengejar kualitas.';
  }

  Widget _toggleRow(String label, String desc, bool value,
      ValueChanged<bool> onChanged) {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(label,
                  style: const TextStyle(color: AppColors.textPrimary, fontSize: 14)),
              const SizedBox(height: 2),
              Text(desc,
                  style: const TextStyle(color: AppColors.textSecondary, fontSize: 11)),
            ],
          ),
        ),
        Switch(
          value: value,
          activeThumbColor: AppColors.gold,
          onChanged: _savingEntry ? null : onChanged,
        ),
      ],
    );
  }

  Widget _stepperRow(String label, String value,
      {VoidCallback? onMinus, VoidCallback? onPlus}) {
    return Row(children: [
      Expanded(
          child: Text(label,
              style: const TextStyle(color: AppColors.textPrimary, fontSize: 14))),
      _stepBtn(Icons.remove, onMinus),
      Container(
        width: 76,
        alignment: Alignment.center,
        child: Text(value,
            style: const TextStyle(
                color: AppColors.gold, fontWeight: FontWeight.bold, fontSize: 15)),
      ),
      _stepBtn(Icons.add, onPlus),
    ]);
  }

  Widget _stepBtn(IconData icon, VoidCallback? onTap) {
    final on = onTap != null;
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(8),
      child: Container(
        width: 34,
        height: 34,
        decoration: BoxDecoration(
          color: on ? AppColors.goldBg : AppColors.surface2,
          borderRadius: BorderRadius.circular(8),
          border: Border.all(color: on ? AppColors.gold : AppColors.border),
        ),
        child: Icon(icon,
            size: 18, color: on ? AppColors.gold : AppColors.textSecondary),
      ),
    );
  }

  Widget _accountCard() {
    final acc = _status?.account ?? AccountInfo();
    final plColor = acc.profit >= 0 ? AppColors.green : AppColors.red;
    return _card(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(children: [
            const Text('Akun MT5',
                style: TextStyle(color: AppColors.textSecondary, fontSize: 12)),
            const Spacer(),
            if (acc.login != 0)
              Text('#${acc.login} · ${acc.currency}',
                  style: const TextStyle(color: AppColors.textSecondary, fontSize: 11)),
          ]),
          const SizedBox(height: 10),
          Row(
            children: [
              _stat('Equity', acc.equity.toStringAsFixed(2), AppColors.textPrimary),
              _stat('Balance', acc.balance.toStringAsFixed(2), AppColors.textPrimary),
              _stat('Floating P/L',
                  '${acc.profit >= 0 ? '+' : ''}${acc.profit.toStringAsFixed(2)}', plColor),
            ],
          ),
          const SizedBox(height: 10),
          Row(
            children: [
              _stat('Margin', acc.margin.toStringAsFixed(2), AppColors.textSecondary),
              _stat('Free Margin', acc.freeMargin.toStringAsFixed(2), AppColors.textSecondary),
              const Expanded(child: SizedBox()),
            ],
          ),
        ],
      ),
    );
  }

  Widget _stat(String k, String v, Color c) => Expanded(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(k, style: const TextStyle(color: AppColors.textSecondary, fontSize: 11)),
            const SizedBox(height: 2),
            Text(v, style: TextStyle(color: c, fontSize: 16, fontWeight: FontWeight.bold)),
          ],
        ),
      );

  Widget _latestSignalCard() {
    final s = _signals.isNotEmpty ? _signals.first : null;
    final raw = s?.rawSignal ?? 'NETRAL';
    final color = raw.signalColor;
    return _card(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(children: [
            Text('Sinyal FuLens (otak) · $_tf',
                style: const TextStyle(color: AppColors.textSecondary, fontSize: 12)),
            const Spacer(),
            if (s != null && s.executed)
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                decoration: BoxDecoration(
                    color: AppColors.greenBg, borderRadius: BorderRadius.circular(6)),
                child: const Text('DIEKSEKUSI',
                    style: TextStyle(color: AppColors.green, fontSize: 10)),
              ),
          ]),
          const SizedBox(height: 8),
          Row(children: [
            Text('${raw.signalIcon} $raw',
                style: TextStyle(color: color, fontSize: 22, fontWeight: FontWeight.bold)),
            const Spacer(),
            if (s != null)
              Text('Confidence ${s.confidence.toStringAsFixed(0)}%',
                  style: const TextStyle(color: AppColors.textSecondary, fontSize: 12)),
          ]),
          if (s != null && s.reasons.isNotEmpty) ...[
            const SizedBox(height: 10),
            ...s.reasons.take(4).map((r) => Padding(
                  padding: const EdgeInsets.only(bottom: 4),
                  child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    const Text('• ', style: TextStyle(color: AppColors.gold)),
                    Expanded(
                        child: Text(r,
                            style: const TextStyle(
                                color: AppColors.textSecondary, fontSize: 12))),
                  ]),
                )),
          ],
        ],
      ),
    );
  }

  Widget _chartCard() => _card(
        child: FibonacciChart(
          candles: _candles,
          currentPrice: _currentPrice,
          title: '${SymbolState.instance.symbol} · $_tf — Live + Fibonacci',
        ),
      );

  Widget _execModeCard() {
    final swing = _tradingMode == 'swing';
    Widget opt(String mode, String label, String desc, IconData icon) {
      final active = _tradingMode == mode;
      return Expanded(
        child: InkWell(
          onTap: _savingMode ? null : () => _setTradingMode(mode),
          borderRadius: BorderRadius.circular(10),
          child: Container(
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: active ? AppColors.goldBg : AppColors.surface2,
              borderRadius: BorderRadius.circular(10),
              border: Border.all(
                  color: active ? AppColors.gold : AppColors.border),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Icon(icon, size: 18,
                    color: active ? AppColors.gold : AppColors.textSecondary),
                const SizedBox(height: 6),
                Text(label,
                    style: TextStyle(
                        color: active ? AppColors.gold : AppColors.textPrimary,
                        fontWeight: FontWeight.bold,
                        fontSize: 13)),
                const SizedBox(height: 2),
                Text(desc,
                    style: const TextStyle(
                        color: AppColors.textSecondary, fontSize: 10)),
              ],
            ),
          ),
        ),
      );
    }

    return _card(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(children: [
            const Text('Mode Kerja Otak',
                style: TextStyle(color: AppColors.textSecondary, fontSize: 12)),
            const Spacer(),
            if (_savingMode)
              const SizedBox(
                  width: 14, height: 14, child: CircularProgressIndicator(strokeWidth: 2)),
          ]),
          const SizedBox(height: 10),
          Row(children: [
            opt('swing', 'Swing', 'Stoch + MACD cross + S&R', Icons.show_chart),
            const SizedBox(width: 10),
            opt('scalping', 'Scalping', 'Stoch + MACD searah', Icons.bolt),
          ]),
          const SizedBox(height: 8),
          Text(
            swing
                ? 'Swing: Stochastic cross → MACD cross baru → sentuh Major S&R '
                  '→ dicek ruang Bollinger. Lebih ketat, entry lebih jarang.'
                : 'Scalping: Stochastic cross → MACD searah → dicek ruang '
                  'Bollinger. Tanpa syarat S&R, entry lebih sering.',
            style: const TextStyle(color: AppColors.textSecondary, fontSize: 11),
          ),
          const SizedBox(height: 6),
          const Text(
            'Mode berlaku untuk SEMUA simbol. Simbol yang ditradingkan '
            'ditentukan chart tempat EA dipasang.',
            style: TextStyle(color: AppColors.textSecondary, fontSize: 10),
          ),

          const Divider(height: 22, color: AppColors.border),
          // Timeframe EKSEKUSI. EA mendorong data semua timeframe (supaya layar
          // analisis memakai harga broker asli), tapi hanya SATU yang ditradingkan.
          Row(children: [
            const Icon(Icons.timelapse, size: 16, color: AppColors.textSecondary),
            const SizedBox(width: 8),
            const Text('Timeframe Eksekusi',
                style: TextStyle(color: AppColors.textSecondary, fontSize: 12)),
          ]),
          const SizedBox(height: 8),
          Wrap(
            spacing: 6,
            runSpacing: 6,
            children: [
              for (final tf in SymbolState.instance.timeframes)
                InkWell(
                  onTap: _savingMode ? null : () => _setExecTimeframe(tf),
                  borderRadius: BorderRadius.circular(8),
                  child: Container(
                    padding: const EdgeInsets.symmetric(
                        horizontal: 12, vertical: 6),
                    decoration: BoxDecoration(
                      color: _execTf == tf ? AppColors.goldBg : AppColors.surface2,
                      borderRadius: BorderRadius.circular(8),
                      border: Border.all(
                          color: _execTf == tf
                              ? AppColors.gold
                              : AppColors.border),
                    ),
                    child: Text(tf,
                        style: TextStyle(
                            fontSize: 12,
                            fontWeight: _execTf == tf
                                ? FontWeight.bold
                                : FontWeight.normal,
                            color: _execTf == tf
                                ? AppColors.gold
                                : AppColors.textSecondary)),
                  ),
                ),
            ],
          ),
          const SizedBox(height: 6),
          Text(
            'Bot hanya entry di $_execTf. EA tetap mengirim data semua timeframe, '
            'jadi layar analisis memakai harga broker asli — bukan yfinance.',
            style: const TextStyle(color: AppColors.textSecondary, fontSize: 10),
          ),
          const Divider(height: 22, color: AppColors.border),
          // Yang BENAR-BENAR ditradingkan bot — dilaporkan EA, bukan selektor
          // timeframe aplikasi. Teks lama ("Bot mengikuti timeframe $_tf")
          // menyesatkan: selektor itu cuma mengubah apa yang DILIHAT.
          Row(children: [
            const Icon(Icons.memory, size: 16, color: AppColors.textSecondary),
            const SizedBox(width: 8),
            const Text('Dikerjakan Bot (dari EA)',
                style: TextStyle(color: AppColors.textSecondary, fontSize: 12)),
            const Spacer(),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
              decoration: BoxDecoration(
                  color: AppColors.goldBg, borderRadius: BorderRadius.circular(8)),
              child: Text(
                  (_status?.eaSymbol.isNotEmpty ?? false)
                      ? '${_status!.eaSymbol} · ${_status!.eaTimeframe}'
                      : 'menunggu EA…',
                  style: const TextStyle(
                      color: AppColors.gold, fontWeight: FontWeight.bold)),
            ),
          ]),
          const SizedBox(height: 6),
          if (_botTfMismatch) ...[
            Container(
              padding: const EdgeInsets.all(10),
              decoration: BoxDecoration(
                color: AppColors.red.withValues(alpha: 0.08),
                borderRadius: BorderRadius.circular(8),
                border: Border.all(color: AppColors.red.withValues(alpha: 0.3)),
              ),
              child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                const Icon(Icons.warning_amber_rounded,
                    size: 15, color: AppColors.red),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    'Kamu sedang melihat ${SymbolState.instance.symbol} · $_tf, '
                    'tapi bot entry di ${_status!.eaSymbol} · '
                    '${_status!.eaTimeframe}. Gerbang di layar analisis TIDAK '
                    'menggambarkan keputusan bot. Samakan lewat "Timeframe '
                    'Eksekusi" di atas, atau ubah pilihan di bar atas.',
                    style: const TextStyle(
                        color: AppColors.red, fontSize: 11, height: 1.35),
                  ),
                ),
              ]),
            ),
          ] else
            Text(
              'Timeframe & simbol bot ditentukan input SignalTF pada EA di chart. '
              'Selektor di bar atas hanya mengubah tampilan.',
              style: const TextStyle(color: AppColors.textSecondary, fontSize: 11),
            ),
        ],
      ),
    );
  }

  /// True bila yang sedang dilihat berbeda dari yang dikerjakan bot.
  bool get _botTfMismatch {
    final s = _status;
    if (s == null || s.eaSymbol.isEmpty) return false;
    return s.eaSymbol.toUpperCase() !=
            SymbolState.instance.symbol.toUpperCase() ||
        s.eaTimeframe.toUpperCase() != _tf.toUpperCase();
  }

  Widget _backtestCard() {
    final b = _backtest;
    return _card(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(children: [
            const Text('Backtest (Hybrid Testing)',
                style: TextStyle(color: AppColors.textSecondary, fontSize: 12)),
            const Spacer(),
            TextButton.icon(
              onPressed: _btLoading ? null : _runBacktest,
              icon: _btLoading
                  ? const SizedBox(
                      width: 14, height: 14, child: CircularProgressIndicator(strokeWidth: 2))
                  : const Icon(Icons.play_arrow, size: 16),
              label: Text(_btLoading ? 'Menghitung…' : 'Jalankan'),
              style: TextButton.styleFrom(foregroundColor: AppColors.gold),
            ),
          ]),
          if (b == null)
            const Padding(
              padding: EdgeInsets.symmetric(vertical: 8),
              child: Text('Jalankan backtest untuk menilai kualitas sinyal simbol ini.',
                  style: TextStyle(color: AppColors.textSecondary, fontSize: 12)),
            )
          else ...[
            const SizedBox(height: 4),
            Row(children: [
              _btStat('Return', '${b.totalReturnPct >= 0 ? '+' : ''}${b.totalReturnPct}%',
                  b.totalReturnPct >= 0 ? AppColors.green : AppColors.red),
              _btStat('Buy&Hold', '${b.buyHoldPct >= 0 ? '+' : ''}${b.buyHoldPct}%',
                  AppColors.textSecondary),
              _btStat('Win Rate', '${b.winRate}%', AppColors.textPrimary),
            ]),
            const SizedBox(height: 10),
            Row(children: [
              _btStat('Trade', '${b.trades}', AppColors.textPrimary),
              _btStat('Profit Factor', '${b.profitFactor}', AppColors.textPrimary),
              _btStat('Max DD', '${b.maxDrawdownPct}%', AppColors.red),
            ]),
            const SizedBox(height: 12),
            SizedBox(height: 140, child: _equityChart(b)),
            const SizedBox(height: 6),
            Text(b.note, style: const TextStyle(color: AppColors.textSecondary, fontSize: 10)),
          ],
        ],
      ),
    );
  }

  Widget _btStat(String k, String v, Color c) => Expanded(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(k, style: const TextStyle(color: AppColors.textSecondary, fontSize: 10)),
            const SizedBox(height: 2),
            Text(v, style: TextStyle(color: c, fontSize: 15, fontWeight: FontWeight.bold)),
          ],
        ),
      );

  Widget _equityChart(BacktestResult b) => SfCartesianChart(
        plotAreaBorderWidth: 0,
        primaryXAxis: CategoryAxis(isVisible: false),
        primaryYAxis: NumericAxis(
          axisLine: const AxisLine(width: 0),
          majorTickLines: const MajorTickLines(size: 0),
          labelStyle: const TextStyle(fontSize: 9, color: AppColors.textSecondary),
        ),
        series: <CartesianSeries<BacktestPoint, String>>[
          AreaSeries<BacktestPoint, String>(
            dataSource: b.equityCurve,
            xValueMapper: (p, _) => p.date,
            yValueMapper: (p, _) => p.equity,
            color: AppColors.gold.withValues(alpha: 0.18),
            borderColor: AppColors.gold,
            borderWidth: 1.5,
          ),
        ],
      );

  Widget _decisionsCard() => _card(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text('Log Keputusan Bot',
                style: TextStyle(color: AppColors.textSecondary, fontSize: 12)),
            const SizedBox(height: 8),
            if (_signals.isEmpty)
              const Padding(
                padding: EdgeInsets.symmetric(vertical: 12),
                child: Text('Belum ada keputusan',
                    style: TextStyle(color: AppColors.textSecondary)),
              )
            else
              ..._signals.take(12).map(_signalRow),
          ],
        ),
      );

  Widget _signalRow(BotSignal s) {
    final color = s.rawSignal.signalColor;
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: Row(
        children: [
          Container(width: 6, height: 6, decoration: BoxDecoration(color: color, shape: BoxShape.circle)),
          const SizedBox(width: 8),
          Expanded(
            child: Text('${s.symbol} · ${s.rawSignal}',
                style: const TextStyle(color: AppColors.textPrimary, fontSize: 13)),
          ),
          if (s.executed)
            const Icon(Icons.check_circle, color: AppColors.green, size: 14)
          else
            Text('${s.confidence.toStringAsFixed(0)}%',
                style: const TextStyle(color: AppColors.textSecondary, fontSize: 11)),
        ],
      ),
    );
  }
}
