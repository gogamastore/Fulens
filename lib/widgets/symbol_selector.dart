// lib/widgets/symbol_selector.dart
import 'package:flutter/material.dart';
import '../core/theme.dart';
import '../state/symbol_state.dart';

/// Bar tipis di atas semua layar: menampilkan & mengganti simbol terpilih.
/// Semua tab mengikuti simbol ini.
class SymbolTopBar extends StatelessWidget {
  const SymbolTopBar({super.key});

  IconData _assetIcon(String asset) => switch (asset) {
        'metal' => Icons.diamond_outlined,
        'forex' => Icons.currency_exchange,
        'crypto' => Icons.currency_bitcoin,
        'commodity' => Icons.oil_barrel_outlined,
        _ => Icons.show_chart,
      };

  @override
  Widget build(BuildContext context) {
    final state = SymbolState.instance;
    return Material(
      color: AppColors.surface,
      child: SafeArea(
        bottom: false,
        child: Container(
          height: 52,
          padding: const EdgeInsets.symmetric(horizontal: 14),
          decoration: const BoxDecoration(
            border: Border(bottom: BorderSide(color: AppColors.border)),
          ),
          child: ListenableBuilder(
            listenable: state,
            builder: (context, _) {
              final cur = state.current;
              return Row(
                children: [
                  Icon(_assetIcon(cur?.asset ?? ''), size: 18, color: AppColors.gold),
                  const SizedBox(width: 8),
                  const Text('Simbol:',
                      style: TextStyle(color: AppColors.textSecondary, fontSize: 12)),
                  const SizedBox(width: 8),
                  Expanded(
                    child: InkWell(
                      onTap: () => _openPicker(context, state),
                      borderRadius: BorderRadius.circular(8),
                      child: Container(
                        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
                        decoration: BoxDecoration(
                          color: AppColors.surface2,
                          borderRadius: BorderRadius.circular(8),
                          border: Border.all(color: AppColors.border),
                        ),
                        child: Row(
                          children: [
                            Text(state.symbol,
                                style: const TextStyle(
                                    color: AppColors.textPrimary,
                                    fontWeight: FontWeight.bold,
                                    fontSize: 14)),
                            const SizedBox(width: 6),
                            if (cur != null)
                              Expanded(
                                child: Text(cur.name,
                                    overflow: TextOverflow.ellipsis,
                                    style: const TextStyle(
                                        color: AppColors.textSecondary, fontSize: 11)),
                              ),
                            const Icon(Icons.keyboard_arrow_down,
                                color: AppColors.textSecondary, size: 18),
                          ],
                        ),
                      ),
                    ),
                  ),
                  const SizedBox(width: 8),
                  _timeframePill(state),
                ],
              );
            },
          ),
        ),
      ),
    );
  }

  Widget _timeframePill(SymbolState state) {
    return PopupMenuButton<String>(
      color: AppColors.surface2,
      onSelected: state.setTimeframe,
      itemBuilder: (_) => [
        for (final tf in state.timeframes)
          PopupMenuItem(
            value: tf,
            height: 38,
            child: Row(children: [
              if (tf == state.timeframe)
                const Icon(Icons.check, size: 16, color: AppColors.gold)
              else
                const SizedBox(width: 16),
              const SizedBox(width: 8),
              Text(tf,
                  style: TextStyle(
                      color: tf == state.timeframe
                          ? AppColors.gold
                          : AppColors.textPrimary,
                      fontWeight: FontWeight.bold)),
            ]),
          ),
      ],
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
        decoration: BoxDecoration(
          color: AppColors.goldBg,
          borderRadius: BorderRadius.circular(8),
          border: Border.all(color: AppColors.gold),
        ),
        child: Row(mainAxisSize: MainAxisSize.min, children: [
          const Icon(Icons.timelapse, size: 14, color: AppColors.gold),
          const SizedBox(width: 4),
          Text(state.timeframe,
              style: const TextStyle(
                  color: AppColors.gold, fontWeight: FontWeight.bold, fontSize: 13)),
          const Icon(Icons.arrow_drop_down, color: AppColors.gold, size: 18),
        ]),
      ),
    );
  }

  void _openPicker(BuildContext context, SymbolState state) {
    showModalBottomSheet(
      context: context,
      backgroundColor: AppColors.surface,
      shape: const RoundedRectangleBorder(
          borderRadius: BorderRadius.vertical(top: Radius.circular(16))),
      builder: (_) {
        final items = state.symbols;
        return SafeArea(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Padding(
                padding: EdgeInsets.all(16),
                child: Text('Pilih Simbol',
                    style: TextStyle(
                        color: AppColors.textPrimary,
                        fontWeight: FontWeight.bold,
                        fontSize: 16)),
              ),
              if (items.isEmpty)
                const Padding(
                  padding: EdgeInsets.all(24),
                  child: Text('Daftar simbol belum termuat',
                      style: TextStyle(color: AppColors.textSecondary)),
                )
              else
                Flexible(
                  child: ListView.builder(
                    shrinkWrap: true,
                    itemCount: items.length,
                    itemBuilder: (_, i) {
                      final s = items[i];
                      final sel = s.symbol == state.symbol;
                      return ListTile(
                        leading: Icon(_assetIcon(s.asset),
                            color: sel ? AppColors.gold : AppColors.textSecondary),
                        title: Text(s.symbol,
                            style: TextStyle(
                                color: sel ? AppColors.gold : AppColors.textPrimary,
                                fontWeight: FontWeight.bold)),
                        subtitle: Text('${s.name}  ·  ${s.asset}${s.ml ? '  · ML' : ''}',
                            style: const TextStyle(
                                color: AppColors.textSecondary, fontSize: 11)),
                        trailing: sel
                            ? const Icon(Icons.check_circle, color: AppColors.gold)
                            : null,
                        onTap: () {
                          state.setSymbol(s.symbol);
                          Navigator.pop(context);
                        },
                      );
                    },
                  ),
                ),
              const SizedBox(height: 8),
            ],
          ),
        );
      },
    );
  }
}
