// lib/services/api_service.dart
import 'dart:convert';
import 'package:http/http.dart' as http;
import '../core/theme.dart';
import '../config/app_config.dart';
import '../state/selected_symbol.dart';

class ApiService {
  static final ApiService _instance = ApiService._internal();
  factory ApiService() => _instance;
  ApiService._internal();

  final String _base = AppConfig.baseUrl;
  final _timeout = AppConstants.requestTimeout;
  Map<String, String> get _headers => AppConfig.headers;

  // ── HELPER ────────────────────────────────────────────
  // Ambil pesan `detail` dari body error server (FastAPI HTTPException),
  // supaya pengguna melihat alasan sebenarnya, bukan sekadar "HTTP 503".
  Never _throwStatus(http.Response res) {
    String msg = 'HTTP ${res.statusCode}';
    try {
      final b = json.decode(res.body);
      if (b is Map && b['detail'] != null) msg = b['detail'].toString();
    } catch (_) {}
    throw Exception(msg);
  }

  Future<http.Response> _req(Future<http.Response> Function() call) async {
    try {
      return await call().timeout(_timeout);
    } catch (e) {
      // Ini kegagalan JARINGAN sesungguhnya (timeout/host tak terjangkau).
      throw Exception('Koneksi gagal: $e\nPastikan gateway di VPS berjalan.');
    }
  }

  Future<Map<String, dynamic>> _get(String path) async {
    final res = await _req(() => http.get(Uri.parse('$_base$path'), headers: _headers));
    if (res.statusCode != 200) _throwStatus(res);
    return json.decode(res.body) as Map<String, dynamic>;
  }

  Future<List<dynamic>> _getList(String path) async {
    final res = await _req(() => http.get(Uri.parse('$_base$path'), headers: _headers));
    if (res.statusCode != 200) _throwStatus(res);
    return json.decode(res.body) as List<dynamic>;
  }

  Future<Map<String, dynamic>> _send(String method, String path,
      {Object? body}) async {
    final uri = Uri.parse('$_base$path');
    final b = body != null ? json.encode(body) : null;
    final res = await _req(() => method == 'POST'
        ? http.post(uri, headers: _headers, body: b)
        : http.put(uri, headers: _headers, body: b));
    if (res.statusCode != 200) _throwStatus(res);
    return res.body.isEmpty
        ? <String, dynamic>{}
        : json.decode(res.body) as Map<String, dynamic>;
  }

  // Konteks efektif: argumen eksplisit, atau nilai global terpilih.
  String _sym(String? s) => Uri.encodeComponent(s ?? selectedSymbol);
  String _tf(String? tf) => Uri.encodeComponent(tf ?? selectedTimeframe);

  // ── PRICE ─────────────────────────────────────────────
  Future<GoldPrice> getPrice({String? symbol, String? timeframe}) async {
    final data = await _get(
        '/api/v1/price?symbol=${_sym(symbol)}&timeframe=${_tf(timeframe)}');
    return GoldPrice.fromJson(data);
  }

  // ── SIGNAL ────────────────────────────────────────────
  Future<SignalData> getSignal({String? symbol, String? timeframe}) async {
    final data = await _get(
        '/api/v1/signal?symbol=${_sym(symbol)}&timeframe=${_tf(timeframe)}');
    return SignalData.fromJson(data);
  }

  // ── PREDICTION ────────────────────────────────────────
  Future<PredictionData> getPredictions({String? symbol}) async {
    final data = await _get('/api/v1/predict?horizons=1,3,7,14,30&symbol=${_sym(symbol)}');
    return PredictionData.fromJson(data);
  }

  // ── INDICATORS ────────────────────────────────────────
  Future<IndicatorData> getIndicators({String? symbol, String? timeframe}) async {
    final data = await _get(
        '/api/v1/indicators?symbol=${_sym(symbol)}&timeframe=${_tf(timeframe)}');
    return IndicatorData.fromJson(data);
  }

  // ── MULTI-TIMEFRAME ───────────────────────────────────
  Future<MultiTFData> getMultiTimeframe({String? symbol, String? timeframe}) async {
    final data = await _get(
        '/api/v1/indicators/multitimeframe?symbol=${_sym(symbol)}&timeframe=${_tf(timeframe)}');
    return MultiTFData.fromJson(data);
  }

  // ── FUNDAMENTAL ───────────────────────────────────────
  // Fundamental bersifat makro (DXY/VIX/yield/oil) — berlaku lintas simbol.
  Future<FundamentalData> getFundamental() async {
    final data = await _get('/api/v1/fundamental');
    return FundamentalData.fromJson(data);
  }

  // ── HISTORY ───────────────────────────────────────────
  Future<List<OhlcData>> getHistory(
      {int days = 90, String? symbol, String? timeframe}) async {
    final data = await _get(
        '/api/v1/history?days=$days&symbol=${_sym(symbol)}&timeframe=${_tf(timeframe)}');
    final list = data['data'] as List;
    return list.map((e) => OhlcData.fromJson(e)).toList();
  }

  // ── DAFTAR SIMBOL ─────────────────────────────────────
  Future<List<SymbolInfo>> getSymbols() async {
    final data = await _get('/api/v1/symbols');
    final list = (data['symbols'] as List?) ?? [];
    return list.map((e) => SymbolInfo.fromJson(e as Map<String, dynamic>)).toList();
  }

  // ── TIMEFRAMES ────────────────────────────────────────
  Future<List<String>> getTimeframes() async {
    try {
      final data = await _get('/api/v1/timeframes');
      return List<String>.from(data['timeframes'] ?? const []);
    } catch (_) {
      return const ['M15', 'M30', 'H1', 'H4', 'D1', 'W1'];
    }
  }

  // ── BACKTEST ──────────────────────────────────────────
  Future<BacktestResult> getBacktest({
    String? symbol,
    String? timeframe,
    int days = 365,
    String? start,
    String? end,
    String strategy = 'ta',
  }) async {
    final q = StringBuffer('/api/v1/backtest?symbol=${_sym(symbol)}'
        '&timeframe=${_tf(timeframe)}&days=$days&strategy=$strategy');
    if (start != null) q.write('&start=$start');
    if (end != null) q.write('&end=$end');
    final data = await _get(q.toString());
    return BacktestResult.fromJson(data);
  }

  // ── HEALTH ────────────────────────────────────────────
  Future<bool> checkHealth() async {
    try {
      final data = await _get('/health');
      return data['status'] == 'ok';
    } catch (_) {
      return false;
    }
  }

  // ══════════════════════════════════════════════════════
  //  TRADING (gerbang eksekutor)
  // ══════════════════════════════════════════════════════

  /// Status bot + akun MT5.
  Future<BotStatus> getStatus() async {
    final data = await _get('/status');
    return BotStatus.fromJson(data);
  }

  Future<bool> startBot() async {
    final data = await _send('POST', '/bot/start');
    return data['running'] == true;
  }

  Future<bool> stopBot() async {
    final data = await _send('POST', '/bot/stop');
    return data['running'] == false;
  }

  /// Posisi terbuka milik bot.
  Future<List<Position>> getPositions() async {
    final list = await _getList('/positions');
    return list.map((e) => Position.fromJson(e as Map<String, dynamic>)).toList();
  }

  Future<bool> closePosition(int ticket) async {
    final data = await _send('POST', '/positions/$ticket/close');
    return data['ok'] == true;
  }

  /// Riwayat posisi tertutup bot (default 7 hari terakhir).
  Future<List<ClosedTrade>> getTradeHistory({String? from, String? to}) async {
    final q = <String>[];
    if (from != null) q.add('date_from=$from');
    if (to != null) q.add('date_to=$to');
    final qs = q.isEmpty ? '' : '?${q.join('&')}';
    final list = await _getList('/history$qs');
    return list.map((e) => ClosedTrade.fromJson(e as Map<String, dynamic>)).toList();
  }

  /// Log keputusan sinyal bot (dari FuLens).
  Future<List<BotSignal>> getBotSignals({int limit = 50}) async {
    final list = await _getList('/signals?limit=$limit');
    return list.map((e) => BotSignal.fromJson(e as Map<String, dynamic>)).toList();
  }

  Future<Map<String, dynamic>> getBotSettings() => _get('/settings');

  Future<Map<String, dynamic>> updateBotSettings(Map<String, dynamic> s) =>
      _send('PUT', '/settings', body: s);

  /// Set timeframe eksekusi bot (dipanggil saat timeframe global berubah).
  Future<void> setBotSignalTimeframe(String tf) async {
    final s = await getBotSettings();
    s['signal_timeframe'] = tf;
    await updateBotSettings(s);
  }
}

// ══════════════════════════════════════════════════════════
//  DATA MODELS
// ══════════════════════════════════════════════════════════

class GoldPrice {
  final String timestamp;
  final double price, open, high, low, changeUsd, changePct;
  final double? dxy, vix, bond10y, oil;

  GoldPrice({
    required this.timestamp, required this.price,
    required this.open, required this.high, required this.low,
    required this.changeUsd, required this.changePct,
    this.dxy, this.vix, this.bond10y, this.oil,
  });

  factory GoldPrice.fromJson(Map<String, dynamic> j) => GoldPrice(
    timestamp : j['timestamp'] ?? '',
    price     : (j['price']      ?? 0).toDouble(),
    open      : (j['open']       ?? 0).toDouble(),
    high      : (j['high']       ?? 0).toDouble(),
    low       : (j['low']        ?? 0).toDouble(),
    changeUsd : (j['change_usd'] ?? 0).toDouble(),
    changePct : (j['change_pct'] ?? 0).toDouble(),
    dxy       : j['dxy']     != null ? (j['dxy']    ).toDouble() : null,
    vix       : j['vix']     != null ? (j['vix']    ).toDouble() : null,
    bond10y   : j['bond10y'] != null ? (j['bond10y']).toDouble() : null,
    oil       : j['oil']     != null ? (j['oil']    ).toDouble() : null,
  );
}

class SignalData {
  final double currentPrice, confidence;
  final String signal, timestamp;
  final int buyCount, sellCount, neutralCount;
  final double? prediction1d, prediction7d;
  final List<double> support, resistance;

  SignalData({
    required this.currentPrice, required this.confidence,
    required this.signal, required this.timestamp,
    required this.buyCount, required this.sellCount,
    required this.neutralCount,
    this.prediction1d, this.prediction7d,
    this.support = const [], this.resistance = const [],
  });

  factory SignalData.fromJson(Map<String, dynamic> j) {
    final sum = j['indicator_summary'] ?? {};
    return SignalData(
      currentPrice  : (j['current_price'] ?? 0).toDouble(),
      confidence    : (j['confidence']    ?? 0).toDouble(),
      signal        : j['signal'] ?? 'NETRAL',
      timestamp     : j['timestamp'] ?? '',
      buyCount      : sum['buy']     ?? 0,
      sellCount     : sum['sell']    ?? 0,
      neutralCount  : sum['neutral'] ?? 0,
      prediction1d  : j['prediction_1d'] != null ? (j['prediction_1d']).toDouble() : null,
      prediction7d  : j['prediction_7d'] != null ? (j['prediction_7d']).toDouble() : null,
      support       : List<double>.from((j['support']    ?? []).map((e) => e.toDouble())),
      resistance    : List<double>.from((j['resistance'] ?? []).map((e) => e.toDouble())),
    );
  }
}

class PredictionItem {
  final int horizonDays;
  final String date, signal;
  final double predictedPrice, changeUsd, changePct, lower95, upper95;
  final double? xgbPrice, lstmPrice;
  final bool modelAgreement;

  PredictionItem({
    required this.horizonDays, required this.date, required this.signal,
    required this.predictedPrice, required this.changeUsd,
    required this.changePct, required this.lower95, required this.upper95,
    this.xgbPrice, this.lstmPrice, this.modelAgreement = false,
  });

  factory PredictionItem.fromJson(Map<String, dynamic> j) => PredictionItem(
    horizonDays    : j['horizon_days'] ?? 0,
    date           : j['date'] ?? '',
    signal         : j['signal'] ?? 'NETRAL',
    predictedPrice : (j['predicted_price'] ?? 0).toDouble(),
    changeUsd      : (j['change_usd']      ?? 0).toDouble(),
    changePct      : (j['change_pct']      ?? 0).toDouble(),
    lower95        : (j['lower_95']        ?? 0).toDouble(),
    upper95        : (j['upper_95']        ?? 0).toDouble(),
    xgbPrice       : j['xgb_price']  != null ? (j['xgb_price'] ).toDouble() : null,
    lstmPrice      : j['lstm_price'] != null ? (j['lstm_price']).toDouble() : null,
    modelAgreement : j['model_agreement'] ?? false,
  );
}

class PredictionData {
  final double currentPrice;
  final String overallSignal, generatedAt;
  final List<PredictionItem> predictions;

  PredictionData({
    required this.currentPrice, required this.overallSignal,
    required this.generatedAt, required this.predictions,
  });

  factory PredictionData.fromJson(Map<String, dynamic> j) {
    final predsMap = j['predictions'] as Map<String, dynamic>? ?? {};
    final preds = predsMap.values
        .map((e) => PredictionItem.fromJson(e as Map<String, dynamic>))
        .toList()
      ..sort((a, b) => a.horizonDays.compareTo(b.horizonDays));
    return PredictionData(
      currentPrice  : (j['current_price']  ?? 0).toDouble(),
      overallSignal : j['overall_signal']  ?? 'NETRAL',
      generatedAt   : j['generated_at']   ?? '',
      predictions   : preds,
    );
  }
}

class IndicatorSignal {
  final String name, signal, category, detail;
  final double value;

  IndicatorSignal({
    required this.name, required this.signal,
    required this.category, required this.detail,
    required this.value,
  });

  factory IndicatorSignal.fromJson(Map<String, dynamic> j) => IndicatorSignal(
    name     : j['name']     ?? '',
    signal   : j['signal']   ?? 'NETRAL',
    category : j['category'] ?? '',
    detail   : j['detail']   ?? '',
    value    : (j['value']   ?? 0).toDouble(),
  );
}

class IndicatorData {
  final double currentPrice, confidence;
  final String overallSignal, timestamp;
  final int buyCount, sellCount, neutralCount;
  final List<IndicatorSignal> signals;
  final List<double> support, resistance;

  IndicatorData({
    required this.currentPrice, required this.confidence,
    required this.overallSignal, required this.timestamp,
    required this.buyCount, required this.sellCount,
    required this.neutralCount, required this.signals,
    this.support = const [], this.resistance = const [],
  });

  factory IndicatorData.fromJson(Map<String, dynamic> j) {
    final sum = j['summary'] ?? {};
    return IndicatorData(
      currentPrice  : (j['current_price'] ?? 0).toDouble(),
      confidence    : (j['confidence']    ?? 0).toDouble(),
      overallSignal : j['overall_signal'] ?? 'NETRAL',
      timestamp     : j['timestamp']      ?? '',
      buyCount      : sum['buy']     ?? 0,
      sellCount     : sum['sell']    ?? 0,
      neutralCount  : sum['neutral'] ?? 0,
      signals       : List<IndicatorSignal>.from(
        (j['signals'] ?? []).map((e) => IndicatorSignal.fromJson(e))),
      support    : List<double>.from((j['support_levels']    ?? []).map((e) => e.toDouble())),
      resistance : List<double>.from((j['resistance_levels'] ?? []).map((e) => e.toDouble())),
    );
  }
}

class TimeframeResult {
  final String timeframe, label, signal;
  final double confidence, rsi, adx;
  final int buy, sell, neutral;

  TimeframeResult({
    required this.timeframe, required this.label,
    required this.signal, required this.confidence,
    required this.rsi, required this.adx,
    required this.buy, required this.sell, required this.neutral,
  });

  factory TimeframeResult.fromJson(Map<String, dynamic> j) => TimeframeResult(
    timeframe  : j['timeframe']  ?? '',
    label      : j['label']      ?? '',
    signal     : j['signal']     ?? 'NETRAL',
    confidence : (j['confidence'] ?? 0).toDouble(),
    rsi        : (j['rsi']        ?? 0).toDouble(),
    adx        : (j['adx']        ?? 0).toDouble(),
    buy        : j['buy']     ?? 0,
    sell       : j['sell']    ?? 0,
    neutral    : j['neutral'] ?? 0,
  );
}

class MultiTFData {
  final List<TimeframeResult> timeframes;
  final Map<String, dynamic> consensus;

  MultiTFData({required this.timeframes, required this.consensus});

  factory MultiTFData.fromJson(Map<String, dynamic> j) => MultiTFData(
    timeframes : List<TimeframeResult>.from(
      (j['timeframes'] ?? []).map((e) => TimeframeResult.fromJson(e))),
    consensus  : j['consensus'] ?? {},
  );
}

class FundamentalItem {
  final String name, unit, impact;
  final double? value, changePct;

  FundamentalItem({
    required this.name, required this.unit, required this.impact,
    this.value, this.changePct,
  });

  factory FundamentalItem.fromEntry(String key, Map<String, dynamic> j) =>
    FundamentalItem(
      name      : key,
      unit      : j['unit']   ?? '',
      impact    : j['impact'] ?? '',
      value     : j['value']      != null ? (j['value']     ).toDouble() : null,
      changePct : j['change_pct'] != null ? (j['change_pct']).toDouble() : null,
    );
}

class FundamentalData {
  final String timestamp;
  final List<FundamentalItem> items;

  FundamentalData({required this.timestamp, required this.items});

  factory FundamentalData.fromJson(Map<String, dynamic> j) {
    final dataMap = j['data'] as Map<String, dynamic>? ?? {};
    return FundamentalData(
      timestamp : j['timestamp'] ?? '',
      items     : dataMap.entries
          .map((e) => FundamentalItem.fromEntry(e.key, e.value))
          .toList(),
    );
  }
}

class OhlcData {
  final String date;
  final double open, high, low, close;
  final int volume;

  OhlcData({
    required this.date, required this.open, required this.high,
    required this.low, required this.close, required this.volume,
  });

  factory OhlcData.fromJson(Map<String, dynamic> j) => OhlcData(
    date   : j['date']   ?? '',
    open   : (j['open']  ?? 0).toDouble(),
    high   : (j['high']  ?? 0).toDouble(),
    low    : (j['low']   ?? 0).toDouble(),
    close  : (j['close'] ?? 0).toDouble(),
    volume : j['volume'] ?? 0,
  );
}

// ══════════════════════════════════════════════════════════
//  TRADING MODELS (gerbang eksekutor)
// ══════════════════════════════════════════════════════════

class AccountInfo {
  final int login;
  final double balance, equity, margin, freeMargin, profit;
  final String currency;

  AccountInfo({
    this.login = 0, this.balance = 0, this.equity = 0, this.margin = 0,
    this.freeMargin = 0, this.profit = 0, this.currency = 'USD',
  });

  factory AccountInfo.fromJson(Map<String, dynamic> j) => AccountInfo(
        login: j['login'] ?? 0,
        balance: (j['balance'] ?? 0).toDouble(),
        equity: (j['equity'] ?? 0).toDouble(),
        margin: (j['margin'] ?? 0).toDouble(),
        freeMargin: (j['free_margin'] ?? 0).toDouble(),
        profit: (j['profit'] ?? 0).toDouble(),
        currency: j['currency'] ?? 'USD',
      );
}

class BotStatus {
  final bool running, mt5Connected;
  final AccountInfo account;
  final List<String> symbols;

  BotStatus({
    required this.running, required this.mt5Connected,
    required this.account, this.symbols = const [],
  });

  factory BotStatus.fromJson(Map<String, dynamic> j) => BotStatus(
        running: j['running'] ?? false,
        mt5Connected: j['mt5_connected'] ?? false,
        account: AccountInfo.fromJson(
            (j['account'] as Map<String, dynamic>?) ?? {}),
        symbols: List<String>.from(j['symbols'] ?? const []),
      );
}

class Position {
  final int ticket, time;
  final String symbol, type, comment;
  final double volume, priceOpen, priceCurrent, sl, tp, profit;

  Position({
    required this.ticket, required this.symbol, required this.type,
    required this.volume, required this.priceOpen, required this.priceCurrent,
    required this.sl, required this.tp, required this.profit,
    required this.time, this.comment = '',
  });

  bool get isBuy => type == 'BUY';

  factory Position.fromJson(Map<String, dynamic> j) => Position(
        ticket: j['ticket'] ?? 0,
        symbol: j['symbol'] ?? '',
        type: j['type'] ?? '',
        volume: (j['volume'] ?? 0).toDouble(),
        priceOpen: (j['price_open'] ?? 0).toDouble(),
        priceCurrent: (j['price_current'] ?? 0).toDouble(),
        sl: (j['sl'] ?? 0).toDouble(),
        tp: (j['tp'] ?? 0).toDouble(),
        profit: (j['profit'] ?? 0).toDouble(),
        time: j['time'] ?? 0,
        comment: j['comment'] ?? '',
      );
}

class ClosedTrade {
  final int positionId, openTime, closeTime;
  final String symbol, type;
  final double volume, openPrice, closePrice, profit;

  ClosedTrade({
    required this.positionId, required this.symbol, required this.type,
    required this.volume, required this.openPrice, required this.closePrice,
    required this.profit, required this.openTime, required this.closeTime,
  });

  factory ClosedTrade.fromJson(Map<String, dynamic> j) => ClosedTrade(
        positionId: j['position_id'] ?? 0,
        symbol: j['symbol'] ?? '',
        type: j['type'] ?? '',
        volume: (j['volume'] ?? 0).toDouble(),
        openPrice: (j['open_price'] ?? 0).toDouble(),
        closePrice: (j['close_price'] ?? 0).toDouble(),
        profit: (j['profit'] ?? 0).toDouble(),
        openTime: j['open_time'] ?? 0,
        closeTime: j['close_time'] ?? 0,
      );
}

/// Log keputusan bot (berasal dari sinyal FuLens).
class BotSignal {
  final String symbol, rawSignal, time;
  final String? direction;
  final double confidence, atr;
  final bool executed;
  final int executedEntries, plannedEntries;
  final List<String> reasons;

  BotSignal({
    required this.symbol, required this.rawSignal, required this.time,
    this.direction, this.confidence = 0, this.atr = 0,
    this.executed = false, this.executedEntries = 0, this.plannedEntries = 0,
    this.reasons = const [],
  });

  factory BotSignal.fromJson(Map<String, dynamic> j) => BotSignal(
        symbol: j['symbol'] ?? '',
        rawSignal: j['raw_signal'] ?? j['signal'] ?? 'NETRAL',
        time: j['time'] ?? '',
        direction: j['direction'],
        confidence: (j['confidence'] ?? 0).toDouble(),
        atr: (j['atr'] ?? 0).toDouble(),
        executed: j['executed'] ?? false,
        executedEntries: j['executed_entries'] ?? 0,
        plannedEntries: j['planned_entries'] ?? 0,
        reasons: List<String>.from(j['reasons'] ?? const []),
      );
}

// ══════════════════════════════════════════════════════════
//  MULTI-SIMBOL & BACKTEST
// ══════════════════════════════════════════════════════════

class SymbolInfo {
  final String symbol, asset, name;
  final bool ml;

  SymbolInfo({required this.symbol, required this.asset,
      required this.name, this.ml = false});

  factory SymbolInfo.fromJson(Map<String, dynamic> j) => SymbolInfo(
        symbol: j['symbol'] ?? '',
        asset: j['asset'] ?? '',
        name: j['name'] ?? j['symbol'] ?? '',
        ml: j['ml'] ?? false,
      );
}

class BacktestPoint {
  final String date;
  final double equity;
  BacktestPoint({required this.date, required this.equity});

  factory BacktestPoint.fromJson(Map<String, dynamic> j) => BacktestPoint(
        date: j['date'] ?? '',
        equity: (j['equity'] ?? 1).toDouble(),
      );
}

class BacktestResult {
  final String symbol, note, timeframe, strategy;
  final String? start, end;
  final int trades, bars;
  final double totalReturnPct, buyHoldPct, winRate, avgWinPct, avgLossPct,
      profitFactor, maxDrawdownPct;
  final double? mlTestAccuracy;
  final List<BacktestPoint> equityCurve;

  BacktestResult({
    required this.symbol, required this.note, required this.timeframe,
    required this.strategy, required this.trades, required this.bars,
    required this.totalReturnPct, required this.buyHoldPct,
    required this.winRate, required this.avgWinPct, required this.avgLossPct,
    required this.profitFactor, required this.maxDrawdownPct,
    required this.equityCurve, this.start, this.end, this.mlTestAccuracy,
  });

  factory BacktestResult.fromJson(Map<String, dynamic> j) => BacktestResult(
        symbol: j['symbol'] ?? '',
        note: j['note'] ?? '',
        timeframe: j['timeframe'] ?? 'D1',
        strategy: j['strategy'] ?? 'ta',
        start: j['start'],
        end: j['end'],
        trades: j['trades'] ?? 0,
        bars: j['bars'] ?? 0,
        totalReturnPct: (j['total_return_pct'] ?? 0).toDouble(),
        buyHoldPct: (j['buy_hold_pct'] ?? 0).toDouble(),
        winRate: (j['win_rate'] ?? 0).toDouble(),
        avgWinPct: (j['avg_win_pct'] ?? 0).toDouble(),
        avgLossPct: (j['avg_loss_pct'] ?? 0).toDouble(),
        profitFactor: (j['profit_factor'] ?? 0).toDouble(),
        maxDrawdownPct: (j['max_drawdown_pct'] ?? 0).toDouble(),
        mlTestAccuracy: j['ml_test_accuracy'] != null
            ? (j['ml_test_accuracy']).toDouble() : null,
        equityCurve: ((j['equity_curve'] as List?) ?? [])
            .map((e) => BacktestPoint.fromJson(e as Map<String, dynamic>))
            .toList(),
      );
}

// ══════════════════════════════════════════════════════════
//  TRADING ADVICE MODEL
// ══════════════════════════════════════════════════════════

class TradingAdvice {
  final double currentPrice;
  final String signal, bias, sessionLabel;
  final List<EntryZone> entryZones;
  final List<TradingLevel> supportLevels, targetLevels, stopLevels;
  final List<TradingArgument> arguments;
  final String summary, riskNote;
  final double riskRewardRatio;

  TradingAdvice({
    required this.currentPrice, required this.signal,
    required this.bias, required this.sessionLabel,
    required this.entryZones, required this.supportLevels,
    required this.targetLevels, required this.stopLevels,
    required this.arguments, required this.summary,
    required this.riskNote, required this.riskRewardRatio,
  });
}

class EntryZone {
  final String label, type, reason;
  final double priceFrom, priceTo;
  final String strength; // "Kuat" | "Moderat" | "Lemah"

  EntryZone({
    required this.label, required this.type, required this.reason,
    required this.priceFrom, required this.priceTo, required this.strength,
  });
}

class TradingLevel {
  final String label, reason, type;
  final double price;

  TradingLevel({
    required this.label, required this.reason,
    required this.type, required this.price,
  });
}

class TradingArgument {
  final String title, description, icon;
  final bool isBullish;

  TradingArgument({
    required this.title, required this.description,
    required this.icon, required this.isBullish,
  });
}
