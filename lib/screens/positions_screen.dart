// lib/screens/positions_screen.dart
import 'dart:async';
import 'package:flutter/material.dart';
import '../core/theme.dart';
import '../services/api_service.dart';
import '../services/ws_service.dart';

class PositionsScreen extends StatefulWidget {
  const PositionsScreen({super.key});

  @override
  State<PositionsScreen> createState() => _PositionsScreenState();
}

class _PositionsScreenState extends State<PositionsScreen> {
  final _api = ApiService();
  final _ws = WsService();
  StreamSubscription? _sub;
  Timer? _poll;

  List<Position> _positions = [];
  bool _loading = true;
  String? _error;
  final _closing = <int>{};

  @override
  void initState() {
    super.initState();
    _refresh();
    _poll = Timer.periodic(const Duration(seconds: 5), (_) => _refresh(silent: true));
    _sub = _ws.events.listen((e) {
      if (e.event == 'trade_opened' || e.event == 'trade_closed') _refresh(silent: true);
    });
  }

  @override
  void dispose() {
    _poll?.cancel();
    _sub?.cancel();
    super.dispose();
  }

  Future<void> _refresh({bool silent = false}) async {
    if (!silent) setState(() => _loading = true);
    try {
      final p = await _api.getPositions();
      if (!mounted) return;
      setState(() {
        _positions = p;
        _error = null;
        _loading = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _error = '$e';
        _loading = false;
      });
    }
  }

  Future<void> _close(Position p) async {
    setState(() => _closing.add(p.ticket));
    try {
      final ok = await _api.closePosition(p.ticket);
      if (mounted && ok) {
        ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(content: Text('Posisi #${p.ticket} ditutup')));
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text('Gagal menutup: $e')));
      }
    } finally {
      if (mounted) setState(() => _closing.remove(p.ticket));
      _refresh(silent: true);
    }
  }

  double get _totalPL =>
      _positions.fold(0.0, (s, p) => s + p.profit);

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Posisi Terbuka'),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh),
            onPressed: () => _refresh(),
          ),
        ],
      ),
      body: RefreshIndicator(
        onRefresh: _refresh,
        child: _loading
            ? const Center(child: CircularProgressIndicator())
            : _error != null
                ? _ErrorView(error: _error!, onRetry: _refresh)
                : _positions.isEmpty
                    ? ListView(children: const [
                        SizedBox(height: 120),
                        Center(child: Text('Tidak ada posisi terbuka')),
                      ])
                    : Column(
                        children: [
                          _summaryBar(),
                          Expanded(
                            child: ListView.builder(
                              padding: const EdgeInsets.all(12),
                              itemCount: _positions.length,
                              itemBuilder: (_, i) => _card(_positions[i]),
                            ),
                          ),
                        ],
                      ),
      ),
    );
  }

  Widget _summaryBar() {
    final c = _totalPL >= 0 ? AppColors.green : AppColors.red;
    return Container(
      width: double.infinity,
      color: AppColors.surface,
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Text('${_positions.length} posisi',
              style: const TextStyle(color: AppColors.textSecondary)),
          Text('Total P/L: ${_totalPL >= 0 ? '+' : ''}${_totalPL.toStringAsFixed(2)}',
              style: TextStyle(color: c, fontWeight: FontWeight.bold, fontSize: 16)),
        ],
      ),
    );
  }

  Widget _card(Position p) {
    final dirColor = p.isBuy ? AppColors.green : AppColors.red;
    final plColor = p.profit >= 0 ? AppColors.green : AppColors.red;
    final busy = _closing.contains(p.ticket);
    return Container(
      margin: const EdgeInsets.only(bottom: 10),
      decoration: BoxDecoration(
        color: AppColors.surface,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: AppColors.border),
      ),
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                  decoration: BoxDecoration(
                    color: dirColor.withValues(alpha: 0.15),
                    borderRadius: BorderRadius.circular(6),
                  ),
                  child: Text(p.type,
                      style: TextStyle(
                          color: dirColor, fontWeight: FontWeight.bold, fontSize: 12)),
                ),
                const SizedBox(width: 8),
                Text(p.symbol,
                    style: const TextStyle(
                        color: AppColors.textPrimary,
                        fontWeight: FontWeight.bold,
                        fontSize: 15)),
                const Spacer(),
                Text('${p.profit >= 0 ? '+' : ''}${p.profit.toStringAsFixed(2)}',
                    style: TextStyle(
                        color: plColor, fontWeight: FontWeight.bold, fontSize: 16)),
              ],
            ),
            const SizedBox(height: 10),
            Wrap(
              spacing: 16,
              runSpacing: 4,
              children: [
                _kv('Lot', p.volume.toStringAsFixed(2)),
                _kv('Buka', p.priceOpen.toStringAsFixed(2)),
                _kv('Kini', p.priceCurrent.toStringAsFixed(2)),
                _kv('SL', p.sl == 0 ? '—' : p.sl.toStringAsFixed(2)),
                _kv('TP', p.tp == 0 ? '—' : p.tp.toStringAsFixed(2)),
                _kv('#', '${p.ticket}'),
              ],
            ),
            if (p.comment.isNotEmpty) ...[
              const SizedBox(height: 6),
              Text(p.comment,
                  style: const TextStyle(
                      color: AppColors.textSecondary, fontSize: 11)),
            ],
            const SizedBox(height: 10),
            SizedBox(
              width: double.infinity,
              child: OutlinedButton.icon(
                onPressed: busy ? null : () => _close(p),
                icon: busy
                    ? const SizedBox(
                        width: 14,
                        height: 14,
                        child: CircularProgressIndicator(strokeWidth: 2))
                    : const Icon(Icons.close, size: 16),
                label: Text(busy ? 'Menutup…' : 'Tutup Posisi'),
                style: OutlinedButton.styleFrom(
                  foregroundColor: AppColors.red,
                  side: const BorderSide(color: AppColors.red),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _kv(String k, String v) => Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(k, style: const TextStyle(color: AppColors.textSecondary, fontSize: 10)),
          Text(v, style: const TextStyle(color: AppColors.textPrimary, fontSize: 13)),
        ],
      );
}

class _ErrorView extends StatelessWidget {
  final String error;
  final Future<void> Function() onRetry;
  const _ErrorView({required this.error, required this.onRetry});

  @override
  Widget build(BuildContext context) {
    return ListView(
      children: [
        const SizedBox(height: 100),
        const Icon(Icons.cloud_off, color: AppColors.textSecondary, size: 48),
        const SizedBox(height: 12),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 32),
          child: Text(error,
              textAlign: TextAlign.center,
              style: const TextStyle(color: AppColors.textSecondary)),
        ),
        const SizedBox(height: 16),
        Center(
          child: FilledButton(onPressed: onRetry, child: const Text('Coba lagi')),
        ),
      ],
    );
  }
}
