// lib/state/selected_symbol.dart
//
// Konteks global (holder ringan tanpa dependensi) supaya ApiService bisa
// memakainya sebagai default tanpa import melingkar ke SymbolState.
String selectedSymbol = 'XAUUSD';
String selectedTimeframe = 'D1';
