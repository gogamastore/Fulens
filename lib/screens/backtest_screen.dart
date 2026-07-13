// lib/screens/backtest_screen.dart
import 'package:flutter/material.dart';
import 'package:syncfusion_flutter_charts/charts.dart';
import '../core/theme.dart';
import '../services/api_service.dart';
import '../state/symbol_state.dart';

/// Halaman backtest (hybrid testing). Simbol & timeframe mengikuti pilihan
/// GLOBAL di bar atas; di sini Anda memilih rentang tanggal & strategi (TA/ML).
class BacktestScreen extends StatefulWidget {
  const BacktestScreen({super.key});

  @override
  State<BacktestScreen> createState() => _BacktestScreenState();
}

class _BacktestScreenState extends State<BacktestScreen> {
  final _api = ApiService();

  String _strategy = 'ta';
  DateTime? _start;
  DateTime? _end;

  BacktestResult? _result;
  bool _loading = false;
  String? _error;

  String get _symbol => SymbolState.instance.symbol;
  String get _tf => SymbolState.instance.timeframe;

  String _fmt(DateTime d) =>
      '${d.year}-${d.month.toString().padLeft(2, '0')}-${d.day.toString().padLeft(2, '0')}';

  // Batas histori Yahoo per timeframe: M15/M30 ~60 hari, H1/H4 ~730 hari, D1/W1 bertahun.
  DateTime _minDate() {
    final now = DateTime.now();
    switch (_tf) {
      case 'M15':
      case 'M30':
        return now.subtract(const Duration(days: 60));
      case 'H1':
      case 'H4':
        return now.subtract(const Duration(days: 720));
      default:
        return DateTime(2010);
    }
  }

  String _tfHint() {
    switch (_tf) {
      case 'M15':
      case 'M30':
        return 'Intraday $_tf: Yahoo hanya sediakan ~60 hari terakhir.';
      case 'H1':
      case 'H4':
        return 'Intraday $_tf: histori hingga ~730 hari terakhir.';
      default:
        return 'Timeframe $_tf: histori bertahun-tahun tersedia.';
    }
  }

  Future<void> _pickDate(bool isStart) async {
    final now = DateTime.now();
    final min = _minDate();
    final init = (isStart ? _start : _end) ?? now;
    final picked = await showDatePicker(
      context: context,
      initialDate: init.isBefore(min) ? min : init,
      firstDate: min,
      lastDate: now,
    );
    if (picked != null) {
      setState(() => isStart ? _start = picked : _end = picked);
    }
  }

  Future<void> _run() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final r = await _api.getBacktest(
        strategy: _strategy,
        start: _start != null ? _fmt(_start!) : null,
        end: _end != null ? _fmt(_end!) : null,
      );
      if (mounted) setState(() => _result = r);
    } catch (e) {
      if (mounted) setState(() => _error = '$e');
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Backtest')),
      body: ListView(
        padding: const EdgeInsets.all(14),
        children: [
          _card(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                // Konteks global (read-only)
                Row(children: [
                  const Icon(Icons.tag, size: 16, color: AppColors.gold),
                  const SizedBox(width: 6),
                  Text('$_symbol · $_tf',
                      style: const TextStyle(
                          color: AppColors.textPrimary,
                          fontWeight: FontWeight.bold,
                          fontSize: 15)),
                  const Spacer(),
                  const Text('atur dari bar atas',
                      style: TextStyle(color: AppColors.textSecondary, fontSize: 10)),
                ]),
                const Divider(height: 22, color: AppColors.border),
                // Rentang tanggal
                const Text('Rentang tanggal',
                    style: TextStyle(color: AppColors.textSecondary, fontSize: 11)),
                const SizedBox(height: 6),
                Row(children: [
                  Expanded(child: _dateField('Dari', _start, () => _pickDate(true))),
                  const SizedBox(width: 12),
                  Expanded(child: _dateField('Sampai', _end, () => _pickDate(false))),
                ]),
                const SizedBox(height: 6),
                Row(children: [
                  const Icon(Icons.info_outline, size: 12, color: AppColors.textSecondary),
                  const SizedBox(width: 4),
                  Expanded(
                    child: Text(_tfHint(),
                        style: const TextStyle(
                            color: AppColors.textSecondary, fontSize: 10)),
                  ),
                ]),
                if (_start != null || _end != null)
                  Align(
                    alignment: Alignment.centerRight,
                    child: TextButton(
                      onPressed: () => setState(() {
                        _start = null;
                        _end = null;
                      }),
                      child: const Text('Reset (pakai 1 tahun terakhir)'),
                    ),
                  ),
                const SizedBox(height: 10),
                // Strategi
                const Text('Strategi',
                    style: TextStyle(color: AppColors.textSecondary, fontSize: 11)),
                const SizedBox(height: 6),
                Row(children: [
                  _stratChip('ta', 'Teknikal'),
                  const SizedBox(width: 8),
                  _stratChip('ml', 'ML (XGBoost)'),
                ]),
                const SizedBox(height: 14),
                SizedBox(
                  width: double.infinity,
                  child: FilledButton.icon(
                    onPressed: _loading ? null : _run,
                    icon: _loading
                        ? const SizedBox(
                            width: 16, height: 16,
                            child: CircularProgressIndicator(strokeWidth: 2))
                        : const Icon(Icons.play_arrow),
                    label: Text(_loading ? 'Menghitung…' : 'Jalankan Backtest'),
                  ),
                ),
              ],
            ),
          ),
          if (_error != null) ...[
            const SizedBox(height: 12),
            _card(child: Text(_error!,
                style: const TextStyle(color: AppColors.red, fontSize: 12))),
          ],
          if (_result != null) ...[
            const SizedBox(height: 12),
            _resultCard(_result!),
          ],
        ],
      ),
    );
  }

  Widget _card({required Widget child}) => Container(
        padding: const EdgeInsets.all(16),
        decoration: BoxDecoration(
          color: AppColors.surface,
          borderRadius: BorderRadius.circular(14),
          border: Border.all(color: AppColors.border),
        ),
        child: child,
      );

  Widget _dateField(String label, DateTime? value, VoidCallback onTap) => Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(label, style: const TextStyle(color: AppColors.textSecondary, fontSize: 11)),
          const SizedBox(height: 2),
          InkWell(
            onTap: onTap,
            borderRadius: BorderRadius.circular(8),
            child: Container(
              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 10),
              decoration: BoxDecoration(
                color: AppColors.surface2,
                borderRadius: BorderRadius.circular(8),
                border: Border.all(color: AppColors.border),
              ),
              child: Row(children: [
                const Icon(Icons.calendar_today, size: 14, color: AppColors.textSecondary),
                const SizedBox(width: 8),
                Text(value != null ? _fmt(value) : '—',
                    style: const TextStyle(color: AppColors.textPrimary, fontSize: 13)),
              ]),
            ),
          ),
        ],
      );

  Widget _stratChip(String value, String label) {
    final active = _strategy == value;
    return Expanded(
      child: InkWell(
        onTap: () => setState(() => _strategy = value),
        borderRadius: BorderRadius.circular(8),
        child: Container(
          padding: const EdgeInsets.symmetric(vertical: 10),
          alignment: Alignment.center,
          decoration: BoxDecoration(
            color: active ? AppColors.goldBg : AppColors.surface2,
            borderRadius: BorderRadius.circular(8),
            border: Border.all(color: active ? AppColors.gold : AppColors.border),
          ),
          child: Text(label,
              style: TextStyle(
                  color: active ? AppColors.gold : AppColors.textSecondary,
                  fontSize: 12, fontWeight: FontWeight.bold)),
        ),
      ),
    );
  }

  Widget _resultCard(BacktestResult b) {
    return _card(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(children: [
            Text('${b.symbol} · ${b.timeframe}',
                style: const TextStyle(
                    color: AppColors.textPrimary,
                    fontWeight: FontWeight.bold,
                    fontSize: 15)),
            const SizedBox(width: 8),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
              decoration: BoxDecoration(
                  color: AppColors.blueBg, borderRadius: BorderRadius.circular(6)),
              child: Text(b.strategy.toUpperCase(),
                  style: const TextStyle(color: AppColors.blue, fontSize: 10)),
            ),
            const Spacer(),
            if (b.mlTestAccuracy != null)
              Text('Akurasi ML ${(b.mlTestAccuracy! * 100).toStringAsFixed(1)}%',
                  style: const TextStyle(color: AppColors.textSecondary, fontSize: 11)),
          ]),
          if (b.start != null && b.end != null) ...[
            const SizedBox(height: 4),
            Text('${b.start!.split(' ').first} → ${b.end!.split(' ').first}  ·  ${b.bars} bar',
                style: const TextStyle(color: AppColors.textSecondary, fontSize: 11)),
          ],
          const SizedBox(height: 12),
          Row(children: [
            _stat('Return', '${b.totalReturnPct >= 0 ? '+' : ''}${b.totalReturnPct}%',
                b.totalReturnPct >= 0 ? AppColors.green : AppColors.red),
            _stat('Buy & Hold', '${b.buyHoldPct >= 0 ? '+' : ''}${b.buyHoldPct}%',
                AppColors.textSecondary),
            _stat('Win Rate', '${b.winRate}%', AppColors.textPrimary),
          ]),
          const SizedBox(height: 12),
          Row(children: [
            _stat('Trade', '${b.trades}', AppColors.textPrimary),
            _stat('Profit Factor', '${b.profitFactor}', AppColors.textPrimary),
            _stat('Max DD', '${b.maxDrawdownPct}%', AppColors.red),
          ]),
          const SizedBox(height: 16),
          SizedBox(height: 200, child: _equityChart(b)),
          const SizedBox(height: 8),
          Text(b.note,
              style: const TextStyle(color: AppColors.textSecondary, fontSize: 10)),
        ],
      ),
    );
  }

  Widget _stat(String k, String v, Color c) => Expanded(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(k, style: const TextStyle(color: AppColors.textSecondary, fontSize: 10)),
            const SizedBox(height: 2),
            Text(v, style: TextStyle(color: c, fontSize: 16, fontWeight: FontWeight.bold)),
          ],
        ),
      );

  Widget _equityChart(BacktestResult b) => SfCartesianChart(
        plotAreaBorderWidth: 0,
        primaryXAxis: CategoryAxis(isVisible: false),
        primaryYAxis: NumericAxis(
          axisLine: const AxisLine(width: 0),
          majorTickLines: const MajorTickLines(size: 0),
          plotBands: <PlotBand>[
            PlotBand(start: 1, end: 1, borderWidth: 0.8,
                borderColor: AppColors.textSecondary, dashArray: const [4, 4]),
          ],
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
}
