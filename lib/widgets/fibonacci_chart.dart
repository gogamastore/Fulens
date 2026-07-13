// lib/widgets/fibonacci_chart.dart
import 'package:flutter/material.dart';
import 'package:syncfusion_flutter_charts/charts.dart';
import '../core/theme.dart';
import '../services/api_service.dart';

/// Level Fibonacci retracement dari swing high/low pada rentang candle.
class _FibLevel {
  final double ratio;
  final double price;
  _FibLevel(this.ratio, this.price);
}

/// Candlestick live + overlay Fibonacci retracement sebagai gambaran keputusan.
///
/// Fibonacci dihitung dari harga tertinggi & terendah pada data yang tampil.
/// Garis support/resistance & harga saat ini bisa ditambahkan lewat parameter.
class FibonacciChart extends StatelessWidget {
  final List<OhlcData> candles;
  final double? currentPrice;
  final String title;

  const FibonacciChart({
    super.key,
    required this.candles,
    this.currentPrice,
    this.title = 'XAUUSD — Live + Fibonacci',
  });

  static const _ratios = [0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0];

  List<_FibLevel> _fib() {
    if (candles.isEmpty) return const [];
    double hi = candles.first.high, lo = candles.first.low;
    for (final c in candles) {
      if (c.high > hi) hi = c.high;
      if (c.low < lo) lo = c.low;
    }
    final range = hi - lo;
    // Retracement dari atas (uptrend swing): 0.0 = high, 1.0 = low.
    return _ratios.map((r) => _FibLevel(r, hi - range * r)).toList();
  }

  Color _fibColor(double r) {
    if (r == 0.5 || r == 0.618) return AppColors.gold;      // zona emas
    if (r == 0.0 || r == 1.0) return AppColors.textSecondary;
    return AppColors.gold.withValues(alpha: 0.45);
  }

  @override
  Widget build(BuildContext context) {
    if (candles.isEmpty) {
      return const SizedBox(
        height: 320,
        child: Center(child: Text('Belum ada data chart')),
      );
    }

    final levels = _fib();
    final bands = <PlotBand>[
      for (final l in levels)
        PlotBand(
          isVisible: true,
          start: l.price,
          end: l.price,
          borderWidth: (l.ratio == 0.5 || l.ratio == 0.618) ? 1.4 : 0.8,
          borderColor: _fibColor(l.ratio),
          dashArray: const [4, 4],
          text: 'Fib ${l.ratio.toStringAsFixed(3)}  ${l.price.toStringAsFixed(2)}',
          textStyle: TextStyle(fontSize: 9, color: _fibColor(l.ratio)),
          horizontalTextAlignment: TextAnchor.start,
          verticalTextAlignment: TextAnchor.end,
        ),
      if (currentPrice != null)
        PlotBand(
          isVisible: true,
          start: currentPrice,
          end: currentPrice,
          borderWidth: 1.2,
          borderColor: AppColors.green,
          text: 'Harga ${currentPrice!.toStringAsFixed(2)}',
          textStyle: const TextStyle(fontSize: 9, color: AppColors.green),
          horizontalTextAlignment: TextAnchor.end,
        ),
    ];

    return SizedBox(
      height: 360,
      child: SfCartesianChart(
        title: ChartTitle(
          text: title,
          textStyle: const TextStyle(fontSize: 13, color: AppColors.textSecondary),
        ),
        plotAreaBorderWidth: 0,
        primaryXAxis: DateTimeAxis(
          majorGridLines: const MajorGridLines(width: 0),
          axisLine: const AxisLine(width: 0.4, color: AppColors.border),
          labelStyle: const TextStyle(fontSize: 9, color: AppColors.textSecondary),
        ),
        primaryYAxis: NumericAxis(
          opposedPosition: true,
          plotBands: bands,
          majorGridLines: const MajorGridLines(
              width: 0.3, color: AppColors.border, dashArray: [3, 6]),
          axisLine: const AxisLine(width: 0),
          labelStyle: const TextStyle(fontSize: 9, color: AppColors.textSecondary),
        ),
        zoomPanBehavior: ZoomPanBehavior(
          enablePinching: true,
          enablePanning: true,
          zoomMode: ZoomMode.x,
        ),
        trackballBehavior: TrackballBehavior(
          enable: true,
          activationMode: ActivationMode.singleTap,
          tooltipSettings: const InteractiveTooltip(format: 'point.x\nO:point.open H:point.high\nL:point.low C:point.close'),
        ),
        series: <CandleSeries<OhlcData, DateTime>>[
          CandleSeries<OhlcData, DateTime>(
            dataSource: candles,
            xValueMapper: (c, _) => DateTime.tryParse(c.date) ?? DateTime.now(),
            lowValueMapper: (c, _) => c.low,
            highValueMapper: (c, _) => c.high,
            openValueMapper: (c, _) => c.open,
            closeValueMapper: (c, _) => c.close,
            bearColor: AppColors.red,
            bullColor: AppColors.green,
            enableSolidCandles: true,
          ),
        ],
      ),
    );
  }
}
