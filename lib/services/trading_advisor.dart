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
    // Semua nilai di bawah HARUS ada di payload otak. Fallback-nya sengaja
    // dibuat kentara, bukan angka yang terlihat masuk akal: dulu 'EMA 20' yang
    // hilang diam-diam jatuh ke `cur`, sehingga advisor menyodorkan "support"
    // tepat di harga sekarang dan `cur > ema20` selalu false → selamanya bilang
    // "Death Stack". Fiksi yang terlihat meyakinkan lebih berbahaya daripada
    // data kosong. RSI/EMA20/EMA50 sudah TIDAK ADA lagi — strateginya cuma 4
    // komponen (BB, S&R, Stochastic, MACD), jadi advisor ikut memakai itu.
    final atr      = _getIndicatorValue(indicators, 'ATR (14)') ?? cur * 0.008;
    final bbUpper  = _getIndicatorValue(indicators, 'BB Atas');
    final bbLower  = _getIndicatorValue(indicators, 'BB Bawah');
    final stochK   = _getIndicatorValue(indicators, 'Stochastic %K');

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

    // Zona entry dibangun dari level yang BENAR-BENAR dipakai bot: S&R dari
    // pivot fractal dan Bollinger Band. Versi lama memakai EMA 20 sebagai
    // "support dinamis utama" — indikator yang kini tak dihitung otak dan tak
    // pernah dilihat bot saat memutuskan entry.
    if (isBullish || bias == 'NETRAL') {
      // Entry 1: Pullback ke Major Support — ini lokasi yang dinilai gerbang
      // "Sentuh S&R" pada swing mode.
      if (signal.support.isNotEmpty) {
        final s1 = signal.support.first;
        entries.add(EntryZone(
          label: 'Entry Utama (Buy)',
          type: 'BUY',
          priceFrom: s1 - atr * 0.2,
          priceTo: s1 + atr * 0.5,
          strength: 'Kuat',
          reason: 'Major support \$${s1.toStringAsFixed(2)} dari swing low '
              'terdahulu — level yang dipakai bot untuk menilai lokasi entry. '
              'Tunggu Stochastic menyilang ke atas sebagai pelatuk, jangan '
              'entry hanya karena harga menyentuh level.',
        ));
      }

      // Entry 2: BB bawah saat Stochastic oversold.
      if (bbLower != null && stochK != null && stochK < 30) {
        entries.add(EntryZone(
          label: 'Entry Agresif (Buy Dip)',
          type: 'BUY',
          priceFrom: bbLower - atr * 0.1,
          priceTo: bbLower + atr * 0.3,
          strength: 'Moderat',
          reason: 'Stochastic %K ${stochK.toStringAsFixed(1)} di area oversold '
              'dan harga mendekati batas bawah Bollinger Band. '
              'Potensi reversal jangka pendek — risiko lebih tinggi karena '
              'belum ada konfirmasi pelatuk.',
        ));
      }
    }

    if (isBearish) {
      if (signal.resistance.isNotEmpty) {
        final r1 = signal.resistance.first;
        entries.add(EntryZone(
          label: 'Entry Utama (Sell)',
          type: 'SELL',
          priceFrom: r1 - atr * 0.3,
          priceTo: r1 + atr * 0.2,
          strength: 'Kuat',
          reason: 'Major resistance \$${r1.toStringAsFixed(2)} dari swing high '
              'terdahulu. Harga cenderung tertolak di area ini. '
              'Tunggu Stochastic menyilang ke bawah sebagai pelatuk.',
        ));
      }

      if (bbUpper != null && stochK != null && stochK > 70) {
        entries.add(EntryZone(
          label: 'Entry Agresif (Sell Rally)',
          type: 'SELL',
          priceFrom: bbUpper - atr * 0.3,
          priceTo: bbUpper + atr * 0.1,
          strength: 'Moderat',
          reason: 'Stochastic %K ${stochK.toStringAsFixed(1)} di area overbought '
              'dan harga mendekati batas atas Bollinger Band. '
              'Sell on rally — belum ada konfirmasi pelatuk.',
        ));
      }
    }

    // ── SUPPORT LEVELS ────────────────────────────────────
    final supports = <TradingLevel>[];

    // Support dari swing low (pivot fractal) — inilah level yang dipakai bot.
    // Versi lama menaruh EMA 20 & EMA 50 sebagai S1/S2; keduanya sudah tidak
    // dihitung otak, sehingga jatuh ke `cur` dan menampilkan "support" tepat di
    // harga sekarang — level yang mustahil berguna.
    for (int i = 0; i < signal.support.length && i < 3; i++) {
      supports.add(TradingLevel(
        label: 'S${i + 1} — Major Support',
        price: signal.support[i],
        type: 'historical',
        reason: i == 0
            ? 'Support terdekat dari swing low terdahulu. Ini level yang dinilai '
              'bot lewat gerbang "Sentuh S&R" untuk menentukan lokasi entry.'
            : 'Support historis lapis ${i + 1}. Area konsentrasi order beli '
              'bila level di atasnya tertembus.',
      ));
    }

    // BB bawah sebagai support volatilitas (dinamis, bukan struktural).
    if (bbLower != null) {
      supports.add(TradingLevel(
        label: 'S${supports.length + 1} — BB Bawah',
        price: bbLower,
        type: 'volatility',
        reason: 'Batas bawah volatilitas normal. Harga menembus ke bawah sini '
            'menandakan kondisi oversold ekstrem.',
      ));
    }

    if (supports.isEmpty) {
      supports.add(TradingLevel(
        label: 'Belum ada support terdeteksi',
        price: cur,
        type: 'none',
        reason: 'Otak belum menemukan swing low di bawah harga saat ini pada '
            'timeframe ini. Jangan mengarang level — tunggu struktur terbentuk.',
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
      if (bbUpper != null && bbUpper > cur && (bbUpper - cur) <= maxRise) {
        targets.add(TradingLevel(
          label: 'T3 — BB Atas',
          price: bbUpper,
          type: 'volatility',
          reason: 'Batas atas volatilitas normal '
              '(${((bbUpper - cur) / cur * 100).toStringAsFixed(1)}% di atas). '
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

      // Target EMA 50 dihapus — EMA sudah tidak dihitung otak. Struktur S&R
      // di bawah (T2/T5) sudah mengisi peran "support menengah" ini dengan
      // level yang benar-benar ada, bukan garis rata-rata.

      // Target 4: Bollinger Band bawah HANYA jika dalam jangkauan 8%
      if (bbLower != null && bbLower < cur && (cur - bbLower) <= maxDrop) {
        targets.add(TradingLevel(
          label: 'T4 — BB Bawah',
          price: bbLower,
          type: 'volatility',
          reason: 'Batas bawah volatilitas normal '
              '(${((cur - bbLower) / cur * 100).toStringAsFixed(1)}% di bawah). '
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
      stochK: stochK, isBullish: isBullish, isBearish: isBearish,
    );

    // ── RISK/REWARD ───────────────────────────────────────
    final potentialProfit = (target1d - cur).abs();
    final potentialRisk   = (slTight - cur).abs();
    final rrr = potentialRisk > 0 ? potentialProfit / potentialRisk : 0.0;

    // ── SUMMARY ───────────────────────────────────────────
    final summary = _buildSummary(
      bias: bias, signal: signal, cur: cur, target1d: target1d,
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
    required double? stochK,
    required bool isBullish, required bool isBearish,
  }) {
    final args = <TradingArgument>[];

    // Argumen 1: Status gerbang konfluensi — menggantikan "Tren EMA".
    // EMA sudah tidak dihitung otak; lagipula "harga di atas EMA20" bukan hal
    // yang dilihat bot saat memutuskan. Yang menentukan: gerbang mana yang lolos.
    final blocker = signal.blocker;
    final allPass = signal.gatesTotal > 0 && blocker == null;
    args.add(TradingArgument(
      icon: '🚦',
      title: 'Gerbang Setup (${signal.mode == 'scalping' ? 'Scalping' : 'Swing'}): '
             '${signal.gatesPassed}/${signal.gatesTotal} lolos',
      description: allPass
          ? 'Semua syarat setup terpenuhi. Strateginya rantai AND — semua '
            'gerbang harus lolos, dan saat ini memang lolos semua. '
            'Arah: ${signal.direction ?? "-"}.'
          : blocker == null
          ? 'Belum ada data gerbang dari otak.'
          : 'Setup ditahan di gerbang "${blocker.name}" — ${blocker.detail}. '
            'Selama gerbang ini belum lolos, bot TIDAK akan entry, berapa pun '
            'meyakinkannya indikator lain.',
      isBullish: allPass && signal.direction == 'BUY',
    ));

    // Argumen 2: Stochastic — menggantikan "RSI Momentum" (RSI sudah dibuang).
    if (stochK != null) {
      final status = stochK < 20 ? 'Oversold' : stochK > 80 ? 'Overbought' : 'Netral';
      args.add(TradingArgument(
        icon: '⚡',
        title: 'Stochastic %K: $status (${stochK.toStringAsFixed(1)})',
        description: stochK < 20
            ? 'Stochastic di bawah 20 — area oversold. Tekanan jual mulai '
              'kehabisan tenaga, tapi oversold saja bukan sinyal beli: '
              'di tren turun, %K bisa bertahan rendah lama.'
            : stochK > 80
            ? 'Stochastic di atas 80 — area overbought. Momentum beli mulai '
              'jenuh. Pertimbangkan take profit; jangan buka beli baru '
              'tanpa konfirmasi.'
            : 'Stochastic di ${stochK.toStringAsFixed(0)} — belum ada kondisi '
              'jenuh di kedua sisi. Momentum netral.',
        isBullish: stochK < 20,
      ));
    }

    // Argumen 3: Kualitas setup — menggantikan "Konsensus Indikator".
    // Otak tidak lagi memungut suara, jadi "N Beli vs M Jual" tak punya arti.
    args.add(TradingArgument(
      icon: '🎯',
      title: 'Kualitas Setup: ${signal.confidence.toStringAsFixed(0)}%',
      description: signal.direction == null
          ? 'Belum ada setup yang lolos, jadi belum ada kualitas untuk dinilai. '
            'Kualitas bukan hasil hitung suara indikator — ia mengukur seberapa '
            'BAIK tiap syarat dipenuhi setelah semuanya lolos.'
          : 'Setup ${signal.direction} dengan kualitas '
            '${signal.confidence.toStringAsFixed(0)}%. Angka ini mengukur '
            'seberapa baik tiap gerbang dipenuhi — bukan berapa banyak '
            'indikator yang setuju. Di bawah min_confidence, bot menolak entry.',
      isBullish: signal.direction == 'BUY',
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

    // Argumen 7: MACD — KONTEKS SAJA, bukan gerbang.
    // MACD sudah dicabut dari kedua rantai gerbang: diuji ke depan ia rugi di
    // swing (-0.39R) maupun scalping (-0.25R). Sebabnya struktural — ia dan
    // Stochastic sama-sama osilator momentum dari deret harga yang sama, jadi
    // menggandengkannya cuma konfirmasi berulang. Tetap ditampilkan sebagai
    // bacaan pasar, tapi teksnya TIDAK BOLEH menyiratkan bot memakainya.
    final macd = indicators.signals.where((s) => s.name == 'MACD').firstOrNull;
    if (macd != null) {
      args.add(TradingArgument(
        icon: '🔄',
        title: 'MACD: ${macd.signal} (${macd.value.toStringAsFixed(2)})',
        description: '${macd.signal == 'BELI'
            ? 'MACD line di atas signal line dengan histogram positif — '
                'momentum bullish sedang membangun.'
            : 'MACD line di bawah signal line — tekanan jual dominan '
                'secara momentum.'} '
            'Catatan: bot TIDAK memakai MACD sebagai syarat entry; ini bacaan '
            'pasar tambahan, bukan gerbang.',
        isBullish: macd.signal == 'BELI',
      ));
    }

    return args;
  }

  static String _buildSummary({
    required String bias, required SignalData signal,
    required double cur, required double target1d,
  }) {
    final direction = target1d > cur ? 'naik' : 'turun';
    final chgPct = ((target1d - cur) / cur * 100).abs();
    final modeLabel = signal.mode == 'scalping' ? 'scalping' : 'swing';
    final blocker = signal.blocker;

    // Kalimat "mayoritas indikator teknikal" dan bagian RSI/EMA dibuang: otak
    // tidak lagi memungut suara indikator, dan RSI/EMA sudah tidak dihitung.
    final setupPart = blocker == null && signal.gatesTotal > 0
        ? 'Semua ${signal.gatesTotal} gerbang setup $modeLabel lolos '
          '(kualitas ${signal.confidence.toStringAsFixed(0)}%), arah '
          '${signal.direction ?? "-"}.'
        : blocker == null
        ? 'Data gerbang setup belum tersedia dari otak.'
        : 'Setup $modeLabel belum terbentuk — '
          '${signal.gatesPassed}/${signal.gatesTotal} gerbang lolos, '
          'tertahan di "${blocker.name}". Bot tidak akan entry sampai '
          'gerbang ini terpenuhi.';

    return 'Bias pasar emas hari ini: $bias. $setupPart '
        'Terpisah dari itu, model prediksi (LSTM + XGBoost) memperkirakan harga '
        'berpotensi $direction ${chgPct.toStringAsFixed(2)}% ke '
        '\$${target1d.toStringAsFixed(2)} dalam 24 jam ke depan — ini proyeksi '
        'harga, bukan sinyal entry; keputusan entry sepenuhnya dari gerbang.';
  }
}
