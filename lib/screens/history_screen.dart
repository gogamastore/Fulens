// lib/screens/history_screen.dart
import 'package:flutter/material.dart';
import 'package:fl_chart/fl_chart.dart';
import '../core/theme.dart';
import '../services/api_service.dart';
import '../widgets/common_widgets.dart';

class HistoryScreen extends StatefulWidget {
  const HistoryScreen({super.key});
  @override
  State<HistoryScreen> createState() => _HistoryScreenState();
}

class _HistoryScreenState extends State<HistoryScreen> {
  final _api = ApiService();
  List<OhlcData> _history = [];
  bool _loading = true;
  String? _error;
  int _days = 30;

  @override
  void initState() { super.initState(); _load(); }

  Future<void> _load() async {
    setState(() { _loading = true; _error = null; });
    try {
      final d = await _api.getHistory(days: _days);
      setState(() { _history = d.reversed.toList(); _loading = false; });
    } catch (e) {
      setState(() { _loading = false; _error = e.toString().replaceAll('Exception: ', ''); });
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(
      title: const Text('Riwayat Harga'),
      actions: [
        DropdownButton<int>(
          value: _days,
          dropdownColor: AppColors.surface,
          underline: const SizedBox(),
          style: const TextStyle(color: AppColors.gold, fontSize: 13),
          items: [30, 60, 90, 180, 365]
              .map((d) => DropdownMenuItem(value: d, child: Text('$d Hari')))
              .toList(),
          onChanged: (v) {
            if (v != null) {
              setState(() => _days = v);
              _load();
            }
          },
        ),
        const SizedBox(width: 8),
        IconButton(
          icon: const Icon(Icons.refresh),
          onPressed: _load,
          color: AppColors.gold,
        ),
      ],
    ),
    body: _error != null
      ? Padding(
          padding: const EdgeInsets.all(16),
          child: ErrorCard(message: _error!, onRetry: _load))
      : _loading
      ? _shimmer()
      : Column(children: [
          // Chart mini
          if (_history.isNotEmpty)
            Padding(
              padding: const EdgeInsets.all(16),
              child: AppCard(
                padding: const EdgeInsets.fromLTRB(8, 16, 16, 8),
                child: SizedBox(height: 160, child: LineChart(_buildChart())),
              ),
            ),

          // Table header
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16),
            child: Row(children: [
              SizedBox(
                width: 90,
                child: Text('Tanggal',
                  style: const TextStyle(fontSize: 10,
                    color: AppColors.textSecondary, letterSpacing: 1)),
              ),
              Expanded(child: Text('Close',
                textAlign: TextAlign.right,
                style: const TextStyle(fontSize: 10, color: AppColors.textSecondary))),
              Expanded(child: Text('High',
                textAlign: TextAlign.right,
                style: const TextStyle(fontSize: 10, color: AppColors.textSecondary))),
              Expanded(child: Text('Low',
                textAlign: TextAlign.right,
                style: const TextStyle(fontSize: 10, color: AppColors.textSecondary))),
              Expanded(child: Text('Δ%',
                textAlign: TextAlign.right,
                style: const TextStyle(fontSize: 10, color: AppColors.textSecondary))),
            ]),
          ),
          const Divider(color: AppColors.border),

          // List
          Expanded(
            child: ListView.separated(
              padding: const EdgeInsets.symmetric(horizontal: 16),
              itemCount: _history.length,
              separatorBuilder: (_, __) =>
                  const Divider(height: 1, color: AppColors.border),
              itemBuilder: (_, i) {
                final d = _history[i];
                final prev = i < _history.length - 1 ? _history[i + 1] : null;
                final chgPct = prev != null
                    ? (d.close - prev.close) / prev.close * 100
                    : 0.0;
                final isUp = chgPct >= 0;
                return Padding(
                  padding: const EdgeInsets.symmetric(vertical: 8),
                  child: Row(children: [
                    SizedBox(
                      width: 90,
                      child: Text(
                        d.date.length >= 7 ? d.date.substring(5) : d.date,
                        style: const TextStyle(
                            fontSize: 12, color: AppColors.textSecondary),
                      ),
                    ),
                    Expanded(
                      child: Text(
                        '\$${d.close.toStringAsFixed(2)}',
                        textAlign: TextAlign.right,
                        style: const TextStyle(
                            fontSize: 12,
                            fontWeight: FontWeight.w600,
                            fontFamily: 'SpaceMono'),
                      ),
                    ),
                    Expanded(
                      child: Text(
                        '\$${d.high.toStringAsFixed(0)}',
                        textAlign: TextAlign.right,
                        style: const TextStyle(
                            fontSize: 12,
                            color: AppColors.green,
                            fontFamily: 'SpaceMono'),
                      ),
                    ),
                    Expanded(
                      child: Text(
                        '\$${d.low.toStringAsFixed(0)}',
                        textAlign: TextAlign.right,
                        style: const TextStyle(
                            fontSize: 12,
                            color: AppColors.red,
                            fontFamily: 'SpaceMono'),
                      ),
                    ),
                    Expanded(
                      child: Text(
                        '${isUp ? '+' : ''}${chgPct.toStringAsFixed(2)}%',
                        textAlign: TextAlign.right,
                        style: TextStyle(
                            fontSize: 12,
                            color: isUp ? AppColors.green : AppColors.red),
                      ),
                    ),
                  ]),
                );
              },
            ),
          ),
        ]),
  );

  LineChartData _buildChart() {
    final reversed = _history.reversed.toList();
    final spots = reversed
        .asMap()
        .entries
        .map((e) => FlSpot(e.key.toDouble(), e.value.close))
        .toList();
    final prices = reversed.map((e) => e.close).toList();
    final minY = prices.reduce((a, b) => a < b ? a : b);
    final maxY = prices.reduce((a, b) => a > b ? a : b);
    final range = maxY - minY;

    return LineChartData(
      gridData: const FlGridData(show: false),
      titlesData: const FlTitlesData(
        leftTitles: AxisTitles(sideTitles: SideTitles(showTitles: false)),
        bottomTitles: AxisTitles(sideTitles: SideTitles(showTitles: false)),
        topTitles: AxisTitles(sideTitles: SideTitles(showTitles: false)),
        rightTitles: AxisTitles(sideTitles: SideTitles(showTitles: false)),
      ),
      borderData: FlBorderData(show: false),
      lineBarsData: [
        LineChartBarData(
          spots: spots,
          isCurved: true,
          color: AppColors.gold,
          barWidth: 2,
          dotData: const FlDotData(show: false),
          belowBarData: BarAreaData(
            show: true,
            color: AppColors.gold.withOpacity(0.08),
          ),
        ),
      ],
      minY: minY - range * 0.05,
      maxY: maxY + range * 0.05,
    );
  }

  Widget _shimmer() => ListView(
    padding: const EdgeInsets.all(16),
    children: const [
      ShimmerCard(height: 160),
      SizedBox(height: 10),
      ShimmerCard(height: 400),
    ],
  );
}
