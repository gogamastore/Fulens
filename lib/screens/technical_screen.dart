// lib/screens/technical_screen.dart
import 'package:flutter/material.dart';
import '../core/theme.dart';
import '../services/api_service.dart';
import '../widgets/common_widgets.dart';

class TechnicalScreen extends StatefulWidget {
  const TechnicalScreen({super.key});
  @override
  State<TechnicalScreen> createState() => _TechnicalScreenState();
}

class _TechnicalScreenState extends State<TechnicalScreen>
    with SingleTickerProviderStateMixin {
  final _api = ApiService();
  IndicatorData? _indicators;
  MultiTFData? _multitf;
  bool _loading = true;
  String? _error;
  late TabController _tabCtrl;

  @override
  void initState() {
    super.initState();
    _tabCtrl = TabController(length: 4, vsync: this);
    _load();
  }

  @override
  void dispose() { _tabCtrl.dispose(); super.dispose(); }

  Future<void> _load() async {
    setState(() { _loading = true; _error = null; });
    try {
      final r = await Future.wait([_api.getIndicators(), _api.getMultiTimeframe()]);
      setState(() {
        _indicators = r[0] as IndicatorData;
        _multitf    = r[1] as MultiTFData;
        _loading = false;
      });
    } catch (e) {
      setState(() { _loading = false; _error = e.toString().replaceAll('Exception: ', ''); });
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(
      title: const Text('Analisis Teknikal'),
      actions: [
        IconButton(icon: const Icon(Icons.refresh), onPressed: _load,
          color: AppColors.gold),
      ],
      bottom: TabBar(
        controller: _tabCtrl,
        labelColor: AppColors.gold,
        unselectedLabelColor: AppColors.textSecondary,
        indicatorColor: AppColors.gold,
        isScrollable: true,
        tabs: const [
          Tab(text: 'Ringkasan'),
          Tab(text: 'Tren'),
          Tab(text: 'Momentum'),
          Tab(text: 'Multi-TF'),
        ],
      ),
    ),
    body: _error != null
      ? Padding(padding: const EdgeInsets.all(16),
          child: ErrorCard(message: _error!, onRetry: _load))
      : _loading
      ? _buildShimmer()
      : TabBarView(
          controller: _tabCtrl,
          children: [
            _buildSummaryTab(),
            _buildCategoryTab('Tren'),
            _buildCategoryTab('Momentum'),
            _buildMultiTFTab(),
          ],
        ),
  );

  Widget _buildSummaryTab() {
    if (_indicators == null) return const SizedBox();
    final ind = _indicators!;
    return ListView(padding: const EdgeInsets.all(16), children: [
      // Overall signal
      _buildSignalCard(ind.overallSignal, ind.confidence),
      const SizedBox(height: 16),

      // Buy/Sell/Neutral counts
      const SectionLabel('Ringkasan Sinyal'),
      const SizedBox(height: 10),
      AppCard(child: Row(children: [
        _countBox('${ind.buyCount}', 'Beli', AppColors.green),
        _countBox('${ind.neutralCount}', 'Netral', AppColors.gold),
        _countBox('${ind.sellCount}', 'Jual', AppColors.red),
      ])),
      const SizedBox(height: 16),

      // RSI Gauge
      const SectionLabel('RSI (14)'),
      const SizedBox(height: 10),
      AppCard(child: _buildRsiGauge(ind)),
      const SizedBox(height: 16),

      // Support & Resistance
      if (ind.support.isNotEmpty || ind.resistance.isNotEmpty) ...[
        const SectionLabel('Support & Resistance'),
        const SizedBox(height: 10),
        AppCard(child: Column(children: [
          ...ind.resistance.map((r) => _srRow('▼ Resistance', r, AppColors.red)),
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 6),
            child: Row(children: [
              const Text('● Harga Saat Ini', style: TextStyle(color: AppColors.gold, fontSize: 13)),
              const Spacer(),
              Text('\$${ind.currentPrice.toStringAsFixed(2)}',
                style: const TextStyle(color: AppColors.gold, fontSize: 13,
                  fontWeight: FontWeight.w700)),
            ]),
          ),
          ...ind.support.map((s) => _srRow('▲ Support', s, AppColors.green)),
        ])),
      ],
    ]);
  }

  Widget _buildCategoryTab(String category) {
    if (_indicators == null) return const SizedBox();
    final sigs = _indicators!.signals.where((s) => s.category == category).toList();
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        AppCard(child: Column(
          children: sigs.asMap().entries.map((e) => Column(
            children: [
              IndicatorRow(
                name: e.value.name,
                valueStr: e.value.value.toStringAsFixed(2),
                signal: e.value.signal,
                detail: e.value.detail,
              ),
              if (e.key < sigs.length - 1)
                const Divider(height: 1, color: AppColors.border),
            ],
          )).toList(),
        )),
        const SizedBox(height: 80),
      ],
    );
  }

  Widget _buildMultiTFTab() {
    if (_multitf == null) return const SizedBox();
    final consensus = _multitf!.consensus;
    return ListView(padding: const EdgeInsets.all(16), children: [
      // Consensus
      AppCard(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        const SectionLabel('Konsensus'),
        const SizedBox(height: 12),
        Row(children: [
          _countBox('${consensus['bullish'] ?? 0}', 'Bullish', AppColors.green),
          _countBox('${consensus['neutral'] ?? 0}', 'Netral', AppColors.gold),
          _countBox('${consensus['bearish'] ?? 0}', 'Bearish', AppColors.red),
        ]),
        const SizedBox(height: 12),
        Row(children: [
          const Text('Bias Keseluruhan: ', style: TextStyle(fontSize: 13, color: AppColors.textSecondary)),
          Text(consensus['bias'] ?? '-',
            style: TextStyle(
              fontSize: 13, fontWeight: FontWeight.w700,
              color: (consensus['bias'] ?? '') == 'BULLISH' ? AppColors.green
                   : (consensus['bias'] ?? '') == 'BEARISH' ? AppColors.red
                   : AppColors.gold,
            )),
        ]),
      ])),
      const SizedBox(height: 16),

      // Timeframe list
      const SectionLabel('Analisis per Timeframe'),
      const SizedBox(height: 10),
      AppCard(child: Column(
        children: _multitf!.timeframes.asMap().entries.map((e) {
          final tf = e.value;
          return Column(children: [
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 10),
              child: Row(children: [
                SizedBox(width: 90,
                  child: Text(tf.timeframe,
                    style: const TextStyle(fontSize: 13, color: AppColors.textSecondary))),
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                  decoration: BoxDecoration(
                    color: AppColors.border,
                    borderRadius: BorderRadius.circular(4),
                  ),
                  child: Text(tf.label,
                    style: const TextStyle(fontSize: 10)),
                ),
                const Spacer(),
                Text('RSI ${tf.rsi.toStringAsFixed(1)}',
                  style: const TextStyle(fontSize: 11, color: AppColors.textSecondary)),
                const SizedBox(width: 8),
                SignalBadge(tf.signal),
              ]),
            ),
            if (e.key < _multitf!.timeframes.length - 1)
              const Divider(height: 1, color: AppColors.border),
          ]);
        }).toList(),
      )),
      const SizedBox(height: 80),
    ]);
  }

  Widget _buildSignalCard(String signal, double confidence) => Container(
    padding: const EdgeInsets.all(16),
    decoration: BoxDecoration(
      color: signal.signalBgColor,
      borderRadius: BorderRadius.circular(12),
      border: Border.all(color: signal.signalColor.withValues(alpha: 0.3)),
    ),
    child: Row(children: [
      Text('${signal.signalIcon} $signal',
        style: TextStyle(fontSize: 22, fontWeight: FontWeight.w700, color: signal.signalColor)),
      const Spacer(),
      Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
        const Text('Kepercayaan', style: TextStyle(fontSize: 10, color: AppColors.textSecondary)),
        Text('${confidence.toStringAsFixed(1)}%',
          style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w700,
            color: AppColors.gold)),
      ]),
    ]),
  );

  Widget _buildRsiGauge(IndicatorData ind) {
    final rsiSig = ind.signals.where((s) => s.name == 'RSI (14)').firstOrNull;
    final rsi = rsiSig?.value ?? 50.0;
    final color = rsi < 30 ? AppColors.green : rsi > 70 ? AppColors.red : AppColors.gold;
    return Column(children: [
      Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
        Text(rsi.toStringAsFixed(1),
          style: TextStyle(fontSize: 36, fontWeight: FontWeight.w700,
            color: color)),
        Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
          Text(rsi < 30 ? 'OVERSOLD — Sinyal Beli'
               : rsi > 70 ? 'OVERBOUGHT — Sinyal Jual'
               : 'NETRAL',
            style: TextStyle(fontSize: 12, color: color, fontWeight: FontWeight.w600)),
          Text('Range: 0 – 100', style: const TextStyle(fontSize: 11, color: AppColors.textSecondary)),
        ]),
      ]),
      const SizedBox(height: 10),
      ClipRRect(
        borderRadius: BorderRadius.circular(4),
        child: LinearProgressIndicator(
          value: rsi / 100,
          minHeight: 8,
          backgroundColor: AppColors.surface2,
          valueColor: AlwaysStoppedAnimation(color),
        ),
      ),
      const SizedBox(height: 6),
      const Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Text('0 Oversold', style: TextStyle(fontSize: 9, color: AppColors.green)),
          Text('30', style: TextStyle(fontSize: 9, color: AppColors.textSecondary)),
          Text('70', style: TextStyle(fontSize: 9, color: AppColors.textSecondary)),
          Text('100 Overbought', style: TextStyle(fontSize: 9, color: AppColors.red)),
        ],
      ),
    ]);
  }

  Widget _countBox(String count, String label, Color color) => Expanded(
    child: Column(children: [
      Text(count, style: TextStyle(fontSize: 28, fontWeight: FontWeight.w700,
        color: color)),
      Text(label, style: const TextStyle(fontSize: 11, color: AppColors.textSecondary)),
    ]),
  );

  Widget _srRow(String label, double price, Color color) => Padding(
    padding: const EdgeInsets.symmetric(vertical: 6),
    child: Row(children: [
      Text(label, style: TextStyle(fontSize: 13, color: color)),
      const Spacer(),
      Text('\$${price.toStringAsFixed(2)}',
        style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w700)),
    ]),
  );

  Widget _buildShimmer() => ListView(padding: const EdgeInsets.all(16), children: const [
    ShimmerCard(height: 80), SizedBox(height: 10),
    ShimmerCard(height: 120), SizedBox(height: 10),
    ShimmerCard(height: 200),
  ]);
}
