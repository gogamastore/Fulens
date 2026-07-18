// lib/screens/dashboard_screen.dart
import 'dart:async';
import 'package:flutter/material.dart';
import 'package:fl_chart/fl_chart.dart';
import '../core/theme.dart';
import '../services/api_service.dart';
import '../widgets/common_widgets.dart';

class DashboardScreen extends StatefulWidget {
  const DashboardScreen({super.key});

  @override
  State<DashboardScreen> createState() => _DashboardScreenState();
}

class _DashboardScreenState extends State<DashboardScreen> {
  final _api = ApiService();
  GoldPrice? _price;
  SignalData? _signal;
  List<OhlcData> _history = [];
  bool _loading = true;
  String? _error;
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    _loadAll();
    // Auto-refresh setiap 60 detik
    _timer = Timer.periodic(const Duration(seconds: 60), (_) => _loadAll());
  }

  @override
  void dispose() { _timer?.cancel(); super.dispose(); }

  Future<void> _loadAll() async {
    try {
      final results = await Future.wait([
        _api.getPrice(),
        _api.getSignal(),
        _api.getHistory(days: 30),
      ]);
      if (mounted) setState(() {
        _price   = results[0] as GoldPrice;
        _signal  = results[1] as SignalData;
        _history = results[2] as List<OhlcData>;
        _loading = false;
        _error   = null;
      });
    } catch (e) {
      if (mounted) setState(() {
        _loading = false;
        _error   = e.toString().replaceAll('Exception: ', '');
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Column(children: [
        // Header harga
        if (_price != null)
          GoldPriceHeader(
            price: _price!.price,
            changePct: _price!.changePct,
            timestamp: _price!.timestamp,
          )
        else
          _buildHeaderShimmer(),

        // Content
        Expanded(
          child: RefreshIndicator(
            onRefresh: _loadAll,
            color: AppColors.gold,
            backgroundColor: AppColors.surface,
            child: _error != null
              ? ListView(padding: const EdgeInsets.all(16), children: [
                  ErrorCard(message: _error!, onRetry: _loadAll),
                ])
              : _loading
              ? _buildShimmer()
              : _buildContent(),
          ),
        ),
      ]),
    );
  }

  Widget _buildContent() => ListView(
    padding: const EdgeInsets.all(16),
    children: [
      // ── Signal Banner ──
      if (_signal != null) _buildSignalBanner(),
      const SizedBox(height: 16),

      // ── KPI Row ──
      if (_price != null) ...[
        Row(children: [
          Expanded(child: KpiCard(
            label: 'Harga Emas',
            value: '\$${_price!.price.toStringAsFixed(2)}',
            subtitle: 'per troy oz',
            delta: '${_price!.changeUsd >= 0 ? '▲' : '▼'} \$${_price!.changeUsd.abs().toStringAsFixed(2)} hari ini',
            valueColor: AppColors.gold,
            deltaColor: _price!.changeUsd >= 0 ? AppColors.green : AppColors.red,
          )),
          const SizedBox(width: 10),
          Expanded(child: KpiCard(
            label: 'High / Low',
            value: '\$${_price!.high.toStringAsFixed(0)}',
            subtitle: 'High hari ini',
            delta: '▼ Low: \$${_price!.low.toStringAsFixed(0)}',
            valueColor: AppColors.green,
            deltaColor: AppColors.red,
          )),
        ]),
        const SizedBox(height: 10),
        Row(children: [
          if (_price!.dxy != null) Expanded(child: KpiCard(
            label: 'DXY',
            value: _price!.dxy!.toStringAsFixed(2),
            subtitle: 'Dollar Index',
            delta: '${_price!.dxy! < 102 ? '▼ Melemah' : '▲ Menguat'} — ${_price!.dxy! < 102 ? 'Bullish Emas' : 'Bearish Emas'}',
            deltaColor: _price!.dxy! < 102 ? AppColors.green : AppColors.red,
          )),
          const SizedBox(width: 10),
          if (_price!.vix != null) Expanded(child: KpiCard(
            label: 'VIX',
            value: _price!.vix!.toStringAsFixed(2),
            subtitle: 'Fear Index',
            delta: _price!.vix! > 20 ? '▲ Volatil — Bullish Emas' : '◆ Rendah',
            deltaColor: _price!.vix! > 20 ? AppColors.green : AppColors.textSecondary,
          )),
        ]),
      ],
      const SizedBox(height: 16),

      // ── Chart 30 Hari ──
      if (_history.isNotEmpty) ...[
        const SectionLabel('Grafik Harga 30 Hari'),
        const SizedBox(height: 10),
        AppCard(
          padding: const EdgeInsets.fromLTRB(8, 16, 16, 8),
          child: SizedBox(
            height: 200,
            child: LineChart(_buildChartData()),
          ),
        ),
        const SizedBox(height: 16),
      ],

      // ── Support & Resistance ──
      if (_signal != null && (_signal!.support.isNotEmpty || _signal!.resistance.isNotEmpty)) ...[
        const SectionLabel('Support & Resistance'),
        const SizedBox(height: 10),
        AppCard(
          child: Column(children: [
            if (_signal!.resistance.isNotEmpty)
              ..._signal!.resistance.map((r) => _srRow('Resistance', r, AppColors.red)),
            _currentPriceRow(),
            if (_signal!.support.isNotEmpty)
              ..._signal!.support.map((s) => _srRow('Support', s, AppColors.green)),
          ]),
        ),
        const SizedBox(height: 16),
      ],

      // ── Gerbang Setup ──
      // Dulu di sini ada tiga bar "Beli/Jual/Netral (N indikator)". Itu dibuang:
      // otak sudah tidak memungut suara, jadi rasio N-indikator tak punya arti
      // (dan dengan hitungan nol, pembagiannya menghasilkan NaN → bar penuh
      // semua). Sekarang yang ditampilkan: gerbang mana yang menahan setup.
      if (_signal != null) ...[
        SectionLabel('Gerbang Setup — ${_signal!.mode == 'scalping' ? 'Scalping' : 'Swing'}'),
        const SizedBox(height: 10),
        AppCard(child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            GateSummaryLine(
              passed: _signal!.gatesPassed,
              total: _signal!.gatesTotal,
              blockerName: _signal!.blocker?.name,
            ),
            const SizedBox(height: 6),
            const Divider(height: 1, color: AppColors.border),
            const SizedBox(height: 4),
            GateChecklist(_signal!.gates),
          ],
        )),
      ],
      const SizedBox(height: 80),
    ],
  );

  Widget _buildSignalBanner() {
    final s = _signal!;
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: s.signal.signalBgColor,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: s.signal.signalColor.withValues(alpha: 0.3)),
      ),
      child: Row(children: [
        Text(
          s.signal.contains('BELI') ? '🟢' : s.signal.contains('JUAL') ? '🔴' : '🟡',
          style: const TextStyle(fontSize: 28),
        ),
        const SizedBox(width: 12),
        Expanded(child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text('SINYAL AI SAAT INI',
              style: TextStyle(fontSize: 10, letterSpacing: 1.5, color: AppColors.textSecondary)),
            const SizedBox(height: 4),
            Text(s.signal,
              style: TextStyle(
                fontSize: 20, fontWeight: FontWeight.w700,
                color: s.signal.signalColor,
              ),
            ),
          ],
        )),
        Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
          const Text('Kepercayaan', style: TextStyle(fontSize: 10, color: AppColors.textSecondary)),
          const SizedBox(height: 4),
          Text('${s.confidence.toStringAsFixed(1)}%',
            style: const TextStyle(
              fontSize: 18, fontWeight: FontWeight.w700,
              color: AppColors.gold,
            ),
          ),
        ]),
      ]),
    );
  }

  LineChartData _buildChartData() {
    final spots = _history.asMap().entries.map((e) =>
      FlSpot(e.key.toDouble(), e.value.close),
    ).toList();

    final minY = _history.map((e) => e.close).reduce((a,b) => a<b?a:b);
    final maxY = _history.map((e) => e.close).reduce((a,b) => a>b?a:b);
    final range = maxY - minY;

    return LineChartData(
      gridData: FlGridData(
        show: true,
        drawVerticalLine: false,
        horizontalInterval: range / 4,
        getDrawingHorizontalLine: (_) => FlLine(
          color: AppColors.border, strokeWidth: 1,
        ),
      ),
      titlesData: FlTitlesData(
        leftTitles: AxisTitles(sideTitles: SideTitles(
          showTitles: true,
          reservedSize: 60,
          getTitlesWidget: (v, _) => Text(
            '\$${v.toStringAsFixed(0)}',
            style: const TextStyle(fontSize: 9, color: AppColors.textSecondary),
          ),
        )),
        bottomTitles: AxisTitles(sideTitles: SideTitles(
          showTitles: true,
          interval: 7,
          getTitlesWidget: (v, _) {
            final idx = v.toInt();
            if (idx < 0 || idx >= _history.length) return const SizedBox();
            return Text(
              _history[idx].date.substring(5), // MM-DD
              style: const TextStyle(fontSize: 9, color: AppColors.textSecondary),
            );
          },
        )),
        topTitles: const AxisTitles(sideTitles: SideTitles(showTitles: false)),
        rightTitles: const AxisTitles(sideTitles: SideTitles(showTitles: false)),
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
            color: AppColors.gold.withValues(alpha: 0.08),
          ),
        ),
      ],
      minY: minY - range * 0.05,
      maxY: maxY + range * 0.05,
    );
  }

  Widget _srRow(String label, double price, Color color) => Padding(
    padding: const EdgeInsets.symmetric(vertical: 6),
    child: Row(children: [
      Text(label, style: TextStyle(fontSize: 13, color: color)),
      const Spacer(),
      Text('\$${price.toStringAsFixed(2)}',
        style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w700)),
    ]),
  );

  Widget _currentPriceRow() => Padding(
    padding: const EdgeInsets.symmetric(vertical: 6),
    child: Row(children: [
      const Text('● Harga Saat Ini', style: TextStyle(fontSize: 13, color: AppColors.gold)),
      const Spacer(),
      Text('\$${_price?.price.toStringAsFixed(2) ?? '-'}',
        style: const TextStyle(
          fontSize: 13, fontWeight: FontWeight.w700,
          color: AppColors.gold,
        )),
    ]),
  );

  Widget _buildHeaderShimmer() => Container(
    height: 60, color: AppColors.surface,
    padding: const EdgeInsets.all(16),
    child: const ShimmerBox(height: 30),
  );

  Widget _buildShimmer() => ListView(
    padding: const EdgeInsets.all(16),
    children: const [
      ShimmerCard(height: 80),
      SizedBox(height: 10),
      Row(children: [
        Expanded(child: ShimmerCard()),
        SizedBox(width: 10),
        Expanded(child: ShimmerCard()),
      ]),
      SizedBox(height: 10),
      ShimmerCard(height: 200),
    ],
  );
}
