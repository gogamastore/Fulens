// lib/core/theme.dart
import 'package:flutter/material.dart';

class AppColors {
  // ── Brand ──
  static const gold       = Color(0xFFC9A84C);
  static const goldLight  = Color(0xFFE8C96A);
  static const goldDim    = Color(0xFF7A5F2A);

  // ── Background ──
  static const bg         = Color(0xFF0A0C10);
  static const surface    = Color(0xFF111318);
  static const surface2   = Color(0xFF181C24);
  static const border     = Color(0xFF252A35);

  // ── Text ──
  static const textPrimary   = Color(0xFFE8EAF0);
  static const textSecondary = Color(0xFF6B7280);

  // ── Signal ──
  static const green  = Color(0xFF22C55E);
  static const red    = Color(0xFFEF4444);
  static const blue   = Color(0xFF3B82F6);
  static const purple = Color(0xFFA78BFA);

  // ── Signal Background ──
  static Color greenBg  = green.withValues(alpha: 0.12);
  static Color redBg    = red.withValues(alpha: 0.12);
  static Color goldBg   = gold.withValues(alpha: 0.12);
  static Color blueBg   = blue.withValues(alpha: 0.12);
  static Color purpleBg = purple.withValues(alpha: 0.12);
}

class AppTheme {
  static ThemeData get dark => ThemeData(
    brightness: Brightness.dark,
    scaffoldBackgroundColor: AppColors.bg,
    colorScheme: const ColorScheme.dark(
      primary:   AppColors.gold,
      secondary: AppColors.goldLight,
      surface:   AppColors.surface,
      error:     AppColors.red,
    ),
    textTheme: ThemeData.dark().textTheme.apply(
      bodyColor:    AppColors.textPrimary,
      displayColor: AppColors.textPrimary,
    ),
    appBarTheme: const AppBarTheme(
      backgroundColor: AppColors.surface,
      elevation: 0,
      centerTitle: false,
      titleTextStyle: TextStyle(
        color: AppColors.textPrimary,
        fontSize: 16,
        fontWeight: FontWeight.w600,
      ),
      iconTheme: IconThemeData(color: AppColors.textPrimary),
    ),
    cardTheme: CardThemeData(
      color: AppColors.surface,
      elevation: 0,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(12),
        side: const BorderSide(color: AppColors.border),
      ),
    ),
    dividerTheme: const DividerThemeData(
      color: AppColors.border,
      thickness: 1,
    ),
    navigationBarTheme: NavigationBarThemeData(
      backgroundColor: AppColors.surface,
      indicatorColor: AppColors.goldBg,
      labelTextStyle: WidgetStateProperty.all(
        const TextStyle(fontSize: 11, color: AppColors.textSecondary),
      ),
    ),
  );
}

class AppConstants {
  // Ganti dengan IP komputer kamu jika test di HP fisik
  // Jika test di emulator Android: gunakan 10.0.2.2
  // Jika test di Windows: gunakan localhost
  // Ganti sesuai platform:
  // static const String baseUrl = 'http://10.0.2.2:8000';     // Emulator Android
  static const String baseUrl = 'http://localhost:8000';        // Windows Desktop
  // static const String baseUrl = 'http://192.168.x.x:8000';  // HP fisik (ganti IP LAN)

  static const Duration cacheTimeout   = Duration(seconds: 60);
  // Harus LEBIH BESAR dari FulensConfig.TIMEOUT di executor (30s), agar Flutter
  // tidak menyerah sebelum proxy sempat mengembalikan hasil unduhan intraday.
  static const Duration requestTimeout = Duration(seconds: 35);
}

// ── Helper Extensions ──
extension SignalColor on String {
  Color get signalColor {
    if (contains('BELI')) return AppColors.green;
    if (contains('JUAL')) return AppColors.red;
    return AppColors.gold;
  }

  Color get signalBgColor {
    if (contains('BELI')) return AppColors.greenBg;
    if (contains('JUAL')) return AppColors.redBg;
    return AppColors.goldBg;
  }

  String get signalIcon {
    if (contains('BELI')) return '▲';
    if (contains('JUAL')) return '▼';
    return '◆';
  }
}

extension NumFormat on double {
  String get asCurrency => '\$${toStringAsFixed(2).replaceAllMapped(
    RegExp(r'(\d{1,3})(?=(\d{3})+(?!\d))'),
    (m) => '${m[1]},',
  )}';

  String get asPercent => '${this >= 0 ? '+' : ''}${toStringAsFixed(2)}%';
}
