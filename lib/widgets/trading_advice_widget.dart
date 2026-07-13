// lib/widgets/trading_advice_widget.dart
import 'package:flutter/material.dart';
import '../core/theme.dart';
import '../services/api_service.dart';
import 'common_widgets.dart';

class TradingAdviceWidget extends StatelessWidget {
  final TradingAdvice advice;
  const TradingAdviceWidget({super.key, required this.advice});

  @override
  Widget build(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    children: [

      // ── HEADER SARAN ──────────────────────────────────
      _HeaderCard(advice: advice),
      const SizedBox(height: 12),

      // ── SUMMARY ───────────────────────────────────────
      AppCard(child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const SectionLabel('Ringkasan Analisis Hari Ini'),
          const SizedBox(height: 10),
          Text(advice.summary,
            style: const TextStyle(fontSize: 13, height: 1.6,
              color: AppColors.textPrimary)),
          const SizedBox(height: 12),
          Row(children: [
            _statChip('R/R Ratio', '1 : ${advice.riskRewardRatio.toStringAsFixed(2)}',
              advice.riskRewardRatio >= 2 ? AppColors.green : AppColors.gold),
            const SizedBox(width: 8),
            _statChip('Sesi', advice.sessionLabel, AppColors.blue),
            const SizedBox(width: 8),
            _statChip('Bias', advice.bias,
              advice.bias == 'BULLISH' ? AppColors.green
              : advice.bias == 'BEARISH' ? AppColors.red : AppColors.gold),
          ]),
        ],
      )),
      const SizedBox(height: 12),

      // ── ENTRY ZONES ───────────────────────────────────
      const SectionLabel('🎯  Zona Entry yang Disarankan'),
      const SizedBox(height: 8),
      ...advice.entryZones.map((e) => Padding(
        padding: const EdgeInsets.only(bottom: 8),
        child: _EntryCard(entry: e),
      )),
      const SizedBox(height: 8),

      // ── SUPPORT & STOP LOSS ───────────────────────────
      const SectionLabel('🛡️  Support & Stop Loss'),
      const SizedBox(height: 8),
      AppCard(child: Column(children: [
        // Stop loss terlebih dahulu
        ...advice.stopLevels.map((s) => _levelRow(
          label: s.label, price: s.price,
          color: AppColors.red,
          icon: '⛔',
          reason: s.reason,
          current: advice.currentPrice,
        )),
        if (advice.stopLevels.isNotEmpty)
          const Divider(color: AppColors.border, height: 20),
        // Support levels
        ...advice.supportLevels.take(3).map((s) => _levelRow(
          label: s.label, price: s.price,
          color: AppColors.green,
          icon: '🟢',
          reason: s.reason,
          current: advice.currentPrice,
        )),
      ])),
      const SizedBox(height: 12),

      // ── TARGET LEVELS ─────────────────────────────────
      const SectionLabel('🎯  Target Take Profit'),
      const SizedBox(height: 8),
      AppCard(child: Column(children: [
        ...advice.targetLevels.map((t) => _levelRow(
          label: t.label, price: t.price,
          color: t.type == 'ai' ? AppColors.purple : AppColors.gold,
          icon: t.type == 'ai' ? '🤖' : '⭐',
          reason: t.reason,
          current: advice.currentPrice,
        )),
      ])),
      const SizedBox(height: 12),

      // ── ARGUMEN & ALASAN ──────────────────────────────
      const SectionLabel('📋  Argumen & Dasar Analisis'),
      const SizedBox(height: 8),
      ...advice.arguments.map((a) => Padding(
        padding: const EdgeInsets.only(bottom: 8),
        child: _ArgumentCard(argument: a),
      )),
      const SizedBox(height: 12),

      // ── DISCLAIMER ────────────────────────────────────
      Container(
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          color: AppColors.surface2,
          borderRadius: BorderRadius.circular(8),
          border: Border.all(color: AppColors.border),
        ),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          const Text('⚠️ ', style: TextStyle(fontSize: 14)),
          Expanded(child: Text(
            advice.riskNote,
            style: const TextStyle(
              fontSize: 11, color: AppColors.textSecondary, height: 1.5),
          )),
        ]),
      ),
      const SizedBox(height: 80),
    ],
  );

  // ── HELPERS ─────────────────────────────────────────────
  Widget _statChip(String label, String value, Color color) => Expanded(
    child: Container(
      padding: const EdgeInsets.symmetric(vertical: 8, horizontal: 6),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.08),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: color.withValues(alpha: 0.25)),
      ),
      child: Column(children: [
        Text(label, style: const TextStyle(
          fontSize: 9, color: AppColors.textSecondary, letterSpacing: 0.5)),
        const SizedBox(height: 3),
        Text(value, style: TextStyle(
          fontSize: 11, fontWeight: FontWeight.w700, color: color),
          textAlign: TextAlign.center, overflow: TextOverflow.ellipsis),
      ]),
    ),
  );

  Widget _levelRow({
    required String label, required double price, required Color color,
    required String icon, required String reason, required double current,
  }) {
    final diff = price - current;
    final diffPct = diff / current * 100;
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 8),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Text('$icon ', style: const TextStyle(fontSize: 13)),
          Expanded(child: Text(label,
            style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w600))),
          Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
            Text('\$${price.toStringAsFixed(2)}',
              style: TextStyle(fontSize: 14, fontWeight: FontWeight.w700,
                color: color, fontFamily: 'monospace')),
            Text('${diffPct >= 0 ? '+' : ''}${diffPct.toStringAsFixed(2)}%',
              style: TextStyle(fontSize: 10,
                color: diffPct >= 0 ? AppColors.green : AppColors.red)),
          ]),
        ]),
        const SizedBox(height: 4),
        Text(reason, style: const TextStyle(
          fontSize: 11, color: AppColors.textSecondary, height: 1.4)),
        const Divider(color: AppColors.border, height: 16),
      ]),
    );
  }
}

// ── SUB-WIDGETS ─────────────────────────────────────────────

class _HeaderCard extends StatelessWidget {
  final TradingAdvice advice;
  const _HeaderCard({required this.advice});

  @override
  Widget build(BuildContext context) {
    final isBull = advice.bias == 'BULLISH';
    final isBear = advice.bias == 'BEARISH';
    final color  = isBull ? AppColors.green : isBear ? AppColors.red : AppColors.gold;
    final bgColor = color.withValues(alpha: 0.08);
    final borderColor = color.withValues(alpha: 0.3);

    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: bgColor,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: borderColor),
      ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Text(isBull ? '🟢' : isBear ? '🔴' : '🟡',
            style: const TextStyle(fontSize: 24)),
          const SizedBox(width: 10),
          Expanded(child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text('SARAN TRADING HARIAN',
                style: TextStyle(fontSize: 9, letterSpacing: 2,
                  color: AppColors.textSecondary)),
              const SizedBox(height: 2),
              Text(advice.signal,
                style: TextStyle(fontSize: 20, fontWeight: FontWeight.w700,
                  color: color)),
            ],
          )),
          Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
            const Text('Harga Sekarang',
              style: TextStyle(fontSize: 9, color: AppColors.textSecondary)),
            Text('\$${advice.currentPrice.toStringAsFixed(2)}',
              style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700,
                color: AppColors.gold)),
          ]),
        ]),
      ]),
    );
  }
}

class _EntryCard extends StatelessWidget {
  final EntryZone entry;
  const _EntryCard({required this.entry});

  @override
  Widget build(BuildContext context) {
    final isBuy = entry.type == 'BUY';
    final color = isBuy ? AppColors.green : AppColors.red;
    final strengthColor = entry.strength == 'Kuat' ? AppColors.green
        : entry.strength == 'Moderat' ? AppColors.gold : AppColors.textSecondary;

    return AppCard(
      borderColor: color.withValues(alpha: 0.3),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
            decoration: BoxDecoration(
              color: color.withValues(alpha: 0.12),
              borderRadius: BorderRadius.circular(4),
            ),
            child: Text(entry.type,
              style: TextStyle(fontSize: 10, fontWeight: FontWeight.w700,
                color: color)),
          ),
          const SizedBox(width: 8),
          Expanded(child: Text(entry.label,
            style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w600))),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
            decoration: BoxDecoration(
              color: strengthColor.withValues(alpha: 0.1),
              borderRadius: BorderRadius.circular(4),
              border: Border.all(color: strengthColor.withValues(alpha: 0.3)),
            ),
            child: Text(entry.strength,
              style: TextStyle(fontSize: 10, color: strengthColor,
                fontWeight: FontWeight.w600)),
          ),
        ]),
        const SizedBox(height: 10),
        Row(children: [
          Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            const Text('ZONA HARGA',
              style: TextStyle(fontSize: 9, letterSpacing: 1,
                color: AppColors.textSecondary)),
            const SizedBox(height: 3),
            Text(
              '\$${entry.priceFrom.toStringAsFixed(2)} — \$${entry.priceTo.toStringAsFixed(2)}',
              style: TextStyle(fontSize: 16, fontWeight: FontWeight.w700,
                color: color, fontFamily: 'monospace'),
            ),
          ]),
        ]),
        const SizedBox(height: 8),
        Text(entry.reason,
          style: const TextStyle(fontSize: 12, color: AppColors.textSecondary,
            height: 1.5)),
      ]),
    );
  }
}

class _ArgumentCard extends StatelessWidget {
  final TradingArgument argument;
  const _ArgumentCard({required this.argument});

  @override
  Widget build(BuildContext context) {
    final color = argument.isBullish ? AppColors.green : AppColors.red;

    return AppCard(child: Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Container(
          width: 36, height: 36,
          decoration: BoxDecoration(
            color: color.withValues(alpha: 0.1),
            borderRadius: BorderRadius.circular(8),
          ),
          child: Center(child: Text(argument.icon,
            style: const TextStyle(fontSize: 18))),
        ),
        const SizedBox(width: 12),
        Expanded(child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(children: [
              Expanded(child: Text(argument.title,
                style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w600))),
              Container(
                width: 8, height: 8,
                decoration: BoxDecoration(
                  color: color, shape: BoxShape.circle),
              ),
            ]),
            const SizedBox(height: 5),
            Text(argument.description,
              style: const TextStyle(fontSize: 11,
                color: AppColors.textSecondary, height: 1.5)),
          ],
        )),
      ],
    ));
  }
}
