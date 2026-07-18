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
    // Dulu 4 tab (Ringkasan/Tren/Momentum/Multi-TF). Sekarang 3: strateginya
    // cuma punya 4 komponen, dan memecahnya jadi tab "Tren" vs "Momentum" malah
    // menyembunyikan tiga baris Volatilitas (BB %B, BB Lebar, ATR) yang tak
    // punya tab sendiri. Semua nilai komponen digabung ke satu tab.
    _tabCtrl = TabController(length: 3, vsync: this);
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
          Tab(text: 'Setup'),
          Tab(text: 'Komponen'),
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
            _buildComponentsTab(),
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

      // Gerbang konfluensi — menggantikan kotak "Beli/Netral/Jual (N indikator)"
      // dan RSI gauge. Keduanya dibuang karena otak tidak lagi memungut suara
      // dan RSI tidak lagi ikut strategi. Yang berguna: gerbang mana penahannya.
      SectionLabel('Gerbang — ${ind.mode == 'scalping' ? 'Scalping' : 'Swing'}'),
      const SizedBox(height: 10),
      AppCard(child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          GateSummaryLine(
            passed: ind.gatesPassed,
            total: ind.gatesTotal,
            blockerName: ind.blocker?.name,
          ),
          // Saat belum ada setup, checklist di bawah adalah diagnosa untuk SATU
          // arah — yang paling dekat lolos. Tanpa keterangan ini, checklist
          // gampang disalahartikan sebagai "indikatornya rusak".
          if (ind.direction == null && ind.probeDirection != null) ...[
            const SizedBox(height: 6),
            Text(
              'Belum ada setup. Checklist di bawah menunjukkan arah '
              '${ind.probeDirection} — yang paling dekat lolos saat ini.',
              style: const TextStyle(
                  fontSize: 11, color: AppColors.textSecondary, height: 1.35),
            ),
          ],
          const SizedBox(height: 6),
          const Divider(height: 1, color: AppColors.border),
          const SizedBox(height: 4),
          GateChecklist(ind.gates),
          const SizedBox(height: 10),
          const Divider(height: 1, color: AppColors.border),
          const SizedBox(height: 8),
          // Dua harga, sengaja dipisah. Gerbang dinilai pada BAR TERTUTUP
          // (anti-repaint), jadi angkanya memang tertinggal dari harga berjalan
          // di MT5. Menampilkan keduanya menghapus kesan "data tidak cocok".
          Row(children: [
            const Text('Harga kini (bar berjalan)',
                style: TextStyle(fontSize: 11, color: AppColors.textSecondary)),
            const Spacer(),
            Text('\$${ind.livePrice.toStringAsFixed(2)}',
                style: const TextStyle(
                    fontSize: 12, fontWeight: FontWeight.w700)),
          ]),
          const SizedBox(height: 4),
          Row(children: [
            Text('Bar dianalisis (${ind.timestamp})',
                style: const TextStyle(fontSize: 11, color: AppColors.textSecondary)),
            const Spacer(),
            Text('\$${ind.currentPrice.toStringAsFixed(2)}',
                style: const TextStyle(
                    fontSize: 12, fontWeight: FontWeight.w700, color: AppColors.gold)),
          ]),
          const SizedBox(height: 6),
          const Text(
            'Gerbang dinilai pada bar TERTUTUP agar sinyal tidak berubah-ubah '
            '(anti-repaint). Jadi wajar angkanya tertinggal dari harga berjalan '
            'di MT5 — itu bukan data tidak cocok.',
            style: TextStyle(fontSize: 10, color: AppColors.textSecondary, height: 1.35),
          ),
        ],
      )),
      const SizedBox(height: 16),

      // Support & Resistance
      if (ind.support.isNotEmpty || ind.resistance.isNotEmpty) ...[
        const SectionLabel('Support & Resistance'),
        const SizedBox(height: 10),
        AppCard(child: Column(children: [
          ...ind.resistance.map((r) => _srRow('▼ Resistance', r, AppColors.red)),
          // Harga BAR YANG DIANALISIS — inilah yang dibandingkan gerbang dengan
          // level S&R. Sengaja dibedakan dari "harga kini" di bawah: keduanya
          // memang tidak sama, dan menyebut yang ini "harga saat ini" dulu
          // membuat angka terlihat tak cocok dengan MT5.
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 6),
            child: Row(children: [
              const Text('● Bar dianalisis', style: TextStyle(color: AppColors.gold, fontSize: 13)),
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

  /// Nilai mentah 4 komponen. Semuanya dalam satu tab — pemisahan lama jadi
  /// "Tren" vs "Momentum" menyembunyikan baris Volatilitas yang tak punya tab.
  Widget _buildComponentsTab() {
    if (_indicators == null) return const SizedBox();
    final sigs = _indicators!.signals;
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        const AppCard(child: Text(
          'Nilai mentah komponen strategi. Ini untuk dilihat saja — keputusan '
          'entry sepenuhnya dari gerbang di tab Setup, bukan dari hitungan '
          'berapa komponen yang setuju.',
          style: TextStyle(fontSize: 11, color: AppColors.textSecondary, height: 1.4),
        )),
        const SizedBox(height: 12),
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

      // Peringatan data sintetis. Brain masih bersumber yfinance HARIAN, jadi
      // timeframe di bawah 1D dikarang: data harian + noise acak. Pengguna wajib
      // tahu baris mana yang tidak boleh dipercaya.
      if (_multitf!.timeframes.any((t) => t.synthetic)) ...[
        Container(
          padding: const EdgeInsets.all(12),
          decoration: BoxDecoration(
            color: AppColors.red.withValues(alpha: 0.08),
            borderRadius: BorderRadius.circular(8),
            border: Border.all(color: AppColors.red.withValues(alpha: 0.3)),
          ),
          child: const Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Icon(Icons.warning_amber_rounded, size: 16, color: AppColors.red),
            SizedBox(width: 8),
            Expanded(child: Text(
              'Baris bertanda "sintetis" TIDAK memakai data asli — timeframe di '
              'bawah 1 Hari disimulasikan dari data harian + noise acak. Jangan '
              'dipakai untuk keputusan trading.',
              style: TextStyle(fontSize: 11, color: AppColors.red, height: 1.4),
            )),
          ]),
        ),
        const SizedBox(height: 16),
      ],

      // Timeframe list
      const SectionLabel('Setup per Timeframe'),
      const SizedBox(height: 10),
      AppCard(child: Column(
        children: _multitf!.timeframes.asMap().entries.map((e) {
          final tf = e.value;
          return Column(children: [
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 10),
              child: Row(children: [
                SizedBox(width: 82,
                  child: Text(tf.timeframe,
                    style: const TextStyle(fontSize: 13, color: AppColors.textSecondary))),
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                  decoration: BoxDecoration(
                    color: AppColors.border,
                    borderRadius: BorderRadius.circular(4),
                  ),
                  child: Text(tf.label, style: const TextStyle(fontSize: 10)),
                ),
                if (tf.synthetic) ...[
                  const SizedBox(width: 5),
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 5, vertical: 2),
                    decoration: BoxDecoration(
                      color: AppColors.red.withValues(alpha: 0.13),
                      borderRadius: BorderRadius.circular(3),
                    ),
                    child: const Text('sintetis', style: TextStyle(
                      fontSize: 9, color: AppColors.red, fontWeight: FontWeight.w700)),
                  ),
                ],
                const Spacer(),
                // Ganti "RSI xx.x" (RSI sudah tak dipakai) dengan hitungan gerbang.
                Text('${tf.gatesPassed}/${tf.gatesTotal}',
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

  // _buildRsiGauge dihapus: RSI sudah tidak ikut strategi, jadi gauge-nya
  // selamanya menunjuk 50 "NETRAL" (nilai default saat RSI tak ditemukan) —
  // angka yang terlihat sah tapi tidak berarti apa-apa.

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
