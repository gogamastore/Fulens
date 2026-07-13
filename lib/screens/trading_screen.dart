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

  String _execMode = 'auto';        // 'auto' | 'selected'
  bool _savingMode = false;
  BacktestResult? _backtest;
  bool _btLoading = false;

  int _maxEntries = 1;              // jumlah entry per simbol
  double _riskPct = 0.5;           // risk % per entry
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
          _execMode = (s['execution_mode'] ?? 'auto').toString();
          _maxEntries = (s['max_positions_per_symbol'] ?? 1) as int;
          _riskPct = ((s['risk_percent'] ?? 0.5) as num).toDouble();
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

  Future<void> _setExecMode(String mode) async {
    if (_savingMode) return;
    setState(() => _savingMode = true);
    try {
      final s = await _api.getBotSettings();
      s['execution_mode'] = mode;
      s['selected_symbol'] = SymbolState.instance.symbol; // fokus simbol terpilih
      await _api.updateBotSettings(s);
      if (mounted) setState(() => _execMode = mode);
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
    final auto = _execMode == 'auto';
    Widget opt(String mode, String label, String desc, IconData icon) {
      final active = _execMode == mode;
      return Expanded(
        child: InkWell(
          onTap: _savingMode ? null : () => _setExecMode(mode),
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
            const Text('Mode Eksekusi',
                style: TextStyle(color: AppColors.textSecondary, fontSize: 12)),
            const Spacer(),
            if (_savingMode)
              const SizedBox(
                  width: 14, height: 14, child: CircularProgressIndicator(strokeWidth: 2)),
          ]),
          const SizedBox(height: 10),
          Row(children: [
            opt('auto', 'Otomatis', 'Semua simbol aktif', Icons.all_inclusive),
            const SizedBox(width: 10),
            opt('selected', 'By Selected',
                'Hanya ${SymbolState.instance.symbol}', Icons.my_location),
          ]),
          const SizedBox(height: 8),
          Text(
            auto
                ? 'Bot mengeksekusi sinyal untuk semua simbol yang dipantau.'
                : 'Bot hanya mengeksekusi simbol terpilih: ${SymbolState.instance.symbol}.',
            style: const TextStyle(color: AppColors.textSecondary, fontSize: 11),
          ),
          const Divider(height: 22, color: AppColors.border),
          Row(children: [
            const Icon(Icons.timelapse, size: 16, color: AppColors.textSecondary),
            const SizedBox(width: 8),
            const Text('Timeframe Sinyal',
                style: TextStyle(color: AppColors.textSecondary, fontSize: 12)),
            const Spacer(),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
              decoration: BoxDecoration(
                  color: AppColors.goldBg, borderRadius: BorderRadius.circular(8)),
              child: Text(_tf,
                  style: const TextStyle(
                      color: AppColors.gold, fontWeight: FontWeight.bold)),
            ),
          ]),
          Text('Bot mengikuti timeframe $_tf — ubah dari bar atas.',
              style: const TextStyle(color: AppColors.textSecondary, fontSize: 11)),
        ],
      ),
    );
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
