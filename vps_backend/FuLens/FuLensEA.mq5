//+------------------------------------------------------------------+
//|  FuLensEA.mq5 - TANGAN + MATA untuk FuLens Hybrid                 |
//|                                                                  |
//|  EA ini TIDAK punya strategi. Semua keputusan (arah, kualitas,   |
//|  jarak SL/TP) datang dari otak Python lewat gerbang :8000.        |
//|  Tugas EA:                                                        |
//|    MATA   : kirim OHLC bar tertutup ke gerbang tiap bar baru.     |
//|    TANGAN : terima rencana, hitung lot dari equity, buka/tutup    |
//|             posisi, trailing stop, lalu lapor state balik.        |
//|                                                                  |
//|  Semua dilakukan pada PENUTUPAN BAR (bar index 1) - hindari       |
//|  repaint dari bar berjalan.                                       |
//|                                                                  |
//|  PENTING sebelum pakai:                                           |
//|   Tools > Options > Expert Advisors > "Allow WebRequest for       |
//|   listed URL" -> tambahkan http://<ip-vps>:8000                    |
//+------------------------------------------------------------------+
#property strict
#include <Trade/Trade.mqh>

//--- Input: koneksi
input string GatewayUrl   = "http://93.127.140.99:8000"; // URL gerbang (WHITELIST dulu!)
input string ApiKey       = "CN9-5UB1TBJMD5wM_WR5dNiPr_Gbq9CXz6dt8Pa1spg";
// Timeframe yang DIDORONG ke otak (mata). Makin lengkap, makin banyak layar
// analisis di Flutter yang memakai harga broker asli alih-alih yfinance.
// Kurangi daftarnya bila ingin lalu lintas lebih ringan.
input string FeedTimeframes = "M1,M5,M15,M30,H1,H4,D1,W1";
input int    BarsToSend     = 200;                   // jumlah bar per timeframe
// Batas timeframe per satu POST. Tanpa ini, saat start EA mengirim SEMUA
// timeframe sekaligus: 8 x 200 bar = ~170 KB dalam satu WebRequest. Itu terlalu
// besar - permintaan gagal/timeout dan gerbang bisa tersendat. Sisanya dikirim
// otomatis pada tick/poll berikutnya karena penanda dirty belum dibersihkan.
input int    MaxFeedsPerSync = 2;
// Catatan: TIDAK ada input mode maupun timeframe eksekusi di EA.
// Keduanya ditentukan dari aplikasi Flutter (trading_mode + exec_timeframe).
// EA murni tangan+mata: dorong data semua timeframe, terima perintah.
// Simbol yang ditradingkan = chart tempat EA ini dipasang.
input int    HttpTimeoutMs = 8000;                   // timeout push penuh (bawa OHLC)

// -- Polling cepat ----------------------------------------------------
// Tanpa ini EA hanya bicara ke gerbang SAAT BAR TERTUTUP: di H1 sekali sejam,
// di D1 sekali sehari. Akibatnya perintah manual (close dari Flutter) dan
// perubahan setelan (ganti mode/risk) baru sampai satu bar kemudian.
// Poll ringan ini TIDAK mengirim OHLC (hemat), hanya mengambil rencana +
// perintah, lalu menerapkannya. 0 = matikan (kembali ke perilaku bar-close).
input int    PollSeconds   = 5;                      // detik antar poll ringan
input int    PollTimeoutMs = 3000;                   // timeout poll (pendek!)

//--- Input: risiko (fallback bila gerbang tak mengirim; gerbang biasanya menang)
input double RiskPercentFallback = 0.5;
input int    MagicFallback       = 202607;

//--- Global
CTrade   trade;
long     g_magic   = 0;              // diisi dari rencana; fallback MagicFallback

// Daftar timeframe feed + waktu bar terakhir per timeframe (deteksi bar baru).
// g_tfDirty = timeframe yang perlu didorong; baru dibersihkan setelah push
// BERHASIL, supaya sync yang gagal otomatis dicoba lagi (data tak hilang).
string          g_tfName[];
ENUM_TIMEFRAMES g_tfEnum[];
datetime        g_tfLastBar[];
bool            g_tfDirty[];
int             g_sentIdx[];         // indeks feed yang ikut di POST terakhir
// Timeframe EKSEKUSI, dipelajari dari balasan gerbang. Dipakai agar poll ringan
// cukup menyegarkan bar berjalan timeframe ITU saja - bukan semua timeframe
// (yang berarti 8 panggilan ke otak tiap 5 detik, sia-sia).
string          g_execTf = "";

// Fill tertutup yang ditangkap OnTradeTransaction, dikirim saat sync berikutnya.
struct FillRec {
   long   position_id;
   string symbol;
   string type;        // arah POSISI ("BUY"/"SELL")
   double volume;
   double open_price;
   double close_price;
   double profit;
   long   open_time;
   long   close_time;
};
FillRec g_fills[];

// Proteksi drawdown harian
datetime g_day       = 0;
double   g_dayEquity = 0;

//+------------------------------------------------------------------+
int OnInit()
{
   g_magic = MagicFallback;
   trade.SetExpertMagicNumber(g_magic);
   ParseFeedTimeframes();
   PrintFormat("FuLensEA init: %s feeds=[%s] poll=%ds gateway=%s",
               _Symbol, FeedTimeframes, PollSeconds, GatewayUrl);
   Print("Mode & timeframe EKSEKUSI diatur dari aplikasi Flutter.");
   if(PollSeconds > 0) EventSetTimer(PollSeconds);
   return(INIT_SUCCEEDED);
}

//+------------------------------------------------------------------+
//| Pecah "M1,M5,H1" jadi daftar timeframe yang akan didorong.        |
//+------------------------------------------------------------------+
void ParseFeedTimeframes()
{
   string parts[];
   int n = StringSplit(FeedTimeframes, ',', parts);
   ArrayResize(g_tfName, 0);
   ArrayResize(g_tfEnum, 0);
   ArrayResize(g_tfLastBar, 0);
   ArrayResize(g_tfDirty, 0);
   for(int i = 0; i < n; i++) {
      string s = parts[i];
      StringTrimLeft(s); StringTrimRight(s);
      if(StringLen(s) == 0) continue;
      ENUM_TIMEFRAMES e = TfFromString(s);
      if((int)e < 0) {
         Print("FuLens: timeframe '", s, "' TIDAK DIKENAL - dilewati. ",
               "Sengaja tidak jatuh ke D1: itu akan mengirim bar D1 berlabel ", s,
               " dan membuat SL/TP salah skala tanpa peringatan.");
         continue;
      }
      int k = ArraySize(g_tfName);
      ArrayResize(g_tfName, k + 1);
      ArrayResize(g_tfEnum, k + 1);
      ArrayResize(g_tfLastBar, k + 1);
      ArrayResize(g_tfDirty, k + 1);
      g_tfName[k]    = s;
      g_tfEnum[k]    = e;
      g_tfLastBar[k] = 0;
      g_tfDirty[k]   = true;           // bootstrap: dorong semua sekali di awal
   }
}

void OnDeinit(const int reason) { EventKillTimer(); }

//+------------------------------------------------------------------+
//| Jalankan hanya sekali per bar baru (bar 1 baru saja tertutup).   |
//+------------------------------------------------------------------+
void OnTick()
{
   // Kumpulkan timeframe yang BARU saja menutup bar. Biasanya 0 atau 1 per tick;
   // di menit ke-5 bisa M1 dan M5 sekaligus. Hanya itu yang perlu didorong ulang.
   bool newBar = false;
   for(int i = 0; i < ArraySize(g_tfEnum); i++) {
      datetime cur = iTime(_Symbol, g_tfEnum[i], 0);
      if(cur != 0 && cur != g_tfLastBar[i]) {
         g_tfLastBar[i] = cur;
         g_tfDirty[i]   = true;
         newBar = true;
      }
   }
   // HANYA saat benar-benar ada bar baru. Sisa backlog (karena batas
   // MaxFeedsPerSync atau push gagal) sengaja TIDAK dikirim dari sini: tick
   // datang beberapa kali per detik, dan tiap RunCycle adalah WebRequest yang
   // memblokir - itu akan membanjiri gerbang. Backlog dituntaskan OnTimer.
   if(!newBar) return;
   RunCycle(true);
}

//+------------------------------------------------------------------+
//| Poll ringan: ambil rencana + perintah TANPA mengirim OHLC.        |
//| Ini yang membuat perintah manual & perubahan setelan terasa       |
//| seketika, tanpa menunggu bar berikutnya.                          |
//+------------------------------------------------------------------+
void OnTimer()
{
   if(PollSeconds <= 0) return;
   // Ada feed yang belum terkirim (dibatasi MaxFeedsPerSync, atau push gagal)?
   // Tuntaskan di sini - terjadwal tiap PollSeconds, jadi tak membanjiri gerbang.
   bool backlog = false;
   for(int i = 0; i < ArraySize(g_tfDirty); i++)
      if(g_tfDirty[i]) { backlog = true; break; }
   RunCycle(backlog);
}

//+------------------------------------------------------------------+
//| Satu siklus penuh: sync ke gerbang, lalu terapkan rencana.       |
//+------------------------------------------------------------------+
void RunCycle(bool sendFeeds)
{
   string body = BuildSyncBody(sendFeeds);
   string resp = "";
   int timeout = sendFeeds ? HttpTimeoutMs : PollTimeoutMs;
   if(!HttpPost("/ea/sync", body, resp, timeout)) {
      // Poll ringan sesekali gagal itu wajar (jaringan) - jangan spam log.
      // Penanda dirty TIDAK dibersihkan, jadi feed yang gagal dicoba lagi.
      if(sendFeeds) Print("FuLensEA: sync gagal - feed akan dicoba lagi");
      return;
   }
   // Bersihkan penanda HANYA untuk feed yang benar-benar ikut di POST ini.
   // Feed yang tertunda (karena batas MaxFeedsPerSync) tetap dirty dan akan
   // menyusul di siklus berikutnya.
   for(int i = 0; i < ArraySize(g_sentIdx); i++) g_tfDirty[g_sentIdx[i]] = false;
   ArrayResize(g_fills, 0);            // fill sudah terkirim; kosongkan

   // Pelajari timeframe eksekusi dari gerbang (dipilih di Flutter).
   string et = JsonStr(resp, "exec_timeframe");
   if(et != "") g_execTf = et;

   // --- Baca rencana dari respons FLAT ---
   long   magic       = (long)JsonNum(resp, "magic_number");
   if(magic > 0) { g_magic = magic; trade.SetExpertMagicNumber(g_magic); }

   bool   running     = JsonBool(resp, "running");
   bool   actionable  = JsonBool(resp, "actionable");
   string target      = JsonStr (resp, "target");     // "BUY"/"SELL"/"" (null)
   double slDist      = JsonNum (resp, "sl_distance");
   double tpDist      = JsonNum (resp, "tp_distance");
   double atr         = JsonNum (resp, "atr");
   bool   closeNeutral= JsonBool(resp, "close_on_neutral");
   bool   closeFlip   = JsonBool(resp, "close_on_flip");
   double riskPct     = JsonNum (resp, "risk_percent");
   if(riskPct <= 0) riskPct = RiskPercentFallback;
   bool   trailEnabled= JsonBool(resp, "trail_enabled");
   double trailStart  = JsonNum (resp, "trail_start_atr");
   double trailDist   = JsonNum (resp, "trail_dist_atr");
   double maxDailyDD  = JsonNum (resp, "max_daily_drawdown_pct");

   // 1) Perintah manual: tutup tiket tertentu (dari Flutter).
   long closeTickets[];
   JsonIntArray(resp, "close_tickets", closeTickets);
   for(int i = 0; i < ArraySize(closeTickets); i++)
      trade.PositionClose((ulong)closeTickets[i]);

   // 2) Proteksi drawdown harian.
   bool ddOk = CheckDailyDrawdown(maxDailyDD);

   // 3) Posisi kita saat ini untuk simbol ini (v1: maksimal satu).
   ulong  myTicket = 0;
   string mySide   = "";
   FindMyPosition(myTicket, mySide);

   // 4) NETRAL -> tutup (bila diaktifkan).
   if(target == "" || !actionable) {
      if(myTicket > 0 && target == "" && closeNeutral)
         trade.PositionClose(myTicket);
   }
   else if(running && ddOk) {
      // 5) Arah berlawanan -> tutup dulu (flip).
      if(myTicket > 0 && mySide != target) {
         if(closeFlip) { trade.PositionClose(myTicket); myTicket = 0; mySide = ""; }
      }
      // 6) Buka bila belum ada posisi searah (v1: satu entry, tanpa piramida).
      if(myTicket == 0 && slDist > 0)
         OpenTrade(target, slDist, tpDist, riskPct);
   }

   // 7) Trailing stop.
   if(trailEnabled && atr > 0)
      ManageTrailing(atr, trailStart, trailDist);
}

//+------------------------------------------------------------------+
//| Buka posisi: lot dari equity / jarak SL, SL/TP dari jarak otak.  |
//+------------------------------------------------------------------+
void OpenTrade(string dir, double slDist, double tpDist, double riskPct)
{
   double lot = ComputeLot(slDist, riskPct);
   if(lot <= 0) { Print("FuLensEA: lot 0 - batal buka"); return; }

   int    dg  = (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS);
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);

   if(dir == "BUY") {
      double sl = NormalizeDouble(ask - slDist, dg);
      double tp = (tpDist > 0) ? NormalizeDouble(ask + tpDist, dg) : 0;
      trade.Buy(lot, _Symbol, ask, sl, tp, "fulens");
   } else {
      double sl = NormalizeDouble(bid + slDist, dg);
      double tp = (tpDist > 0) ? NormalizeDouble(bid - tpDist, dg) : 0;
      trade.Sell(lot, _Symbol, bid, sl, tp, "fulens");
   }
}

double ComputeLot(double slDist, double riskPct)
{
   double equity  = AccountInfoDouble(ACCOUNT_EQUITY);
   double tickVal = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
   double tickSz  = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   if(tickVal <= 0 || tickSz <= 0 || slDist <= 0) return 0;

   double riskMoney  = equity * riskPct / 100.0;
   double lossPerLot = (slDist / tickSz) * tickVal;
   double vol = (lossPerLot > 0) ? riskMoney / lossPerLot : 0;

   double step = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   double vmin = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double vmax = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   if(step <= 0) step = 0.01;
   vol = MathRound(vol / step) * step;
   vol = MathMax(vmin, MathMin(vmax, vol));
   return NormalizeDouble(vol, 2);
}

//+------------------------------------------------------------------+
//| Trailing: geser SL saat profit >= trailStartxATR, jarak trailDistxATR |
//+------------------------------------------------------------------+
void ManageTrailing(double atr, double trailStart, double trailDist)
{
   double start = atr * trailStart;
   double dist  = atr * trailDist;
   int dg = (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS);

   for(int i = PositionsTotal() - 1; i >= 0; i--) {
      ulong tk = PositionGetTicket(i);
      if(!PositionSelectByTicket(tk)) continue;
      if(PositionGetInteger(POSITION_MAGIC) != g_magic) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;

      long   ptype = PositionGetInteger(POSITION_TYPE);
      double open  = PositionGetDouble(POSITION_PRICE_OPEN);
      double cur   = PositionGetDouble(POSITION_PRICE_CURRENT);
      double sl    = PositionGetDouble(POSITION_SL);
      double tp    = PositionGetDouble(POSITION_TP);

      if(ptype == POSITION_TYPE_BUY && (cur - open) >= start) {
         double nsl = NormalizeDouble(cur - dist, dg);
         if(nsl > sl) trade.PositionModify(tk, nsl, tp);
      }
      else if(ptype == POSITION_TYPE_SELL && (open - cur) >= start) {
         double nsl = NormalizeDouble(cur + dist, dg);
         if(sl == 0 || nsl < sl) trade.PositionModify(tk, nsl, tp);
      }
   }
}

bool CheckDailyDrawdown(double maxDDpct)
{
   MqlDateTime t; TimeToStruct(TimeCurrent(), t);
   datetime day0 = StringToTime(StringFormat("%04d.%02d.%02d", t.year, t.mon, t.day));
   double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   if(day0 != g_day) { g_day = day0; g_dayEquity = equity; }
   if(g_dayEquity <= 0 || maxDDpct <= 0) return true;
   double dd = (g_dayEquity - equity) / g_dayEquity * 100.0;
   if(dd >= maxDDpct) { PrintFormat("Drawdown harian %.2f%% >= %.2f%% - stop buka", dd, maxDDpct); return false; }
   return true;
}

void FindMyPosition(ulong &ticket, string &side)
{
   ticket = 0; side = "";
   for(int i = PositionsTotal() - 1; i >= 0; i--) {
      ulong tk = PositionGetTicket(i);
      if(!PositionSelectByTicket(tk)) continue;
      if(PositionGetInteger(POSITION_MAGIC) != g_magic) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
      ticket = tk;
      side = (PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY) ? "BUY" : "SELL";
      return;
   }
}

//+------------------------------------------------------------------+
//| Tangkap fill tertutup (untuk /history di Flutter).               |
//+------------------------------------------------------------------+
void OnTradeTransaction(const MqlTradeTransaction &trans,
                        const MqlTradeRequest &req,
                        const MqlTradeResult &res)
{
   if(trans.type != TRADE_TRANSACTION_DEAL_ADD) return;
   ulong deal = trans.deal;
   if(!HistoryDealSelect(deal)) return;
   if(HistoryDealGetInteger(deal, DEAL_MAGIC) != g_magic) return;
   if(HistoryDealGetInteger(deal, DEAL_ENTRY) != DEAL_ENTRY_OUT) return; // hanya close

   FillRec f;
   f.position_id = (long)HistoryDealGetInteger(deal, DEAL_POSITION_ID);
   f.symbol      = HistoryDealGetString(deal, DEAL_SYMBOL);
   long dtype    = HistoryDealGetInteger(deal, DEAL_TYPE);
   // Deal OUT bertipe SELL menutup posisi BUY, dan sebaliknya.
   f.type        = (dtype == DEAL_TYPE_SELL) ? "BUY" : "SELL";
   f.volume      = HistoryDealGetDouble(deal, DEAL_VOLUME);
   f.close_price = HistoryDealGetDouble(deal, DEAL_PRICE);
   f.profit      = HistoryDealGetDouble(deal, DEAL_PROFIT)
                 + HistoryDealGetDouble(deal, DEAL_SWAP)
                 + HistoryDealGetDouble(deal, DEAL_COMMISSION);
   f.close_time  = (long)HistoryDealGetInteger(deal, DEAL_TIME);
   f.open_price  = 0; f.open_time = 0;
   // Ambil harga/waktu buka dari deal IN posisi yang sama.
   if(HistorySelectByPosition(f.position_id)) {
      for(int i = 0; i < HistoryDealsTotal(); i++) {
         ulong d = HistoryDealGetTicket(i);
         if(HistoryDealGetInteger(d, DEAL_ENTRY) == DEAL_ENTRY_IN) {
            f.open_price = HistoryDealGetDouble(d, DEAL_PRICE);
            f.open_time  = (long)HistoryDealGetInteger(d, DEAL_TIME);
            break;
         }
      }
   }
   int n = ArraySize(g_fills);
   ArrayResize(g_fills, n + 1);
   g_fills[n] = f;
}

//+------------------------------------------------------------------+
//| Bangun body JSON untuk POST /ea/sync                             |
//+------------------------------------------------------------------+
string BuildSyncBody(bool sendFeeds)
{
   string js = "{";
   js += "\"symbol\":\"" + _Symbol + "\",";
   js += "\"feeds\":" + BuildFeeds(sendFeeds) + ",";
   js += "\"account\":" + BuildAccount() + ",";
   js += "\"positions\":" + BuildPositions() + ",";
   js += "\"fills\":" + BuildFills();
   js += "}";
   return js;
}

//+------------------------------------------------------------------+
//| Bungkus SEMUA timeframe yang perlu didorong jadi satu array.      |
//| Hanya yang ditandai dirty (bar baru / push sebelumnya gagal),     |
//| jadi satu WebRequest cukup untuk beberapa timeframe sekaligus.    |
//+------------------------------------------------------------------+
string BuildFeeds(bool full)
{
   ArrayResize(g_sentIdx, 0);
   string js = "[";
   bool first = true;
   for(int i = 0; i < ArraySize(g_tfEnum); i++) {
      int count;
      if(full) {
         // Push penuh: hanya timeframe yang bar-nya baru tertutup (atau yang
         // push sebelumnya gagal). Dibatasi MaxFeedsPerSync agar satu POST tak
         // membengkak; sisanya menyusul karena dirty-nya belum dibersihkan.
         if(!g_tfDirty[i]) continue;
         if(ArraySize(g_sentIdx) >= MaxFeedsPerSync) break;
         count = BarsToSend;
      } else {
         // Poll ringan: cukup timeframe EKSEKUSI, 2 bar - hanya untuk
         // menyegarkan bar berjalan agar harga tidak membeku antar-bar.
         if(g_execTf == "" || g_tfName[i] != g_execTf) continue;
         count = 2;
      }
      if(!first) js += ",";
      first = false;
      js += "{\"timeframe\":\"" + g_tfName[i] + "\",";
      js += "\"bars\":" + BuildBars(g_tfEnum[i], count) + "}";
      int k = ArraySize(g_sentIdx);
      ArrayResize(g_sentIdx, k + 1);
      g_sentIdx[k] = i;
   }
   js += "]";
   return js;
}

//+------------------------------------------------------------------+
//| Ambil `count` bar MULAI INDEX 0 - TERMASUK bar berjalan.          |
//|                                                                  |
//| Penting: otak memakai konvensi "baris terakhir = bar BERJALAN,    |
//| baris -2 = bar tertutup terakhir" (BAR_CLOSED = -2), sama seperti |
//| data yfinance. Kalau EA mengirim mulai index 1 (hanya bar         |
//| tertutup), otak mengurangi satu lagi dan akhirnya menganalisis    |
//| bar yang BASI SATU BAR PENUH - di H1 berarti telat sejam.         |
//| Dengan mengirim dari index 0, analisis tetap anti-repaint (bar    |
//| tertutup terakhir) sekaligus harga "kini" jadi akurat.            |
//+------------------------------------------------------------------+
string BuildBars(ENUM_TIMEFRAMES tf, int count)
{
   MqlRates r[];
   ArraySetAsSeries(r, false);
   int got = CopyRates(_Symbol, tf, 0, count, r);   // index 0 = bar berjalan
   if(got <= 0) return "[]";
   string js = "[";
   for(int i = 0; i < got; i++) {
      if(i > 0) js += ",";
      js += "{";
      js += "\"time\":" + IntegerToString((long)r[i].time) + ",";
      js += "\"open\":"  + DoubleToString(r[i].open, 5)  + ",";
      js += "\"high\":"  + DoubleToString(r[i].high, 5)  + ",";
      js += "\"low\":"   + DoubleToString(r[i].low, 5)   + ",";
      js += "\"close\":" + DoubleToString(r[i].close, 5) + ",";
      js += "\"volume\":"+ IntegerToString((long)r[i].tick_volume);
      js += "}";
   }
   js += "]";
   return js;
}

string BuildAccount()
{
   string js = "{";
   js += "\"login\":"       + IntegerToString(AccountInfoInteger(ACCOUNT_LOGIN)) + ",";
   js += "\"balance\":"     + DoubleToString(AccountInfoDouble(ACCOUNT_BALANCE), 2) + ",";
   js += "\"equity\":"      + DoubleToString(AccountInfoDouble(ACCOUNT_EQUITY), 2) + ",";
   js += "\"margin\":"      + DoubleToString(AccountInfoDouble(ACCOUNT_MARGIN), 2) + ",";
   js += "\"free_margin\":" + DoubleToString(AccountInfoDouble(ACCOUNT_MARGIN_FREE), 2) + ",";
   js += "\"profit\":"      + DoubleToString(AccountInfoDouble(ACCOUNT_PROFIT), 2) + ",";
   js += "\"currency\":\""  + AccountInfoString(ACCOUNT_CURRENCY) + "\"";
   js += "}";
   return js;
}

string BuildPositions()
{
   string js = "[";
   bool first = true;
   for(int i = PositionsTotal() - 1; i >= 0; i--) {
      ulong tk = PositionGetTicket(i);
      if(!PositionSelectByTicket(tk)) continue;
      if(PositionGetInteger(POSITION_MAGIC) != g_magic) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
      if(!first) js += ",";
      first = false;
      string side = (PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY) ? "BUY" : "SELL";
      js += "{";
      js += "\"ticket\":" + IntegerToString((long)tk) + ",";
      js += "\"symbol\":\"" + PositionGetString(POSITION_SYMBOL) + "\",";
      js += "\"type\":\"" + side + "\",";
      js += "\"volume\":" + DoubleToString(PositionGetDouble(POSITION_VOLUME), 2) + ",";
      js += "\"price_open\":" + DoubleToString(PositionGetDouble(POSITION_PRICE_OPEN), 5) + ",";
      js += "\"price_current\":" + DoubleToString(PositionGetDouble(POSITION_PRICE_CURRENT), 5) + ",";
      js += "\"sl\":" + DoubleToString(PositionGetDouble(POSITION_SL), 5) + ",";
      js += "\"tp\":" + DoubleToString(PositionGetDouble(POSITION_TP), 5) + ",";
      js += "\"profit\":" + DoubleToString(PositionGetDouble(POSITION_PROFIT), 2) + ",";
      js += "\"time\":" + IntegerToString((long)PositionGetInteger(POSITION_TIME)) + ",";
      js += "\"comment\":\"" + PositionGetString(POSITION_COMMENT) + "\"";
      js += "}";
   }
   js += "]";
   return js;
}

string BuildFills()
{
   string js = "[";
   for(int i = 0; i < ArraySize(g_fills); i++) {
      if(i > 0) js += ",";
      js += "{";
      js += "\"position_id\":" + IntegerToString(g_fills[i].position_id) + ",";
      js += "\"symbol\":\"" + g_fills[i].symbol + "\",";
      js += "\"type\":\"" + g_fills[i].type + "\",";
      js += "\"volume\":" + DoubleToString(g_fills[i].volume, 2) + ",";
      js += "\"open_price\":" + DoubleToString(g_fills[i].open_price, 5) + ",";
      js += "\"close_price\":" + DoubleToString(g_fills[i].close_price, 5) + ",";
      js += "\"profit\":" + DoubleToString(g_fills[i].profit, 2) + ",";
      js += "\"open_time\":" + IntegerToString(g_fills[i].open_time) + ",";
      js += "\"close_time\":" + IntegerToString(g_fills[i].close_time);
      js += "}";
   }
   js += "]";
   return js;
}

//+------------------------------------------------------------------+
//| HTTP POST via WebRequest                                         |
//+------------------------------------------------------------------+
bool HttpPost(string path, string body, string &out, int timeoutMs)
{
   string url = GatewayUrl + path;
   string headers = "Content-Type: application/json\r\nX-API-Key: " + ApiKey + "\r\n";
   char post[], result[];
   string resHeaders;
   int len = StringLen(body);
   StringToCharArray(body, post, 0, len);   // tanpa null terminator
   ResetLastError();
   int code = WebRequest("POST", url, headers, timeoutMs, post, result, resHeaders);
   if(code == -1) {
      PrintFormat("WebRequest error %d - sudah whitelist %s ?", GetLastError(), url);
      return false;
   }
   out = CharArrayToString(result);
   if(code != 200) {
      PrintFormat("Gerbang balas HTTP %d: %s", code, StringSubstr(out, 0, 200));
      return false;
   }
   return true;
}

//+------------------------------------------------------------------+
//| Parser JSON minimal (respons gerbang berbentuk FLAT & terkendali)|
//+------------------------------------------------------------------+
// Ambil token mentah setelah "key": (string tanpa kutip, atau angka/bool/null).
string JsonRaw(string js, string key)
{
   string pat = "\"" + key + "\"";
   int p = StringFind(js, pat);
   if(p < 0) return "";
   p = StringFind(js, ":", p + StringLen(pat));
   if(p < 0) return "";
   p++;
   int n = StringLen(js);
   while(p < n) {
      ushort c = StringGetCharacter(js, p);
      if(c != ' ' && c != '\t' && c != '\n' && c != '\r') break;
      p++;
   }
   if(p < n && StringGetCharacter(js, p) == '"') {   // string
      int e = StringFind(js, "\"", p + 1);
      if(e < 0) return "";
      return StringSubstr(js, p + 1, e - (p + 1));
   }
   int e = p;                                        // angka/bool/null
   while(e < n) {
      ushort c = StringGetCharacter(js, e);
      if(c == ',' || c == '}' || c == ']') break;
      e++;
   }
   string v = StringSubstr(js, p, e - p);
   StringTrimLeft(v); StringTrimRight(v);
   return v;
}

string JsonStr(string js, string key)
{
   string v = JsonRaw(js, key);
   if(v == "null") return "";
   return v;
}

double JsonNum(string js, string key)
{
   string v = JsonRaw(js, key);
   if(v == "" || v == "null") return 0.0;
   return StringToDouble(v);
}

bool JsonBool(string js, string key)
{
   return JsonRaw(js, key) == "true";
}

// Parse array integer: "key":[1,2,3]
void JsonIntArray(string js, string key, long &out[])
{
   ArrayResize(out, 0);
   string pat = "\"" + key + "\"";
   int p = StringFind(js, pat);
   if(p < 0) return;
   int lb = StringFind(js, "[", p);
   int rb = StringFind(js, "]", lb);
   if(lb < 0 || rb < 0) return;
   string inner = StringSubstr(js, lb + 1, rb - lb - 1);
   StringTrimLeft(inner); StringTrimRight(inner);
   if(StringLen(inner) == 0) return;
   string parts[];
   int k = StringSplit(inner, ',', parts);
   for(int i = 0; i < k; i++) {
      string s = parts[i];
      StringTrimLeft(s); StringTrimRight(s);
      if(StringLen(s) == 0) continue;
      int m = ArraySize(out);
      ArrayResize(out, m + 1);
      out[m] = (long)StringToInteger(s);
   }
}

// Kembalikan -1 untuk nama yang TIDAK dikenal, jangan PERIOD_D1.
//
// Fallback diam-diam ke D1 sudah pernah menggigit keras: "M1" dan "M5" ditambahkan
// di backend + Flutter tapi tidak di sini, sehingga EA mengirim bar D1 BERLABEL M1.
// Otak lalu menghitung ATR D1 dan memasang SL/TP puluhan kali terlalu lebar
// (BTCUSD: SL 2715 poin, seharusnya ~15), dan SEMUA analisa M1/M5 di Flutter
// sebenarnya menampilkan candle harian. Tak ada satu pun pesan error.
//
// Nama tf dikirim ke otak apa adanya sementara enum-nya diam-diam berbeda - itu
// dua sumber kebenaran yang boleh berselisih. Sekarang tidak bisa lagi.
ENUM_TIMEFRAMES TfFromString(string tf)
{
   if(tf == "M1")  return PERIOD_M1;
   if(tf == "M5")  return PERIOD_M5;
   if(tf == "M15") return PERIOD_M15;
   if(tf == "M30") return PERIOD_M30;
   if(tf == "H1")  return PERIOD_H1;
   if(tf == "H4")  return PERIOD_H4;
   if(tf == "D1")  return PERIOD_D1;
   if(tf == "W1")  return PERIOD_W1;
   return (ENUM_TIMEFRAMES)-1;
}
//+------------------------------------------------------------------+
