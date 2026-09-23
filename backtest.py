"""
backtest.py — Backtest quy mô lớn trên TOÀN BỘ dữ liệu cổ phiếu trong Database SQLite.
"""

from __future__ import annotations

import sqlite3
import numpy as np
import pandas as pd
from pathlib import Path

from strategies.ta_strategy import ta_compute_indicators

# ============================================================================
# CẤU HÌNH ĐƯỜNG DẪN & THAM SỐ TỐI ƯU
# ============================================================================
DB_PATH = "data/market_data.db"

RSI_BUY_MIN = 50.0
RSI_BUY_MAX = 65.0
VOLUME_SPIKE_RATIO = 1.2
EMA_SELL_BUFFER_PCT = 0.01  # 1% Buffer khi thủng EMA20
RSI_SELL_THRESHOLD = 75.0
ATR_STOP_MULTIPLIER = 2.0


def get_all_symbols_from_db(db_path: str = DB_PATH) -> list[str]:
    """Lấy toàn bộ danh sách mã cổ phiếu hiện có trong bảng historical_ohlcv."""
    if not Path(db_path).exists():
        print(f"❌ Không tìm thấy file Database tại: {db_path}")
        return []

    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT symbol FROM historical_ohlcv")
        rows = cursor.fetchall()
        symbols = [r[0] for r in rows if r[0]]
        return sorted(symbols)
    except Exception as e:
        print(f"❌ Lỗi khi đọc danh sách mã từ DB: {e}")
        return []
    finally:
        conn.close()


def load_full_history(symbol: str, db_path: str = DB_PATH) -> pd.DataFrame:
    """Lấy dữ liệu OHLCV của mã từ Database."""
    conn = sqlite3.connect(db_path)
    try:
        df = pd.read_sql_query(
            "SELECT date, open, high, low, close, volume FROM historical_ohlcv WHERE symbol = ? ORDER BY date ASC",
            conn, params=(symbol.upper(),)
        )
    except Exception:
        df = pd.DataFrame()
    finally:
        conn.close()
    return df


def calculate_max_drawdown(pnl_list: list[float]) -> float:
    """Tính Max Drawdown (%) dựa trên chuỗi PnL tích lũy."""
    if not pnl_list:
        return 0.0
    equity_curve = np.cumsum(pnl_list)
    peak = np.maximum.accumulate(equity_curve)
    drawdowns = peak - equity_curve
    return float(np.max(drawdowns)) if len(drawdowns) > 0 else 0.0


def run_backtest_single_symbol(symbol: str) -> dict:
    df = load_full_history(symbol)
    if df.empty or len(df) < 60:
        return {"symbol": symbol, "status": "SKIP", "reason": "Thiếu dữ liệu (<60 phiên)"}

    try:
        df = ta_compute_indicators(df)
    except Exception as e:
        return {"symbol": symbol, "status": "ERROR", "reason": str(e)}

    position = None
    trades = []

    for i in range(60, len(df)):
        row = df.iloc[i]
        prev = df.iloc[i - 1]

        price = row["close"]
        high = row["high"]
        ema20, prev_ema20 = row["ema20"], prev["ema20"]
        rsi, prev_rsi = row["rsi14"], prev["rsi14"]
        volume, vol_sma, atr = row["volume"], row["volume_sma20"], row["atr14"]

        if pd.isna(rsi) or pd.isna(vol_sma) or pd.isna(atr):
            continue

        # --- 1. MỞ VỊ THẾ MUA ---
        if position is None:
            trend_up = price > ema20 and ema20 > prev_ema20
            volume_ok = vol_sma > 0 and volume >= VOLUME_SPIKE_RATIO * vol_sma
            momentum_ok = RSI_BUY_MIN <= rsi <= RSI_BUY_MAX

            if trend_up and volume_ok and momentum_ok:
                stop_loss = price - ATR_STOP_MULTIPLIER * atr
                position = {
                    "entry_date": row["date"],
                    "entry_price": price,
                    "highest_price": price,
                    "stop_loss": stop_loss,
                }

        # --- 2. ĐÓNG VỊ THẾ BÁN ---
        else:
            highest_price = max(position["highest_price"], high)
            new_stop = max(position["stop_loss"], highest_price - ATR_STOP_MULTIPLIER * atr)
            position["highest_price"] = highest_price
            position["stop_loss"] = new_stop

            stop_hit = price < new_stop
            price_below_ema_buffered = price < (ema20 * (1.0 - EMA_SELL_BUFFER_PCT))
            rsi_overbought = rsi > RSI_SELL_THRESHOLD and rsi < prev_rsi

            if stop_hit or price_below_ema_buffered or rsi_overbought:
                pnl_pct = (price - position["entry_price"]) / position["entry_price"] * 100
                trades.append(pnl_pct)
                position = None

    total_trades = len(trades)
    if total_trades == 0:
        return {"symbol": symbol, "status": "NO_TRADES", "total_trades": 0, "win_rate": 0, "total_pnl": 0}

    winning_trades = [p for p in trades if p > 0]
    win_rate = (len(winning_trades) / total_trades) * 100
    total_pnl = sum(trades)
    max_dd = calculate_max_drawdown(trades)

    return {
        "symbol": symbol,
        "status": "OK",
        "total_trades": total_trades,
        "win_rate": round(win_rate, 1),
        "total_pnl": round(total_pnl, 2),
        "max_drawdown": round(max_dd, 2),
        "trades": trades
    }


def run_full_watchlist_backtest():
    all_symbols = get_all_symbols_from_db()

    if not all_symbols:
        print("❌ Không tìm thấy dữ liệu mã cổ phiếu nào trong Database market_data.db")
        return

    print(f"\n========================================================")
    print(f"🚀 BẮT ĐẦU BACKTEST TOÀN BỘ VŨ TRỤ DỮ LIỆU CÀO VỀ ({len(all_symbols)} MÃ)")
    print(f"========================================================\n")

    results = []
    skipped_count = 0

    print(f"{'STT':<4} | {'Mã':<6} | {'Số Lệnh':<8} | {'Win Rate':<10} | {'Tổng PnL (%)':<12} | {'Max DD (%)':<10}")
    print("-" * 65)

    for idx, sym in enumerate(all_symbols, 1):
        res = run_backtest_single_symbol(sym)

        if res["status"] != "OK":
            skipped_count += 1
            continue

        results.append(res)
        print(
            f"{idx:<4} | {sym:<6} | {res['total_trades']:<8} | "
            f"{res['win_rate']:<9}% | {res['total_pnl']:<12}% | {res['max_drawdown']:<10}%"
        )

    print("-" * 65)

    # --- TỔNG HỢP KẾT QUẢ ---
    if not results:
        print("❌ Không có mã nào phát sinh giao dịch đủ điều kiện.")
        return

    all_win_rates = [r["win_rate"] for r in results]
    all_pnls = [r["total_pnl"] for r in results]
    total_trades_all = sum([r["total_trades"] for r in results])
    profitable_symbols = [r for r in results if r["total_pnl"] > 0]

    avg_win_rate = sum(all_win_rates) / len(all_win_rates)
    avg_pnl_per_symbol = sum(all_pnls) / len(all_pnls)
    profitable_ratio = (len(profitable_symbols) / len(results)) * 100

    print(f"\n📊 === BÁO CÁO THỐNG KÊ TOÀN DIỆN VŨ TRỤ CỔ PHIẾU ===")
    print(f"• Tổng số mã trong Database:         {len(all_symbols)}")
    print(f"• Số mã có dữ liệu & phát sinh lệnh: {len(results)} (Bỏ qua/Không lệnh: {skipped_count})")
    print(f"• Tổng số giao dịch đã thực hiện:   {total_trades_all} lệnh")
    print(f"• Win Rate trung bình danh mục:      {avg_win_rate:.2f}%")
    print(f"• PnL trung bình mỗi mã:            {avg_pnl_per_symbol:.2f}%")
    print(f"• Tỷ lệ mã có LÃI RÒNG:              {profitable_ratio:.1f}% ({len(profitable_symbols)}/{len(results)} mã)")
    print(f"========================================================\n")


if __name__ == "__main__":
    run_full_watchlist_backtest()