// lib/services/ws_service.dart
import 'dart:async';
import 'dart:convert';
import 'package:web_socket_channel/web_socket_channel.dart';
import '../config/app_config.dart';

/// Satu event realtime dari bot: signal / trade_opened / trade_closed /
/// account / trailing.
class BotEvent {
  final String event;
  final Map<String, dynamic> data;
  final String ts;

  BotEvent({required this.event, required this.data, required this.ts});

  factory BotEvent.fromJson(Map<String, dynamic> j) => BotEvent(
        event: j['event'] ?? '',
        data: (j['data'] as Map<String, dynamic>?) ?? {},
        ts: j['ts'] ?? '',
      );
}

enum WsStatus { disconnected, connecting, connected }

/// WebSocket ke gerbang eksekutor `ws://host/ws?key=…` dengan auto-reconnect.
class WsService {
  static final WsService _instance = WsService._internal();
  factory WsService() => _instance;
  WsService._internal();

  WebSocketChannel? _channel;
  StreamSubscription? _sub;
  Timer? _retry;
  bool _wantConnected = false;

  final _events = StreamController<BotEvent>.broadcast();
  final _statusCtrl = StreamController<WsStatus>.broadcast();
  WsStatus _status = WsStatus.disconnected;

  Stream<BotEvent> get events => _events.stream;
  Stream<WsStatus> get status => _statusCtrl.stream;
  WsStatus get currentStatus => _status;

  void _setStatus(WsStatus s) {
    _status = s;
    if (!_statusCtrl.isClosed) _statusCtrl.add(s);
  }

  void connect() {
    // Idempoten: aman dipanggil berkali-kali (mis. saat layar dibangun ulang
    // karena ganti simbol) tanpa membuka koneksi ganda.
    if (_wantConnected && _channel != null) return;
    _wantConnected = true;
    _open();
  }

  void _open() {
    if (!_wantConnected) return;
    _setStatus(WsStatus.connecting);
    try {
      _channel = WebSocketChannel.connect(Uri.parse(AppConfig.wsUrl));
      _setStatus(WsStatus.connected);
      _sub = _channel!.stream.listen(
        (msg) {
          try {
            final j = json.decode(msg as String) as Map<String, dynamic>;
            _events.add(BotEvent.fromJson(j));
          } catch (_) {/* abaikan frame rusak */}
        },
        onDone: _scheduleReconnect,
        onError: (_) => _scheduleReconnect(),
        cancelOnError: true,
      );
    } catch (_) {
      _scheduleReconnect();
    }
  }

  void _scheduleReconnect() {
    _setStatus(WsStatus.disconnected);
    _cleanup();
    if (!_wantConnected) return;
    _retry?.cancel();
    _retry = Timer(const Duration(seconds: 3), _open);
  }

  void _cleanup() {
    _sub?.cancel();
    _sub = null;
    try {
      _channel?.sink.close();
    } catch (_) {}
    _channel = null;
  }

  void disconnect() {
    _wantConnected = false;
    _retry?.cancel();
    _cleanup();
    _setStatus(WsStatus.disconnected);
  }
}
