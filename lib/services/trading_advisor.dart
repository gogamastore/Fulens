// lib/services/trading_advisor.dart
import 'api_service.dart';

/// Menghasilkan saran trading harian berdasarkan data prediksi,
/// indikator teknikal, dan data fundamental.
class TradingAdvisor {

  static TradingAdvice generate({
    required GoldPrice price,
    required SignalData signal,
    required PredictionData prediction,
    required IndicatorData indicators,
  }) {
    final cur = price.price;
    final atr = _getIndicatorValue(indicators, 'ATR (14)') ?? cur * 0.008;
    final rsi = _getIndicatorValue(indicators, 'RSI (14)') ?? 50.0;
    final bb_upper = _getIndicatorValue(indicators, 'BB Atas') ?? cur * 1.02;
    final bb_lower = _getIndicatorValue(indicators, 'BB Bawah') ?? cur * 0.98;
    final ema20 = _getIndicatorValue(indicators, 'EMA 20') ?? cur;
    final ema50 = _getIndicatorValue(indicators, 'EMA 50') ?? cur;

    // Tentukan bias
    final isBullish = signal.signal.contains('BELI');
    final isBearish = signal.signal.contains('JUAL');
    final bias = isBullish ? 'BULLISH' : isBearish ? 'BEARISH' : 'NETRAL';

    // Prediksi 1 hari & 7 hari
    final p1d = prediction.predictions.where((p) => p.horizonDays == 1).firstOrNull;
    final p7d = prediction.predictions.where((p) => p.horizonDays == 7).firstOrNull;
    final target1d = p1d?.predictedPrice ?? cur;
    final target7d = p7d?.predictedPrice ?? cur;

    // ── ENTRY ZONES ──────────────────────────────────────
    final entries = <EntryZone>[];

    if (isBullish || bias == 'NETRAL') {
      // Entry 1: Di sekitar EMA 20 (support dinamis)
      entries.add(EntryZone(
        label: 'Entry Utama (Buy)',
        type: 'BUY',
        priceFrom: ema20 - atr * 0.3,
        priceTo: ema20 + atr * 0.2,
        strength: 'Kuat',
        reason: 'Area EMA 20 sebagai support dinamis utama. '
            'Harga sering rebound dari level ini pada tren bullish.',
      ));

      // Entry 2: Di Bollinger Band bawah (oversold area)
      if (rsi < 45) {
        entries.add(EntryZone(
          label: 'Entry Agresif (Buy Dip)',
          type: 'BUY',
          priceFrom: bb_lower - atr * 0.1,
          priceTo: bb_lower + atr * 0.3,
          strength: 'Moderat',
          reason: 'RSI ${rsi.toStringAsFixed(1)} mendekati area oversold. '
              'Bollinger Band bawah sebagai support volatilitas. '
              'Potensi reversal jangka pendek.',
        ));
      }

      // Entry 3: Pullback ke support
      if (signal.support.isNotEmpty) {
        final s1 = signal.support.first;
        entries.add(EntryZone(
          label: 'Entry Konservatif (Pullback)',
          type: 'BUY',
          priceFrom: s1 - atr * 0.2,
          priceTo: s1 + atr * 0.5,
          strength: 'Kuat',
          reason: 'Level support historis terkuat. '
              'Tunggu konfirmasi candle bullish (hammer/engulfing) '
              'sebelum entry untuk risk yang lebih rendah.',
        ));
      }
    }

    if (isBearish) {
      // Entry Sell
      entries.add(EntryZone(
        label: 'Entry Utama (Sell)',
        type: 'SELL',
        priceFrom: ema20 - atr * 0.2,
        priceTo: ema20 + atr * 0.3,
        strength: 'Kuat',
        reason: 'EMA 20 bertindak sebagai resistance dinamis pada tren bearish. '
            'Sell on rally ke level ini.',
      ));

      if (signal.resistance.isNotEmpty) {
        final r1 = signal.resistance.first;
        entries.add(EntryZone(
          label: 'Entry Resistance (Sell)',
          type: 'SELL',
          priceFrom: r1 - atr * 0.3,
          priceTo: r1 + atr * 0.2,
          strength: 'Moderat',
          reason: 'Level resistance historis. Harga cenderung tertolak di area ini. '
              'Tunggu konfirmasi candle bearish.',
        ));
      }
    }

    // ── SUPPORT LEVELS ────────────────────────────────────
    final supports = <TradingLevel>[];

    // Support 1: EMA 20
    supports.add(TradingLevel(
      label: 'S1 — EMA 20',
      price: ema20,
      type: 'dynamic',
      reason: 'Support dinamis utama. Selama harga di atas EMA 20, '
          'tren jangka pendek masih bullish.',
    ));

    // Support 2: EMA 50
    supports.add(TradingLevel(
      label: 'S2 — EMA 50',
      price: ema50,
      type: 'dynamic',
      reason: 'Support menengah yang lebih kuat. Penembusan ke bawah level ini '
          'mengindikasikan perubahan tren jangka menengah.',
    ));

    // Support 3: Bollinger Band bawah
    supports.add(TradingLevel(
      label: 'S3 — BB Bawah',
      price: bb_lower,
      type: 'volatility',
      reason: 'Batas bawah volatilitas normal. Harga di bawah BB bawah '
          'mengindikasikan kondisi oversold yang ekstrem.',
    ));

    // Support historis dari API
    for (int i = 0; i < signal.support.length && i < 2; i++) {
      supports.add(TradingLevel(
        label: 'S${i + 4} — Support Historis',
        price: signal.support[i],
        type: 'historical',
        reason: 'Level support historis berdasarkan swing low terdahulu. '
            'Area konsentrasi order beli yang kuat.',
      ));
    }

    // ── TARGET LEVELS ─────────────────────────────────────
    // Logika target berbeda untuk BUY vs SELL:
    // BUY  → target di ATAS harga (resistance, BB atas)
    // SELL → target di BAWAH harga (support, BB bawah)
    final targets = <TradingLevel>[];

    if (!isBearish) {
      // ── TARGET UNTUK BUY ──────────────────────────────
      // Target 1: Prediksi AI 1 hari
      if (target1d > cur) {
        targets.add(TradingLevel(
          label: 'T1 — Target Harian (AI)',
          price: target1d,
          type: 'ai',
          reason: 'Proyeksi harga naik 1 hari dari model LSTM + XGBoost. '
              'Take profit sebagian di level ini jika tercapai dalam sesi hari ini.',
        ));
      }

      // Filter: target BUY harus di atas harga, max 8% dari harga saat ini
      final maxRise = cur * 0.08;

      // Target 2: Resistance terdekat yang REALISTIS (dalam jangkauan 8%)
      final r1above = signal.resistance
          .where((r) => r > cur && (r - cur) <= maxRise)
          .toList()..sort();
      if (r1above.isNotEmpty) {
        targets.add(TradingLevel(
          label: 'T2 — Resistance Terdekat',
          price: r1above.first,
          type: 'resistance',
          reason: 'Level resistance historis terdekat yang realistis '
              '(${((r1above.first - cur) / cur * 100).toStringAsFixed(1)}% di atas harga). '
              'Area tekanan jual meningkat. Partial take profit 50% di sini.',
        ));
      }

      // Target 3: Bollinger Band atas (jika dalam jangkauan)
      if (bb_upper > cur && (bb_upper - cur) <= maxRise) {
        targets.add(TradingLevel(
          label: 'T3 — BB Atas',
          price: bb_upper,
          type: 'volatility',
          reason: 'Batas atas volatilitas normal '
              '(${((bb_upper - cur) / cur * 100).toStringAsFixed(1)}% di atas). '
              'Kondisi overbought. Ideal untuk full take profit.',
        ));
      }

      // Target 4: Prediksi AI 7 hari (hanya jika lebih tinggi dan realistis)
      if (target7d > cur && target7d > target1d && (target7d - cur) <= maxRise) {
        targets.add(TradingLevel(
          label: 'T4 — Target Mingguan (AI)',
          price: target7d,
          type: 'ai',
          reason: 'Proyeksi harga naik 7 hari dari model AI '
              '(${((target7d - cur) / cur * 100).toStringAsFixed(1)}% di atas). '
              'Target swing trader.',
        ));
      }

      // Target 5: Resistance mayor ke-2 yang realistis
      if (r1above.length > 1) {
        targets.add(TradingLevel(
          label: 'T5 — Resistance Mayor',
          price: r1above[1],
          type: 'resistance',
          reason: 'Resistance historis mayor '
              '(${((r1above[1] - cur) / cur * 100).toStringAsFixed(1)}% di atas). '
              'Target jangka menengah.',
        ));
      }

    } else {
      // ── TARGET UNTUK SELL ─────────────────────────────
      // Semua target harus di BAWAH harga saat ini

      // Target 1: Prediksi AI 1 hari (harus di bawah harga)
      if (target1d < cur) {
        targets.add(TradingLevel(
          label: 'T1 — Target Harian (AI)',
          price: target1d,
          type: 'ai',
          reason: 'Proyeksi harga turun 1 hari dari model LSTM + XGBoost. '
              'Take profit sebagian di level ini jika tercapai dalam sesi hari ini.',
        ));
      }

      // Filter: target SELL harus di bawah harga, max 8% dari harga saat ini
      final maxDrop = cur * 0.08;

      // Target 2: Support terdekat yang REALISTIS (dalam jangkauan 8%)
      final s1below = signal.support
          .where((s) => s < cur && (cur - s) <= maxDrop)
          .toList()
        ..sort((a, b) => b.compareTo(a)); // descending: terdekat dulu
      if (s1below.isNotEmpty) {
        targets.add(TradingLevel(
          label: 'T2 — Support Terdekat',
          price: s1below.first,
          type: 'support',
          reason: 'Level support historis terdekat yang realistis '
              '(${((cur - s1below.first) / cur * 100).toStringAsFixed(1)}% di bawah harga). '
              'Area di mana tekanan beli meningkat. '
              'Partial take profit 50% di sini.',
        ));
      }

      // Target 3: EMA 50 (jika di bawah harga dan dalam jangkauan)
      if (ema50 < cur && (cur - ema50) <= maxDrop) {
        targets.add(TradingLevel(
          label: 'T3 — EMA 50',
          price: ema50,
          type: 'dynamic',
          reason: 'EMA 50 sebagai support dinamis menengah '
              '(${((cur - ema50) / cur * 100).toStringAsFixed(1)}% di bawah). '
              'Harga sering bouncing di level ini. Take profit 75% posisi.',
        ));
      }

      // Target 4: Bollinger Band bawah HANYA jika dalam jangkauan 8%
      if (bb_lower < cur && (cur - bb_lower) <= maxDrop) {
        targets.add(TradingLevel(
          label: 'T4 — BB Bawah',
          price: bb_lower,
          type: 'volatility',
          reason: 'Batas bawah volatilitas normal '
              '(${((cur - bb_lower) / cur * 100).toStringAsFixed(1)}% di bawah). '
              'Indikasikan kondisi oversold. Full take profit di sini.',
        ));
      }

      // Target 5: Support mayor ke-2 yang realistis
      if (s1below.length > 1) {
        targets.add(TradingLevel(
          label: 'T5 — Support Mayor',
          price: s1below[1],
          type: 'support',
          reason: 'Support historis mayor '
              '(${((cur - s1below[1]) / cur * 100).toStringAsFixed(1)}% di bawah). '
              'Target untuk posisi sell yang ditahan lebih lama.',
        ));
      }

      // Target 6: Prediksi AI 7 hari (hanya jika dalam jangkauan dan lebih rendah)
      if (target7d < cur && target7d < target1d && (cur - target7d) <= maxDrop) {
        targets.add(TradingLevel(
          label: 'T6 — Target Mingguan (AI)',
          price: target7d,
          type: 'ai',
          reason: 'Proyeksi harga turun 7 hari dari model AI '
              '(${((cur - target7d) / cur * 100).toStringAsFixed(1)}% di bawah). '
              'Target swing trader bearish.',
        ));
      }
    }

    // ── STOP LOSS ─────────────────────────────────────────
    // BUY  → SL di BAWAH harga entry
    // SELL → SL di ATAS harga entry
    final stops = <TradingLevel>[];
    final slTight = isBearish ? cur + atr * 1.5 : cur - atr * 1.5;
    final slWide  = isBearish ? cur + atr * 2.5 : cur - atr * 2.5;

    final slDirection = isBearish ? 'di atas' : 'di bawah';
    final slAction    = isBearish ? 'naik menembus' : 'turun menembus';

    stops.add(TradingLevel(
      label: 'SL Ketat — 1.5× ATR',
      price: slTight,
      type: 'stop',
      reason: 'Stop loss agresif $slDirection harga entry. '
          'Cut loss jika harga $slAction level ini. '
          'ATR saat ini: \$${atr.toStringAsFixed(0)} — cocok untuk intraday.',
    ));
    stops.add(TradingLevel(
      label: 'SL Normal — 2.5× ATR',
      price: slWide,
      type: 'stop',
      reason: 'Stop loss konservatif $slDirection harga entry. '
          'Memberikan ruang gerak terhadap volatilitas normal. '
          'Cocok untuk swing trader yang menahan posisi lebih dari 1 hari.',
    ));

    // ── ARGUMEN & ALASAN ──────────────────────────────────
    final args = _buildArguments(
      price: price, signal: signal, indicators: indicators,
      rsi: rsi, ema20: ema20, ema50: ema50,
      isBullish: isBullish, isBearish: isBearish,
    );

    // ── RISK/REWARD ───────────────────────────────────────
    final potentialProfit = (target1d - cur).abs();
    final potentialRisk   = (slTight - cur).abs();
    final rrr = potentialRisk > 0 ? potentialProfit / potentialRisk : 0.0;

    // ── SUMMARY ───────────────────────────────────────────
    final summary = _buildSummary(
      bias: bias, signal: signal.signal,
      cur: cur, target1d: target1d, rsi: rsi,
      ema20: ema20, ema50: ema50,
    );

    return TradingAdvice(
      currentPrice   : cur,
      signal         : signal.signal,
      bias           : bias,
      sessionLabel   : _getSessionLabel(),
      entryZones     : entries,
      supportLevels  : supports,
      targetLevels   : targets,
      stopLevels     : stops,
      arguments      : args,
      summary        : summary,
      riskNote       : 'Trading emas memiliki risiko tinggi. '
          'Gunakan manajemen risiko ketat: maksimal 1-2% modal per trade. '
          'Saran ini bersifat edukatif, bukan rekomendasi investasi.',
      riskRewardRatio: rrr,
    );
  }

  // ── HELPERS ───────────────────────────────────────────────
  static double? _getIndicatorValue(IndicatorData ind, String name) {
    try {
      return ind.signals.firstWhere((s) => s.name == name).value;
    } catch (_) {
      return null;
    }
  }

  static String _getSessionLabel() {
    final hour = DateTime.now().toUtc().hour + 7; // WIB
    final h = hour % 24;
    if (h >= 8 && h < 12)  return 'Sesi Asia (Pagi)';
    if (h >= 12 && h < 16) return 'Sesi Eropa (Siang)';
    if (h >= 16 && h < 24) return 'Sesi New York (Malam)';
    return 'Pre-Market (Dini Hari)';
  }

  static List<TradingArgument> _buildArguments({
    required GoldPrice price,
    required SignalData signal,
    required IndicatorData indicators,
    required double rsi, required double ema20, required double ema50,
    required bool isBullish, required bool isBearish,
  }) {
    final args = <TradingArgument>[];
    final cur  = price.price;

    // Argumen 1: Tren EMA
    final emaAbove = cur > ema20 && ema20 > ema50;
    args.add(TradingArgument(
      icon: '📈',
      title: 'Tren EMA: ${emaAbove ? "Golden Stack" : "Death Stack"}',
      description: emaAbove
          ? 'Harga (\$${cur.toStringAsFixed(0)}) berada di atas EMA 20 '
            '(\$${ema20.toStringAsFixed(0)}) dan EMA 50 (\$${ema50.toStringAsFixed(0)}). '
            'Formasi "Golden Stack" mengonfirmasi tren naik jangka pendek-menengah.'
          : 'Harga berada di bawah EMA 20 atau EMA 50. '
            'Tren menunjukkan tekanan jual yang dominan. '
            'Hati-hati entry beli sebelum ada konfirmasi pembalikan.',
      isBullish: emaAbove,
    ));

    // Argumen 2: RSI Momentum
    final rsiStatus = rsi < 30 ? 'Oversold Ekstrem' : rsi < 45 ? 'Oversold Ringan'
        : rsi > 70 ? 'Overbought Ekstrem' : rsi > 60 ? 'Overbought Ringan' : 'Netral';
    args.add(TradingArgument(
      icon: '⚡',
      title: 'RSI Momentum: $rsiStatus (${rsi.toStringAsFixed(1)})',
      description: rsi < 30
          ? 'RSI di bawah 30 menandakan kondisi oversold ekstrem. '
            'Secara historis, ini area potensial reversal bullish. '
            'Tunggu konfirmasi candle pembalikan sebelum entry.'
          : rsi > 70
          ? 'RSI di atas 70 menandakan kondisi overbought. '
            'Momentum beli mulai melemah. Pertimbangkan take profit '
            'atau tunda entry beli baru.'
          : 'RSI di area ${rsi.toStringAsFixed(0)} menunjukkan momentum '
            '${rsi > 50 ? "bullish moderat" : "bearish ringan"}. '
            'Belum ada sinyal ekstrem yang perlu diwaspadai.',
      isBullish: rsi < 50,
    ));

    // Argumen 3: Indikator Dominan
    final buyCount  = signal.buyCount;
    final sellCount = signal.sellCount;
    args.add(TradingArgument(
      icon: '🎯',
      title: 'Konsensus Indikator: $buyCount Beli vs $sellCount Jual',
      description: buyCount > sellCount
          ? '$buyCount dari ${buyCount + sellCount + signal.neutralCount} '
            'indikator teknikal memberikan sinyal BELI. '
            'Konsensus mayoritas mendukung posisi long (beli). '
            'Semakin besar selisihnya, semakin kuat sinyal.'
          : '$sellCount indikator memberikan sinyal JUAL. '
            'Mayoritas indikator menekan ke sisi bearish. '
            'Hindari posisi beli melawan tren dominan.',
      isBullish: buyCount > sellCount,
    ));

    // Argumen 4: DXY
    if (price.dxy != null) {
      final dxyWeak = price.dxy! < 102;
      args.add(TradingArgument(
        icon: '💵',
        title: 'Dollar Index (DXY): ${price.dxy!.toStringAsFixed(2)}',
        description: dxyWeak
            ? 'DXY ${price.dxy!.toStringAsFixed(2)} berada di level relatif rendah '
              '(di bawah 102). Dollar yang lemah secara historis '
              'berkorelasi negatif dengan emas — mendukung kenaikan harga.'
            : 'DXY ${price.dxy!.toStringAsFixed(2)} berada di level kuat (di atas 102). '
              'Dollar yang menguat memberikan tekanan pada harga emas. '
              'Perhatikan pergerakan DXY lebih lanjut.',
        isBullish: dxyWeak,
      ));
    }

    // Argumen 5: VIX
    if (price.vix != null) {
      final vixHigh = price.vix! > 20;
      args.add(TradingArgument(
        icon: '😰',
        title: 'Sentimen Pasar (VIX): ${price.vix!.toStringAsFixed(2)}',
        description: vixHigh
            ? 'VIX ${price.vix!.toStringAsFixed(2)} di atas 20 menunjukkan '
              'tingkat ketakutan (fear) yang tinggi di pasar. '
              'Emas sebagai safe haven cenderung naik saat VIX tinggi.'
            : 'VIX ${price.vix!.toStringAsFixed(2)} rendah menandakan pasar '
              'sedang tenang dan risk-on. Emas cenderung sideways '
              'atau tertekan saat sentimen pasar positif.',
        isBullish: vixHigh,
      ));
    }

    // Argumen 6: Yield
    if (price.bond10y != null) {
      final yieldLow = price.bond10y! < 4.5;
      args.add(TradingArgument(
        icon: '📊',
        title: 'Yield UST 10Y: ${price.bond10y!.toStringAsFixed(2)}%',
        description: yieldLow
            ? 'Yield obligasi AS 10 tahun di ${price.bond10y!.toStringAsFixed(2)}% '
              'relatif moderat. Yield yang lebih rendah mengurangi '
              'opportunity cost memegang emas (tidak berbunga). Mendukung emas.'
            : 'Yield tinggi di ${price.bond10y!.toStringAsFixed(2)}% '
              'meningkatkan daya tarik obligasi dibanding emas. '
              'Tekanan potensial pada harga emas dari sisi fundamental.',
        isBullish: yieldLow,
      ));
    }

    // Argumen 7: MACD
    final macd = indicators.signals.where((s) => s.name == 'MACD').firstOrNull;
    if (macd != null) {
      args.add(TradingArgument(
        icon: '🔄',
        title: 'MACD: ${macd.signal} (${macd.value.toStringAsFixed(2)})',
        description: macd.signal == 'BELI'
            ? 'MACD line di atas signal line dengan histogram positif. '
              'Ini mengindikasikan momentum bullish yang sedang membangun. '
              'Konfirmasi kuat untuk posisi beli.'
            : 'MACD menunjukkan momentum bearish. '
              'MACD line di bawah signal line mengindikasikan '
              'tekanan jual yang dominan secara momentum.',
        isBullish: macd.signal == 'BELI',
      ));
    }

    return args;
  }

  static String _buildSummary({
    required String bias, required String signal,
    required double cur, required double target1d, required double rsi,
    required double ema20, required double ema50,
  }) {
    final direction = target1d > cur ? 'naik' : 'turun';
    final chgPct = ((target1d - cur) / cur * 100).abs();

    return 'Berdasarkan analisis ensemble AI dan ${bias == "BULLISH" ? "mayoritas" : "dominasi"} '
        'indikator teknikal, bias pasar emas hari ini adalah $bias. '
        'Model prediksi memperkirakan harga berpotensi $direction '
        '${chgPct.toStringAsFixed(2)}% ke \$${target1d.toStringAsFixed(2)} '
        'dalam 24 jam ke depan. '
        'RSI ${rsi.toStringAsFixed(0)} menunjukkan momentum ${rsi > 50 ? "positif" : "negatif"}, '
        'dengan harga ${cur > ema20 ? "di atas" : "di bawah"} EMA 20 '
        '(\$${ema20.toStringAsFixed(0)}) sebagai '
        '${cur > ema20 ? "support" : "resistance"} dinamis kunci.';
  }
}
