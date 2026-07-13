// lib/screens/prediction_screen.dart
import 'package:flutter/material.dart';
import 'package:fl_chart/fl_chart.dart';
import '../core/theme.dart';
import '../services/trading_advisor.dart';
import '../widgets/trading_advice_widget.dart';
import '../services/api_service.dart';
import '../widgets/common_widgets.dart';

class PredictionScreen extends StatefulWidget {
  const PredictionScreen({super.key});
  @override
  State<PredictionScreen> createState() => _PredictionScreenState();
}

class _PredictionScreenState extends State<PredictionScreen> {
  final _api = ApiService();
  PredictionData? _data;
  SignalData? _signal;
  IndicatorData? _indicators;
  bool _loading = true;
  String? _error;

  @override
  void initState() { super.initState(); _load(); }

  Future<void> _load() async {
    setState(() { _loading = true; _error = null; });
    try {
      final results = await Future.wait([
        _api.getPredictions(),
        _api.getSignal(),
        _api.getIndicators(),
      ]);
      setState(() {
        _data       = results[0] as PredictionData;
        _signal     = results[1] as SignalData;
        _indicators = results[2] as IndicatorData;
        _loading = false;
      });
    } catch (e) {
      setState(() { _loading = false; _error = e.toString().replaceAll('Exception: ', ''); });
    }
  }

  @override
  Widget build(BuildContext context) => DefaultTabController(
    length: 2,
    child: Scaffold(
      appBar: AppBar(
        title: const Text('Prediksi AI'),
        actions: [IconButton(icon: const Icon(Icons.refresh), onPressed: _load, color: AppColors.gold)],
        bottom: const TabBar(
          labelColor: AppColors.gold,
          unselectedLabelColor: AppColors.textSecondary,
          indicatorColor: AppColors.gold,
          tabs: [
            Tab(text: 'Proyeksi Harga'),
            Tab(text: 'Saran Trading'),
          ],
        ),
      ),
      body: _error != null
        ? Padding(padding: const EdgeInsets.all(16), child: ErrorCard(message: _error!, onRetry: _load))
        : _loading ? _shimmer()
        : TabBarView(children: [
            _buildContent(),
            _buildTradingAdvice(),
          ]),
    ),
  );

  Widget _buildContent() {
    final d = _data!;
    return ListView(padding: const EdgeInsets.all(16), children: [
      // Overall Signal
      Container(
        padding: const EdgeInsets.all(16),
        decoration: BoxDecoration(
          color: d.overallSignal.signalBgColor,
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: d.overallSignal.signalColor.withValues(alpha: 0.3)),
        ),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          const Text('SINYAL ENSEMBLE AI', style: TextStyle(fontSize: 10,
            letterSpacing: 1.5, color: AppColors.textSecondary)),
          const SizedBox(height: 6),
          Row(children: [
            Text('${d.overallSignal.signalIcon} ${d.overallSignal}',
              style: TextStyle(fontSize: 22, fontWeight: FontWeight.w700,
                color: d.overallSignal.signalColor)),
            const Spacer(),
            Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
              const Text('Harga Saat Ini', style: TextStyle(fontSize: 10, color: AppColors.textSecondary)),
              Text('\$${d.currentPrice.toStringAsFixed(2)}',
                style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700,
                  color: AppColors.gold)),
            ]),
          ]),
          const SizedBox(height: 8),
          const Text('XGBoost (40%) + LSTM (60%) Weighted Ensemble',
            style: TextStyle(fontSize: 11, color: AppColors.textSecondary)),
        ]),
      ),
      const SizedBox(height: 16),

      // Chart prediksi
      if (d.predictions.isNotEmpty) ...[
        const SectionLabel('Grafik Proyeksi Harga'),
        const SizedBox(height: 10),
        AppCard(
          padding: const EdgeInsets.fromLTRB(8, 16, 16, 8),
          child: SizedBox(height: 200, child: LineChart(_buildPredChart(d))),
        ),
        const SizedBox(height: 16),
      ],

      // Tabel prediksi
      const SectionLabel('Detail Prediksi per Horizon'),
      const SizedBox(height: 10),
      AppCard(child: Column(
        children: d.predictions.asMap().entries.map((e) {
          final p = e.value;
          return Column(children: [
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 12),
              child: Column(children: [
                Row(children: [
                  Text('${p.horizonDays} Hari',
                    style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w600)),
                  const SizedBox(width: 8),
                  Text(p.date, style: const TextStyle(fontSize: 11, color: AppColors.textSecondary)),
                  const Spacer(),
                  SignalBadge(p.signal),
                ]),
                const SizedBox(height: 8),
                Row(children: [
                  Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Text('\$${p.predictedPrice.toStringAsFixed(2)}',
                      style: TextStyle(fontSize: 20, fontWeight: FontWeight.w700,
                        color: p.signal.signalColor)),
                    Text('${p.changePct >= 0 ? '+' : ''}${p.changePct.toStringAsFixed(2)}% '
                        '(${p.changeUsd >= 0 ? '+' : ''}\$${p.changeUsd.toStringAsFixed(2)})',
                      style: TextStyle(fontSize: 12,
                        color: p.changePct >= 0 ? AppColors.green : AppColors.red)),
                  ]),
                  const Spacer(),
                  Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
                    if (p.xgbPrice != null)
                      Text('XGB: \$${p.xgbPrice!.toStringAsFixed(0)}',
                        style: const TextStyle(fontSize: 11, color: AppColors.blue)),
                    if (p.lstmPrice != null)
                      Text('LSTM: \$${p.lstmPrice!.toStringAsFixed(0)}',
                        style: const TextStyle(fontSize: 11, color: AppColors.purple)),
                    Text(p.modelAgreement ? '✓ Sepakat' : '✗ Berbeda',
                      style: TextStyle(fontSize: 10,
                        color: p.modelAgreement ? AppColors.green : AppColors.red)),
                  ]),
                ]),
                const SizedBox(height: 6),
                // Range 95%
                Row(children: [
                  const Text('Range 95%: ', style: TextStyle(fontSize: 11, color: AppColors.textSecondary)),
                  Text('\$${p.lower95.toStringAsFixed(0)} – \$${p.upper95.toStringAsFixed(0)}',
                    style: const TextStyle(fontSize: 11)),
                ]),
              ]),
            ),
            if (e.key < d.predictions.length - 1)
              const Divider(height: 1, color: AppColors.border),
          ]);
        }).toList(),
      )),
      const SizedBox(height: 16),

      // Model info
      const SectionLabel('Info Model'),
      const SizedBox(height: 10),
      AppCard(child: Column(children: [
        _modelRow('LSTM Neural Network', '60%', AppColors.purple, '90 hari lookback • time-series'),
        const Divider(height: 16, color: AppColors.border),
        _modelRow('XGBoost Gradient Boost', '40%', AppColors.blue, '104 fitur • teknikal + fundamental'),
      ])),
      const SizedBox(height: 80),
    ]);
  }

  Widget _modelRow(String name, String weight, Color color, String desc) =>
    Row(children: [
      Container(width: 4, height: 40, decoration: BoxDecoration(
        color: color, borderRadius: BorderRadius.circular(2))),
      const SizedBox(width: 12),
      Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(name, style: TextStyle(fontSize: 13, fontWeight: FontWeight.w600, color: color)),
        Text(desc, style: const TextStyle(fontSize: 11, color: AppColors.textSecondary)),
      ])),
      Text(weight, style: TextStyle(fontSize: 16, fontWeight: FontWeight.w700,
        color: color)),
    ]);

  LineChartData _buildPredChart(PredictionData d) {
    final spots = [FlSpot(0, d.currentPrice)]
      ..addAll(d.predictions.map((p) => FlSpot(p.horizonDays.toDouble(), p.predictedPrice)));
    final upperSpots = [FlSpot(0, d.currentPrice)]
      ..addAll(d.predictions.map((p) => FlSpot(p.horizonDays.toDouble(), p.upper95)));
    final lowerSpots = [FlSpot(0, d.currentPrice)]
      ..addAll(d.predictions.map((p) => FlSpot(p.horizonDays.toDouble(), p.lower95)));

    final allPrices = [...spots.map((s) => s.y), ...upperSpots.map((s) => s.y), ...lowerSpots.map((s) => s.y)];
    final minY = allPrices.reduce((a,b) => a<b?a:b);
    final maxY = allPrices.reduce((a,b) => a>b?a:b);
    final range = maxY - minY;

    return LineChartData(
      gridData: FlGridData(show: true, drawVerticalLine: false,
        getDrawingHorizontalLine: (_) => const FlLine(color: AppColors.border, strokeWidth: 1)),
      titlesData: FlTitlesData(
        leftTitles: AxisTitles(sideTitles: SideTitles(showTitles: true, reservedSize: 60,
          getTitlesWidget: (v, _) => Text('\$${v.toStringAsFixed(0)}',
            style: const TextStyle(fontSize: 9, color: AppColors.textSecondary)))),
        bottomTitles: AxisTitles(sideTitles: SideTitles(showTitles: true,
          getTitlesWidget: (v, _) => Text('${v.toInt()}H',
            style: const TextStyle(fontSize: 9, color: AppColors.textSecondary)))),
        topTitles: const AxisTitles(sideTitles: SideTitles(showTitles: false)),
        rightTitles: const AxisTitles(sideTitles: SideTitles(showTitles: false)),
      ),
      borderData: FlBorderData(show: false),
      lineBarsData: [
        LineChartBarData(spots: upperSpots, isCurved: true,
          color: AppColors.green.withValues(alpha: 0.3), barWidth: 1,
          dotData: const FlDotData(show: false), dashArray: [4, 3]),
        LineChartBarData(spots: lowerSpots, isCurved: true,
          color: AppColors.red.withValues(alpha: 0.3), barWidth: 1,
          dotData: const FlDotData(show: false), dashArray: [4, 3],
          belowBarData: BarAreaData(show: true, color: AppColors.green.withValues(alpha: 0.04))),
        LineChartBarData(spots: spots, isCurved: true,
          color: AppColors.green, barWidth: 2.5,
          dotData: FlDotData(show: true,
            getDotPainter: (_, __, ___, ____) => FlDotCirclePainter(
              radius: 3, color: AppColors.green, strokeWidth: 0))),
      ],
      minY: minY - range * 0.05,
      maxY: maxY + range * 0.05,
    );
  }

  Widget _buildTradingAdvice() {
    if (_data == null || _signal == null || _indicators == null) {
      return const Center(child: CircularProgressIndicator(color: AppColors.gold));
    }
    // Buat GoldPrice minimal dari SignalData
    final price = GoldPrice(
      timestamp : DateTime.now().toIso8601String(),
      price     : _signal!.currentPrice,
      open      : _signal!.currentPrice,
      high      : _signal!.currentPrice,
      low       : _signal!.currentPrice,
      changeUsd : 0,
      changePct : 0,
    );
    final advice = TradingAdvisor.generate(
      price       : price,
      signal      : _signal!,
      prediction  : _data!,
      indicators  : _indicators!,
    );
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [TradingAdviceWidget(advice: advice)],
    );
  }

  Widget _shimmer() => ListView(padding: const EdgeInsets.all(16), children: const [
    ShimmerCard(height: 100), SizedBox(height: 10),
    ShimmerCard(height: 200), SizedBox(height: 10),
    ShimmerCard(height: 300),
  ]);
}


