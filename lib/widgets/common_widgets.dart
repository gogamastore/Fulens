// lib/widgets/common_widgets.dart
import 'package:flutter/material.dart';
import 'package:shimmer/shimmer.dart';
import '../core/theme.dart';

// ── CARD CONTAINER ───────────────────────────────────────
class AppCard extends StatelessWidget {
  final Widget child;
  final EdgeInsetsGeometry? padding;
  final Color? borderColor;

  const AppCard({
    super.key, required this.child,
    this.padding, this.borderColor,
  });

  @override
  Widget build(BuildContext context) => Container(
    padding: padding ?? const EdgeInsets.all(16),
    decoration: BoxDecoration(
      color: AppColors.surface,
      borderRadius: BorderRadius.circular(12),
      border: Border.all(color: borderColor ?? AppColors.border),
    ),
    child: child,
  );
}

// ── SECTION LABEL ────────────────────────────────────────
class SectionLabel extends StatelessWidget {
  final String text;
  final Widget? trailing;

  const SectionLabel(this.text, {super.key, this.trailing});

  @override
  Widget build(BuildContext context) => Row(
    mainAxisAlignment: MainAxisAlignment.spaceBetween,
    children: [
      Text(
        text.toUpperCase(),
        style: const TextStyle(
          fontSize: 10, letterSpacing: 1.5,
          color: AppColors.textSecondary, fontWeight: FontWeight.w600,
        ),
      ),
      if (trailing != null) trailing!,
    ],
  );
}

// ── SIGNAL BADGE ─────────────────────────────────────────
class SignalBadge extends StatelessWidget {
  final String signal;
  final double fontSize;

  const SignalBadge(this.signal, {super.key, this.fontSize = 11});

  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
    decoration: BoxDecoration(
      color: signal.signalBgColor,
      borderRadius: BorderRadius.circular(20),
      border: Border.all(color: signal.signalColor.withValues(alpha: 0.3)),
    ),
    child: Text(
      signal,
      style: TextStyle(
        color: signal.signalColor,
        fontSize: fontSize,
        fontWeight: FontWeight.w700,
        letterSpacing: 0.5,
      ),
    ),
  );
}

// ── KPI CARD ─────────────────────────────────────────────
class KpiCard extends StatelessWidget {
  final String label, value;
  final String? subtitle, delta;
  final Color? valueColor, deltaColor;
  final IconData? icon;

  const KpiCard({
    super.key,
    required this.label, required this.value,
    this.subtitle, this.delta,
    this.valueColor, this.deltaColor,
    this.icon,
  });

  @override
  Widget build(BuildContext context) => AppCard(
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(children: [
          if (icon != null) ...[
            Icon(icon, size: 14, color: AppColors.textSecondary),
            const SizedBox(width: 4),
          ],
          Text(label.toUpperCase(),
            style: const TextStyle(
              fontSize: 9, letterSpacing: 1.5,
              color: AppColors.textSecondary,
            ),
          ),
        ]),
        const SizedBox(height: 8),
        Text(value,
          style: TextStyle(
            fontSize: 22, fontWeight: FontWeight.w700,
            color: valueColor ?? AppColors.textPrimary,
          ),
        ),
        if (subtitle != null) ...[
          const SizedBox(height: 2),
          Text(subtitle!, style: const TextStyle(
            fontSize: 11, color: AppColors.textSecondary,
          )),
        ],
        if (delta != null) ...[
          const SizedBox(height: 6),
          Text(delta!, style: TextStyle(
            fontSize: 12, color: deltaColor ?? AppColors.textSecondary,
          )),
        ],
      ],
    ),
  );
}

// ── SHIMMER LOADING ───────────────────────────────────────
class ShimmerBox extends StatelessWidget {
  final double width, height;
  final double borderRadius;

  const ShimmerBox({
    super.key,
    this.width = double.infinity,
    required this.height,
    this.borderRadius = 8,
  });

  @override
  Widget build(BuildContext context) => Shimmer.fromColors(
    baseColor: AppColors.surface2,
    highlightColor: AppColors.border,
    child: Container(
      width: width, height: height,
      decoration: BoxDecoration(
        color: AppColors.surface2,
        borderRadius: BorderRadius.circular(borderRadius),
      ),
    ),
  );
}

class ShimmerCard extends StatelessWidget {
  final double height;
  const ShimmerCard({super.key, this.height = 100});

  @override
  Widget build(BuildContext context) => AppCard(
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        ShimmerBox(height: 10, width: 80),
        const SizedBox(height: 10),
        ShimmerBox(height: 24, width: 140),
        const SizedBox(height: 8),
        ShimmerBox(height: 10, width: 100),
      ],
    ),
  );
}

// ── ERROR WIDGET ─────────────────────────────────────────
class ErrorCard extends StatelessWidget {
  final String message;
  final VoidCallback? onRetry;

  const ErrorCard({super.key, required this.message, this.onRetry});

  @override
  Widget build(BuildContext context) => AppCard(
    borderColor: AppColors.red.withValues(alpha: 0.3),
    child: Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        const Icon(Icons.wifi_off_rounded, color: AppColors.red, size: 32),
        const SizedBox(height: 8),
        Text(
          message,
          textAlign: TextAlign.center,
          style: const TextStyle(fontSize: 13, color: AppColors.textSecondary),
        ),
        if (onRetry != null) ...[
          const SizedBox(height: 12),
          TextButton(
            onPressed: onRetry,
            child: const Text('Coba Lagi', style: TextStyle(color: AppColors.gold)),
          ),
        ],
      ],
    ),
  );
}

// ── PROGRESS BAR ─────────────────────────────────────────
class LabeledProgress extends StatelessWidget {
  final String label, valueLabel;
  final double value; // 0.0 - 1.0
  final Color color;

  const LabeledProgress({
    super.key,
    required this.label, required this.valueLabel,
    required this.value, required this.color,
  });

  @override
  Widget build(BuildContext context) => Column(
    children: [
      Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Text(label, style: const TextStyle(fontSize: 12, color: AppColors.textSecondary)),
          Text(valueLabel, style: TextStyle(fontSize: 12, color: color, fontWeight: FontWeight.w600)),
        ],
      ),
      const SizedBox(height: 5),
      ClipRRect(
        borderRadius: BorderRadius.circular(3),
        child: LinearProgressIndicator(
          value: value.clamp(0.0, 1.0),
          backgroundColor: AppColors.surface2,
          valueColor: AlwaysStoppedAnimation(color),
          minHeight: 6,
        ),
      ),
    ],
  );
}

// ── INDICATOR ROW ────────────────────────────────────────
class IndicatorRow extends StatelessWidget {
  final String name, valueStr, signal, detail;

  const IndicatorRow({
    super.key,
    required this.name, required this.valueStr,
    required this.signal, required this.detail,
  });

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.symmetric(vertical: 10),
    child: Row(children: [
      Expanded(
        flex: 3,
        child: Text(name, style: const TextStyle(
          fontSize: 13, color: AppColors.textSecondary,
        )),
      ),
      Expanded(
        flex: 2,
        child: Text(valueStr,
          textAlign: TextAlign.right,
          style: const TextStyle(
            fontSize: 13, fontWeight: FontWeight.w600,
          ),
        ),
      ),
      const SizedBox(width: 8),
      SignalBadge(signal),
    ]),
  );
}

// ── GOLD PRICE HEADER ─────────────────────────────────────
class GoldPriceHeader extends StatelessWidget {
  final double price, changePct;
  final String timestamp;
  final bool isLive;

  const GoldPriceHeader({
    super.key,
    required this.price, required this.changePct,
    required this.timestamp, this.isLive = true,
  });

  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
    decoration: const BoxDecoration(
      color: AppColors.surface,
      border: Border(bottom: BorderSide(color: AppColors.border)),
    ),
    child: Row(children: [
      // Logo
      RichText(text: const TextSpan(
        children: [
          TextSpan(text: '⬡ ', style: TextStyle(color: AppColors.gold, fontSize: 18)),
          TextSpan(text: 'FuLens',
            style: TextStyle(color: AppColors.gold, fontSize: 18, fontWeight: FontWeight.w700)),
        ],
      )),
      const Spacer(),
      // Live dot
      if (isLive) ...[
        _LiveDot(),
        const SizedBox(width: 6),
      ],
      // Price
      Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
        Text('\$${price.toStringAsFixed(2)}',
          style: const TextStyle(
            fontSize: 20, fontWeight: FontWeight.w700,
            color: AppColors.gold,
          ),
        ),
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
          decoration: BoxDecoration(
            color: changePct >= 0 ? AppColors.greenBg : AppColors.redBg,
            borderRadius: BorderRadius.circular(4),
          ),
          child: Text(
            '${changePct >= 0 ? '+' : ''}${changePct.toStringAsFixed(2)}%',
            style: TextStyle(
              fontSize: 11, fontWeight: FontWeight.w700,
              color: changePct >= 0 ? AppColors.green : AppColors.red,
            ),
          ),
        ),
      ]),
    ]),
  );
}

class _LiveDot extends StatefulWidget {
  @override
  State<_LiveDot> createState() => _LiveDotState();
}

class _LiveDotState extends State<_LiveDot> with SingleTickerProviderStateMixin {
  late AnimationController _ctrl;
  late Animation<double> _anim;

  @override
  void initState() {
    super.initState();
    _ctrl = AnimationController(vsync: this, duration: const Duration(seconds: 1))
      ..repeat(reverse: true);
    _anim = Tween(begin: 0.3, end: 1.0).animate(_ctrl);
  }

  @override
  void dispose() { _ctrl.dispose(); super.dispose(); }

  @override
  Widget build(BuildContext context) => FadeTransition(
    opacity: _anim,
    child: Container(
      width: 6, height: 6,
      decoration: const BoxDecoration(
        color: AppColors.green,
        shape: BoxShape.circle,
      ),
    ),
  );
}
