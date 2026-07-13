// lib/screens/fundamental_screen.dart
import 'package:flutter/material.dart';
import '../core/theme.dart';
import '../services/api_service.dart';
import '../widgets/common_widgets.dart';

class FundamentalScreen extends StatefulWidget {
  const FundamentalScreen({super.key});
  @override
  State<FundamentalScreen> createState() => _FundamentalScreenState();
}

class _FundamentalScreenState extends State<FundamentalScreen> {
  final _api = ApiService();
  FundamentalData? _data;
  bool _loading = true;
  String? _error;

  @override
  void initState() { super.initState(); _load(); }

  Future<void> _load() async {
    setState(() { _loading = true; _error = null; });
    try {
      final d = await _api.getFundamental();
      setState(() { _data = d; _loading = false; });
    } catch (e) {
      setState(() { _loading = false; _error = e.toString().replaceAll('Exception: ', ''); });
    }
  }

  String _displayName(String key) {
    const names = {
      'dxy'         : 'Dollar Index (DXY)',
      'vix'         : 'VIX Fear Index',
      'bond10y'     : 'Yield UST 10Y',
      'oil_wti'     : 'Minyak WTI',
      'sp500'       : 'S&P 500',
      'cpi'         : 'Inflasi CPI',
      'fed_rate'    : 'Suku Bunga Fed',
      'unemployment': 'Pengangguran AS',
      'gdp'         : 'GDP AS',
      'm2'          : 'Money Supply M2',
    };
    return names[key] ?? key.toUpperCase();
  }

  Color _impactColor(String impact, double? chg) {
    if (chg == null) return AppColors.textSecondary;
    if (impact == 'inverse') return chg < 0 ? AppColors.green : AppColors.red;
    return chg > 0 ? AppColors.green : AppColors.red;
  }

  String _impactLabel(String impact, double? chg) {
    if (chg == null) return '-';
    final direction = chg > 0 ? '▲ Naik' : '▼ Turun';
    final effect = impact == 'inverse'
        ? (chg < 0 ? 'Bullish Emas' : 'Bearish Emas')
        : (chg > 0 ? 'Bullish Emas' : 'Bearish Emas');
    return '$direction — $effect';
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(
      title: const Text('Data Fundamental'),
      actions: [
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
      : ListView(
          padding: const EdgeInsets.all(16),
          children: [
            if (_data != null) ...[
              Text(
                'Update: ${_data!.timestamp}',
                style: const TextStyle(fontSize: 11, color: AppColors.textSecondary),
              ),
              const SizedBox(height: 12),
              ..._data!.items.map((item) => Padding(
                padding: const EdgeInsets.only(bottom: 10),
                child: AppCard(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(children: [
                        Text(
                          _displayName(item.name),
                          style: const TextStyle(
                            fontSize: 11,
                            color: AppColors.textSecondary,
                            letterSpacing: 0.5,
                          ),
                        ),
                        const Spacer(),
                        Container(
                          padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                          decoration: BoxDecoration(
                            color: item.impact == 'inverse'
                                ? AppColors.redBg
                                : AppColors.greenBg,
                            borderRadius: BorderRadius.circular(4),
                          ),
                          child: Text(
                            item.impact == 'inverse' ? 'INVERS' : 'POSITIF',
                            style: TextStyle(
                              fontSize: 9,
                              color: item.impact == 'inverse'
                                  ? AppColors.red
                                  : AppColors.green,
                            ),
                          ),
                        ),
                      ]),
                      const SizedBox(height: 8),
                      Row(
                        crossAxisAlignment: CrossAxisAlignment.end,
                        children: [
                          Text(
                            item.value != null
                                ? '${item.value!.toStringAsFixed(2)} ${item.unit}'
                                : 'N/A',
                            style: const TextStyle(
                              fontSize: 20,
                              fontWeight: FontWeight.w700,
                            ),
                          ),
                          const Spacer(),
                          if (item.changePct != null)
                            Text(
                              _impactLabel(item.impact, item.changePct),
                              style: TextStyle(
                                fontSize: 11,
                                color: _impactColor(item.impact, item.changePct),
                              ),
                            ),
                        ],
                      ),
                    ],
                  ),
                ),
              )),
            ],
            const SizedBox(height: 80),
          ],
        ),
  );

  Widget _shimmer() => ListView(
    padding: const EdgeInsets.all(16),
    children: List.generate(
      6,
      (_) => const Padding(
        padding: EdgeInsets.only(bottom: 10),
        child: ShimmerCard(height: 80),
      ),
    ),
  );
}
