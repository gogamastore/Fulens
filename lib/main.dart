// lib/main.dart
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'core/theme.dart';
import 'state/symbol_state.dart';
import 'widgets/symbol_selector.dart';
import 'screens/dashboard_screen.dart';
import 'screens/trading_screen.dart';
import 'screens/positions_screen.dart';
import 'screens/technical_screen.dart';
import 'screens/prediction_screen.dart';
import 'screens/backtest_screen.dart';
import 'screens/fundamental_screen.dart';
import 'screens/history_screen.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  SystemChrome.setPreferredOrientations([
    DeviceOrientation.portraitUp,
    DeviceOrientation.landscapeLeft,
    DeviceOrientation.landscapeRight,
  ]);
  SystemChrome.setSystemUIOverlayStyle(const SystemUiOverlayStyle(
    statusBarColor: Colors.transparent,
    statusBarIconBrightness: Brightness.light,
  ));
  runApp(const ProviderScope(child: FuLens()));
}

class FuLens extends StatelessWidget {
  const FuLens({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'FuLens',
      debugShowCheckedModeBanner: false,
      theme: AppTheme.dark,
      home: const AppShell(),
    );
  }
}

// ── APP SHELL dengan Bottom Navigation ──────────────────
class AppShell extends StatefulWidget {
  const AppShell({super.key});

  @override
  State<AppShell> createState() => _AppShellState();
}

class _AppShellState extends State<AppShell> {
  int _currentIndex = 0;

  @override
  void initState() {
    super.initState();
    SymbolState.instance.load(); // muat daftar simbol dari backend
  }

  final List<Widget> _screens = const [
    DashboardScreen(),
    TradingScreen(),
    PositionsScreen(),
    TechnicalScreen(),
    PredictionScreen(),
    BacktestScreen(),
    FundamentalScreen(),
    HistoryScreen(),
  ];

  final List<NavigationDestination> _navItems = const [
    NavigationDestination(
      icon: Icon(Icons.dashboard_outlined),
      selectedIcon: Icon(Icons.dashboard),
      label: 'Dashboard',
    ),
    NavigationDestination(
      icon: Icon(Icons.smart_toy_outlined),
      selectedIcon: Icon(Icons.smart_toy),
      label: 'Trading',
    ),
    NavigationDestination(
      icon: Icon(Icons.candlestick_chart_outlined),
      selectedIcon: Icon(Icons.candlestick_chart),
      label: 'Posisi',
    ),
    NavigationDestination(
      icon: Icon(Icons.show_chart_outlined),
      selectedIcon: Icon(Icons.show_chart),
      label: 'Teknikal',
    ),
    NavigationDestination(
      icon: Icon(Icons.auto_graph_outlined),
      selectedIcon: Icon(Icons.auto_graph),
      label: 'Prediksi',
    ),
    NavigationDestination(
      icon: Icon(Icons.query_stats_outlined),
      selectedIcon: Icon(Icons.query_stats),
      label: 'Backtest',
    ),
    NavigationDestination(
      icon: Icon(Icons.analytics_outlined),
      selectedIcon: Icon(Icons.analytics),
      label: 'Fundamental',
    ),
    NavigationDestination(
      icon: Icon(Icons.history_outlined),
      selectedIcon: Icon(Icons.history),
      label: 'Riwayat',
    ),
  ];

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Column(
        children: [
          const SymbolTopBar(),
          Expanded(
            // Bangun ulang layar saat simbol berganti agar semua tab mengikuti
            // simbol terpilih (chart, prediksi, teknikal, dst).
            child: ListenableBuilder(
              listenable: SymbolState.instance,
              builder: (context, _) {
                final sym = SymbolState.instance.symbol;
                final tf = SymbolState.instance.timeframe;
                return IndexedStack(
                  index: _currentIndex,
                  children: [
                    for (final screen in _screens)
                      KeyedSubtree(
                        key: ValueKey('${screen.runtimeType}-$sym-$tf'),
                        child: screen,
                      ),
                  ],
                );
              },
            ),
          ),
        ],
      ),
      bottomNavigationBar: Container(
        decoration: const BoxDecoration(
          border: Border(top: BorderSide(color: AppColors.border)),
        ),
        child: NavigationBar(
          selectedIndex: _currentIndex,
          onDestinationSelected: (i) => setState(() => _currentIndex = i),
          destinations: _navItems,
          backgroundColor: AppColors.surface,
          indicatorColor: AppColors.goldBg,
          labelBehavior: NavigationDestinationLabelBehavior.onlyShowSelected,
          height: 65,
        ),
      ),
    );
  }
}
