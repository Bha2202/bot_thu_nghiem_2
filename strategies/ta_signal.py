# strategies/ta_signal.py
"""
TA SIGNAL — Tra cứu realtime cho BẤT KỲ mã cổ phiếu nào.

Ví dụ:
    /signal FPT
    /signal VCB
    /signal HPG

Không phụ thuộc data/watch_list.json.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd


# ============================================================
# CONFIG
# ============================================================

DB_PATH = Path("data/market_data.db")
TABLE_NAME = "historical_ohlcv"

EMA_PERIOD = 20
RSI_PERIOD = 14
VOLUME_SMA_PERIOD = 20
ATR_PERIOD = 14

# BUY
VOLUME_SPIKE_RATIO = 1.0
RSI_BUY_MIN = 45
RSI_BUY_MAX = 70

# SELL
RSI_SELL_THRESHOLD = 75

# Risk management
ATR_STOP_MULTIPLIER = 2.0
RISK_REWARD_TARGET = 2.0

MIN_BARS_REQUIRED = 60


# ============================================================
# HELPER CHUẨN HÓA & ÉP KIỂU AN TOÀN (TRÁNH CRASH)
# ============================================================

def _normalize_price(price: float) -> float:
    """Tự động quy đổi giá về đơn vị Nghìn VNĐ (VD: 20900 -> 20.9)."""
    if price is None or pd.isna(price) or price <= 0:
        return 0.0
    if price > 2000:
        return price / 1000.0
    return float(price)


def _safe_float(val, default=0.0):
    """Ép kiểu float an toàn, không bị văng lỗi khi gặp 'N/A' hoặc None."""
    if val is None or val == "N/A" or pd.isna(val):
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _fmt(val, fmt_str="{:,.2f}", suffix=""):
    """Định dạng chuỗi hiển thị an toàn."""
    num = _safe_float(val, None)
    if num is None:
        return "N/A"
    return f"{fmt_str.format(num)}{suffix}"


# ============================================================
# DATABASE
# ============================================================

def get_connection():
    """Mở kết nối SQLite."""
    return sqlite3.connect(DB_PATH)


from datetime import datetime, time

def load_historical_data(
    ticker: str,
    limit: int = 150,
) -> pd.DataFrame:
    ticker = ticker.upper().strip()

    # THÊM LOGIC ĐIỀU KIỆN LỌC NGÀY CHUYÊN NGHIỆP:
    # Nếu tra cứu trước 15:00 PM -> Không lấy nến dở dang của ngày hôm nay
    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")
    
    if now.time() < time(15, 0):
        # Chỉ lấy các phiên đã đóng cửa hoàn chỉnh (bé hơn ngày hôm nay)
        query = f"""
            SELECT symbol, date, open, high, low, close, volume
            FROM {TABLE_NAME}
            WHERE symbol = ? AND date < ?
            ORDER BY date DESC
            LIMIT ?
        """
        params = (ticker, today_str, limit)
    else:
        query = f"""
            SELECT symbol, date, open, high, low, close, volume
            FROM {TABLE_NAME}
            WHERE symbol = ?
            ORDER BY date DESC
            LIMIT ?
        """
        params = (ticker, limit)

    try:
        with get_connection() as conn:
            df = pd.read_sql_query(
                query,
                conn,
                params=params,
            )
    except Exception:
        return pd.DataFrame()

    if df.empty:
        return df

    df["date"] = pd.to_datetime(df["date"])

    numeric_cols = ["open", "high", "low", "close", "volume"]

    for col in numeric_cols:
        df[col] = pd.to_numeric(
            df[col],
            errors="coerce",
        )

    df = df.dropna(subset=["open", "high", "low", "close", "volume"])

    # Chuẩn hóa đơn vị giá lịch sử (nếu bị lưu nguyên đơn vị Đồng)
    df["close"] = df["close"].apply(_normalize_price)
    df["open"] = df["open"].apply(_normalize_price)
    df["high"] = df["high"].apply(_normalize_price)
    df["low"] = df["low"].apply(_normalize_price)

    df = df.sort_values("date").reset_index(drop=True)

    return df

# ============================================================
# REALTIME DATA
# ============================================================

def load_live_ticks(ticker: str) -> pd.DataFrame:
    ticker = ticker.upper().strip()
    if not ticker:
        return pd.DataFrame()

    query = """
        SELECT symbol, price, volume, timestamp as time 
        FROM realtime_ticks 
        WHERE symbol = ? 
        ORDER BY timestamp DESC LIMIT 1
    """
    try:
        with get_connection() as conn:
            df = pd.read_sql_query(query, conn, params=(ticker,))
            if not df.empty and "price" in df.columns:
                df["price"] = df["price"].apply(_normalize_price)
            return df
    except Exception:
        return pd.DataFrame()


def merge_live_bar(
    historical: pd.DataFrame,
    live_ticks: pd.DataFrame,
) -> pd.DataFrame:
    if historical.empty:
        return historical

    if live_ticks.empty:
        return historical.copy()

    # NẾU CHƯA QUA 15:00 PM THÌ KHÔNG GHÉP NẾN REALTIME VÀO LỊCH SỬ CHỐT PHIÊN
    from datetime import datetime, time
    now = datetime.now()
    if now.time() < time(15, 0):
        return historical.copy()

    live = live_ticks.copy()
    live.columns = [str(c).lower() for c in live.columns]

    if "price" not in live.columns:
        return historical.copy()

    if "volume" not in live.columns:
        live["volume"] = 0

    valid_prices = pd.to_numeric(live["price"], errors="coerce").dropna()
    if valid_prices.empty:
        return historical.copy()

    current_price = _normalize_price(float(valid_prices.iloc[-1]))
    current_open = _normalize_price(float(valid_prices.iloc[0]))
    current_high = _normalize_price(float(valid_prices.max()))
    current_low = _normalize_price(float(valid_prices.min()))

    current_volume = float(
        pd.to_numeric(live["volume"], errors="coerce").fillna(0).sum()
    )

    result = historical.copy()
    today = pd.Timestamp.now().normalize()
    today_mask = result["date"].dt.normalize() == today

    if today_mask.any():
        idx = result.index[today_mask][-1]
        result.loc[idx, "close"] = current_price
        result.loc[idx, "high"] = max(float(result.loc[idx, "high"]), current_high)
        result.loc[idx, "low"] = min(float(result.loc[idx, "low"]), current_low)
        result.loc[idx, "volume"] = max(float(result.loc[idx, "volume"]), current_volume)
    else:
        new_bar = pd.DataFrame(
            [{
                "symbol": result["symbol"].iloc[-1],
                "date": pd.Timestamp.now(),
                "open": current_open,
                "high": current_high,
                "low": current_low,
                "close": current_price,
                "volume": current_volume,
            }]
        )
        result = pd.concat([result, new_bar], ignore_index=True)

    return result.sort_values("date").reset_index(drop=True)

# ============================================================
# INDICATORS
# ============================================================

def calculate_ema(close: pd.Series, period: int = EMA_PERIOD) -> pd.Series:
    return close.ewm(span=period, adjust=False).mean()


def calculate_rsi(close: pd.Series, period: int = RSI_PERIOD) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi


def calculate_atr(df: pd.DataFrame, period: int = ATR_PERIOD) -> pd.Series:
    previous_close = df["close"].shift(1)
    tr1 = df["high"] - df["low"]
    tr2 = (df["high"] - previous_close).abs()
    tr3 = (df["low"] - previous_close).abs()

    true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = true_range.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    return atr


def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
    result = df.copy()

    result["ema20"] = calculate_ema(result["close"])
    result["rsi14"] = calculate_rsi(result["close"])
    result["volume_sma20"] = result["volume"].rolling(VOLUME_SMA_PERIOD).mean()
    result["volume_ratio"] = result["volume"] / result["volume_sma20"]
    result["atr14"] = calculate_atr(result)
    result["ema20_rising"] = result["ema20"] > result["ema20"].shift(1)

    return result


# ============================================================
# SIGNAL
# ============================================================

def evaluate_signal(df: pd.DataFrame) -> dict:
    if len(df) < MIN_BARS_REQUIRED:
        return {
            "signal": "NO SIGNAL",
            "reason": f"Không đủ dữ liệu ({len(df)}/{MIN_BARS_REQUIRED} bars)",
        }

    row = df.iloc[-1]
    previous_row = df.iloc[-2] if len(df) >= 2 else None

    price = _safe_float(row["close"])
    ema20 = _safe_float(row["ema20"])
    rsi14 = _safe_float(row["rsi14"])
    volume = _safe_float(row["volume"])
    volume_sma20 = _safe_float(row["volume_sma20"])
    volume_ratio = _safe_float(row["volume_ratio"])
    atr14 = _safe_float(row["atr14"])

    ema20_rising = bool(row.get("ema20_rising", False))

    trend_ok = (price > ema20) and ema20_rising
    volume_ok = volume_ratio >= VOLUME_SPIKE_RATIO
    momentum_ok = RSI_BUY_MIN <= rsi14 <= RSI_BUY_MAX

    buy_score = sum([trend_ok, volume_ok, momentum_ok])

    price_below_ema = price < ema20
    rsi_declining = False

    if previous_row is not None:
        previous_rsi = _safe_float(previous_row["rsi14"])
        rsi_declining = rsi14 < previous_rsi

    rsi_sell = (rsi14 > RSI_SELL_THRESHOLD) and rsi_declining

    if rsi_sell or price_below_ema:
        signal = "SELL"
    elif buy_score == 3:
        # Bổ sung bộ lọc R:R < 1.0 tại đây
        if not np.isnan(rr) and rr < 1.0:
            signal = "WATCH"  # Hạ xuống WATCH nếu kèo thối R:R < 1.0
        else:
            signal = "BUY"
    elif buy_score >= 2:
        signal = "WATCH"
    else:
        signal = "NO SIGNAL"
        
    stop_loss = max(0.0, price - ATR_STOP_MULTIPLIER * atr14)
    risk = price - stop_loss
    take_profit = price + risk * RISK_REWARD_TARGET
    reward = take_profit - price
    rr = (reward / risk) if risk > 0 else np.nan

    return {
        "signal": signal,
        "price": price,
        "ema20": ema20,
        "rsi14": rsi14,
        "volume": volume,
        "volume_sma20": volume_sma20,
        "volume_ratio": volume_ratio,
        "atr14": atr14,
        "trend_ok": trend_ok,
        "volume_ok": volume_ok,
        "momentum_ok": momentum_ok,
        "buy_score": buy_score,
        "price_below_ema": price_below_ema,
        "rsi_sell": rsi_sell,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "risk": risk,
        "reward": reward,
        "risk_reward": rr,
        "ema20_rising": ema20_rising,
    }


# ============================================================
# MAIN ANALYSIS
# ============================================================

def analyze_symbol(ticker: str) -> Optional[dict]:
    ticker = ticker.upper().strip()

    if not ticker:
        return None

    historical = load_historical_data(ticker)

    if historical.empty:
        return {
            "ticker": ticker,
            "signal": "NOT FOUND",
            "reason": f"Không tìm thấy dữ liệu cho mã {ticker}",
        }

    live_ticks = load_live_ticks(ticker)
    df = merge_live_bar(historical, live_ticks)
    df = calculate_indicators(df)
    result = evaluate_signal(df)

    result["ticker"] = ticker
    result["data_time"] = df["date"].iloc[-1]
    result["is_realtime"] = not live_ticks.empty

    return result


# ============================================================
# FORMAT TELEGRAM
# ============================================================

def format_signal_message(result: dict) -> str:
    ticker = result.get("ticker", "UNKNOWN")
    signal = result.get("signal", "NO SIGNAL")

    if signal == "BUY":
        signal_icon = "🟢"
    elif signal == "WATCH":
        signal_icon = "🟡"
    elif signal == "SELL":
        signal_icon = "🔴"
    elif signal == "NOT FOUND":
        signal_icon = "❌"
    else:
        signal_icon = "⚪"

    if signal == "NOT FOUND":
        return f"❌ Không tìm thấy dữ liệu cho mã {ticker}."

    if signal == "NO SIGNAL" and ("price" not in result):
        return f"📊 {ticker} — TA SIGNAL\n\n⚪ {result.get('reason', '')}"

    trend_text = "✓" if result.get("trend_ok") else "✗"
    volume_text = "✓" if result.get("volume_ok") else "✗"
    momentum_text = "✓" if result.get("momentum_ok") else "✗"
    realtime_text = "🟢 REALTIME" if result.get("is_realtime") else "🟡 DATA CUỐI CÙNG"
    data_time = result.get("data_time", "")

    return (
        f"📊 {ticker} — TA SIGNAL\n"
        f"{realtime_text}\n\n"

        f"💰 Giá hiện tại: {_fmt(result.get('price'))} VNĐ\n\n"

        f"📈 CHỈ BÁO TA\n"
        f"• EMA20: {_fmt(result.get('ema20'))}\n"
        f"• RSI14: {_fmt(result.get('rsi14'))}\n"
        f"• Volume: {_fmt(result.get('volume'), '{:,.0f}')}\n"
        f"• Volume SMA20: {_fmt(result.get('volume_sma20'), '{:,.0f}')}\n"
        f"• Volume Ratio: {_fmt(result.get('volume_ratio'))}x\n"
        f"• ATR14: {_fmt(result.get('atr14'))}\n\n"

        f"🔎 ĐIỀU KIỆN BUY\n"
        f"• Giá > EMA20 & EMA tăng: {trend_text}\n"
        f"• Volume đạt chuẩn: {volume_text}\n"
        f"• RSI trong vùng BUY: {momentum_text}\n"
        f"• Score: {result.get('buy_score', 0)}/3\n\n"

        f"🔔 TÍN HIỆU: {signal_icon} {signal}\n\n"

        f"🛡️ RISK MANAGEMENT\n"
        f"• Stop Loss: {_fmt(result.get('stop_loss'))} VNĐ\n"
        f"• Take Profit: {_fmt(result.get('take_profit'))} VNĐ\n"
        f"• Risk: {_fmt(result.get('risk'))}\n"
        f"• Reward: {_fmt(result.get('reward'))}\n"
        f"• Risk/Reward: 1:{_fmt(result.get('risk_reward'))}\n\n"

        f"⏱️ Dữ liệu: {data_time}\n\n"
        f"⚠️ Tín hiệu được tạo theo bộ quy tắc TA của bot."
    )


# ============================================================
# TEST COMMAND LINE
# ============================================================

if __name__ == "__main__":
    print("=" * 60)
    print("TA SIGNAL — REALTIME STOCK ANALYSIS")
    print("=" * 60)

    ticker = input("Nhập mã cổ phiếu: ").strip().upper()
    result = analyze_symbol(ticker)

    if result is None:
        print("Mã không hợp lệ.")
    else:
        print()
        print(format_signal_message(result))