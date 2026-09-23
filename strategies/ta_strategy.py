"""
strategies/ta_strategy.py — Thành viên 3
Lớp 3 (TA: Momentum & Quản trị rủi ro động ATR) — tự theo dõi REAL-TIME.

Máy trạng thái MUA -> GIỮ -> BÁN, lưu vị thế trong data/positions.json giữa
các lần quét (bot chạy real-time, quét mỗi vài phút -> KHÔNG được coi mỗi
lần quét là độc lập, phải nhớ đã mua mã nào để: (1) không báo MUA lại mã
đang giữ, (2) tự cập nhật Trailing Stop theo ATR, (3) tự phát BÁN khi giá
chạm Stop dù chỉ báo kỹ thuật (EMA20/RSI) chưa báo bán).

Có 3 lý do độc lập khiến 1 mã bị BÁN (bất kỳ điều kiện nào xảy ra trước):
  1. Chạm Trailing Stop (ATR)  -> quản trị rủi ro, không phụ thuộc EMA/RSI
  2. Giá cắt xuống dưới EMA20  -> gãy xu hướng
  3. RSI > 75 và đang giảm     -> chốt lời vùng quá mua

Bảng chỉ báo & ngưỡng (đã thống nhất với nhóm):
  EMA20  : Giá > EMA20 và EMA20 dốc lên (T > T-1)              -> điều kiện MUA
  Volume : Volume >= 1.2 x Vol SMA20                            -> điều kiện MUA
  RSI14  : 45 <= RSI <= 68                                      -> điều kiện MUA
           RSI > 75 và RSI đang giảm so với hôm trước           -> 1 trong 3 lý do BÁN
  ATR14  : StopLoss = Close(lúc mua) - 2 x ATR, sau đó Trailing:
           StopLoss_mới = max(StopLoss_cũ, Giá đỉnh từ lúc mua - 2 x ATR)
"""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from datetime import datetime, date
from pathlib import Path

import numpy as np
import pandas as pd

# ----------------------------------------------------------------------------
# 1. Ngưỡng & tham số (chỉnh ở đây, không sửa rải rác trong code)
# ----------------------------------------------------------------------------
EMA_PERIOD = 20
RSI_PERIOD = 14
VOLUME_SMA_PERIOD = 20
ATR_PERIOD = 14

VOLUME_SPIKE_RATIO = 1.2      # Volume >= 1.2 x Vol SMA20
RSI_BUY_MIN = 45              # Điều kiện MUA: 45 <= RSI <= 68
RSI_BUY_MAX = 68
RSI_SELL_THRESHOLD = 75       # 1 lý do BÁN: RSI > 75 và đang giảm so với hôm trước
ATR_STOP_MULTIPLIER = 2.0     # StopLoss = Close - 2 x ATR, sau đó trailing theo giá đỉnh

MIN_BARS_REQUIRED = 60        # tối thiểu 60 phiên để "làm nóng" EMA20/RSI14/ATR14/Vol SMA20

DEFAULT_DB_PATH = "data/market_data.db"
DEFAULT_WATCH_LIST_PATH = "data/watch_list.json"
DEFAULT_POSITIONS_PATH = "data/positions.json"

STRATEGY_NAME = "CANSLIM + Momentum (ATR Trailing Stop, Realtime)"


# ----------------------------------------------------------------------------
# 2. Dữ liệu giá: lịch sử (đã chốt phiên) + nến real-time đang hình thành
# ----------------------------------------------------------------------------
def ta_load_price_history(ticker: str, db_path: str | Path = DEFAULT_DB_PATH,
                          lookback: int = 120) -> pd.DataFrame:
    """Lấy `lookback` phiên đã CHỐT (historical_ohlcv). 120 phiên đủ dư so với
    MIN_BARS_REQUIRED=60 để chỉ báo ổn định ngay cả khi vài phiên bị thiếu."""
    conn = sqlite3.connect(str(db_path))
    try:
        df = pd.read_sql_query(
            """
            SELECT date, open, high, low, close, volume
            FROM historical_ohlcv
            WHERE symbol = ?
            ORDER BY date DESC
            LIMIT ?
            """,
            conn, params=(ticker.upper(), lookback),
        )
    finally:
        conn.close()
    return df.sort_values("date").reset_index(drop=True)


def ta_build_live_bar(ticker: str, db_path: str | Path = DEFAULT_DB_PATH) -> dict | None:
    """Dựng nến của NGÀY HÔM NAY từ tick real-time trong bảng market_data
    (do stock_bot/data_pipeline/main.py ghi liên tục khi đang chạy).
    Trả về None nếu chưa có tick nào hôm nay (ngoài giờ / collector chưa chạy)."""
    conn = sqlite3.connect(str(db_path))
    try:
        today_str = date.today().isoformat()
        df = pd.read_sql_query(
            """
            SELECT price, volume, timestamp
            FROM market_data
            WHERE symbol = ? AND data_type = 'match_price' AND timestamp >= ?
            ORDER BY timestamp ASC
            """,
            conn, params=(ticker.upper(), today_str),
        )
    finally:
        conn.close()

    if df.empty:
        return None

    return {
        "date": today_str,
        "open": float(df["price"].iloc[0]),
        "high": float(df["price"].max()),
        "low": float(df["price"].min()),
        "close": float(df["price"].iloc[-1]),   # giá khớp mới nhất = giá "đang chạy"
        "volume": float(df["volume"].sum()),
    }


def ta_load_price_history_realtime(ticker: str, db_path: str | Path = DEFAULT_DB_PATH,
                                   lookback: int = 120) -> pd.DataFrame:
    """Ghép lịch sử đã chốt + nến real-time đang hình thành (nếu có)."""
    hist = ta_load_price_history(ticker, db_path, lookback)
    live = ta_build_live_bar(ticker, db_path)

    if live is None:
        return hist

    if not hist.empty and hist.iloc[-1]["date"] == live["date"]:
        hist = hist.iloc[:-1]  # tránh trùng nếu update_history.py đã lỡ chốt hôm nay

    return pd.concat([hist, pd.DataFrame([live])], ignore_index=True)


# ----------------------------------------------------------------------------
# 3. Tính chỉ báo
# ----------------------------------------------------------------------------
def ta_compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["ema20"] = out["close"].ewm(span=EMA_PERIOD, adjust=False).mean()

    delta = out["close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / RSI_PERIOD, adjust=False, min_periods=RSI_PERIOD).mean()
    avg_loss = loss.ewm(alpha=1 / RSI_PERIOD, adjust=False, min_periods=RSI_PERIOD).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    out["rsi14"] = 100 - (100 / (1 + rs))
    out.loc[avg_loss == 0, "rsi14"] = 100.0

    out["volume_sma20"] = out["volume"].rolling(VOLUME_SMA_PERIOD).mean()

    prev_close = out["close"].shift(1)
    tr = pd.concat([
        out["high"] - out["low"],
        (out["high"] - prev_close).abs(),
        (out["low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    out["atr14"] = tr.ewm(alpha=1 / ATR_PERIOD, adjust=False, min_periods=ATR_PERIOD).mean()

    return out


# ----------------------------------------------------------------------------
# 4. Kho lưu vị thế đang GIỮ (bộ nhớ giữa các lần quét real-time)
# ----------------------------------------------------------------------------
def ta_load_positions(path: str | Path = DEFAULT_POSITIONS_PATH) -> dict:
    path = Path(path)
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def ta_save_positions(positions: dict, path: str | Path = DEFAULT_POSITIONS_PATH) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(positions, f, ensure_ascii=False, indent=2)
        os.replace(tmp_name, path)
    except Exception:
        if os.path.exists(tmp_name):
            os.remove(tmp_name)
        raise


# ----------------------------------------------------------------------------
# 5. Máy trạng thái MUA -> GIỮ -> BÁN cho 1 mã
# ----------------------------------------------------------------------------
def ta_evaluate_symbol(ticker: str, df: pd.DataFrame, position: dict | None) -> tuple[dict | None, dict | None]:
    """Trả về (event, new_position).
    event: dict tín hiệu BUY/SELL để báo cho bot, hoặc None nếu không có gì mới.
    new_position: trạng thái vị thế sau khi xử lý, hoặc None nếu không còn GIỮ."""
    if len(df) < MIN_BARS_REQUIRED:
        return None, position

    row, prev = df.iloc[-1], df.iloc[-2]
    price, ema20, prev_ema20 = row["close"], row["ema20"], prev["ema20"]
    rsi, prev_rsi = row["rsi14"], prev["rsi14"]
    volume, vol_sma, atr = row["volume"], row["volume_sma20"], row["atr14"]

    if pd.isna(rsi) or pd.isna(prev_rsi) or pd.isna(vol_sma) or pd.isna(atr):
        return None, position

    ta_criteria = {
        "EMA20_Status": "Dốc lên" if ema20 > prev_ema20 else "Đi ngang/xuống",
        "RSI": round(float(rsi), 1),
        "Volume_Ratio": round(float(volume / vol_sma), 2) if vol_sma else None,
        "ATR": round(float(atr), 2),
    }

    # ----- Chưa có vị thế -> xét điều kiện MUA / WATCH -----
    if position is None:
        trend_up = price > ema20 and ema20 > prev_ema20
        volume_ok = vol_sma > 0 and volume >= VOLUME_SPIKE_RATIO * vol_sma
        momentum_ok = RSI_BUY_MIN <= rsi <= RSI_BUY_MAX

        score = sum([trend_up, volume_ok, momentum_ok])

        # 1. Điểm MUA CHUẨN (3/3)
        if score == 3:
            stop_loss = float(price - ATR_STOP_MULTIPLIER * atr)
            event = {
                "ticker": ticker, "signal_type": "BUY",
                "price": round(float(price), 2),
                "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "strategy_name": STRATEGY_NAME,
                "ta_criteria": ta_criteria,
                "stop_loss": round(stop_loss, 2),
            }
            new_position = {
                "entry_price": float(price),
                "entry_date": row["date"],
                "highest_price": float(price),
                "stop_loss": stop_loss,
                "atr_at_entry": float(atr),
                "status": "HOLD",
            }
            return event, new_position

        # 2. CẢNH BÁO SỚM (2/3) - Bắt buộc phải có Xu hướng (Trend)
        elif score == 2 and trend_up:
            event = {
                "ticker": ticker, "signal_type": "WATCH",
                "price": round(float(price), 2),
                "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "strategy_name": STRATEGY_NAME,
                "ta_criteria": ta_criteria,
                "note": "Mã tích lũy tốt, chờ dòng tiền bùng nổ (Vol đạt chuẩn) để MUA"
            }
            return event, None # Chưa lưu vị thế HOLD

        return None, None

    # ----- Đang GIỮ -> cập nhật trailing stop & xét 3 lý do BÁN -----
    if row["date"] <= position["entry_date"]:
        # Chưa có phiên MỚI nào kể từ khi mua (quét lại trong cùng phiên vừa
        # khớp lệnh) -> chưa đủ cơ sở xét BÁN, tránh bán ngay hôm vừa mua.
        return None, position

    highest_price = max(position["highest_price"], float(row["high"]))
    new_stop = max(position["stop_loss"], highest_price - ATR_STOP_MULTIPLIER * atr)

    stop_hit = price < new_stop
    price_below_ema = price < ema20
    rsi_pullback_from_overbought = rsi > RSI_SELL_THRESHOLD and rsi < prev_rsi

    if stop_hit or price_below_ema or rsi_pullback_from_overbought:
        reason = ("Chạm Trailing Stop (ATR)" if stop_hit else
                  "Giá cắt xuống dưới EMA20" if price_below_ema else
                  "RSI trên vùng quá mua (>75) và bắt đầu giảm")
        event = {
            "ticker": ticker, "signal_type": "SELL",
            "price": round(float(price), 2),
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "strategy_name": STRATEGY_NAME,
            "ta_criteria": ta_criteria,
            "stop_loss": round(new_stop, 2),
            "sell_reason": reason,
            "entry_price": round(position["entry_price"], 2),
            "pnl_pct": round((price - position["entry_price"]) / position["entry_price"] * 100, 2),
        }
        return event, None  # đóng vị thế

    new_position = dict(position)
    new_position["highest_price"] = highest_price
    new_position["stop_loss"] = new_stop
    return None, new_position  # vẫn GIỮ, không phát tín hiệu


# ----------------------------------------------------------------------------
## ----------------------------------------------------------------------------
# 6. Chẩn đoán: từng điều kiện MUA riêng lẻ đang khớp bao nhiêu mã
# ----------------------------------------------------------------------------
def ta_criteria_report(watch_list: list[dict], db_path: str | Path = DEFAULT_DB_PATH,
                       realtime: bool = True) -> str:
    rows = []
    loader = ta_load_price_history_realtime if realtime else ta_load_price_history
    for record in watch_list:
        ticker = record["ticker"]
        hist = loader(ticker, db_path)
        if len(hist) < MIN_BARS_REQUIRED:
            rows.append({"ticker": ticker, "trend_ok": None, "volume_ok": None,
                         "momentum_ok": None, "ghi_chú": "thiếu dữ liệu giá"})
            continue
        hist = ta_compute_indicators(hist)
        row, prev = hist.iloc[-1], hist.iloc[-2]
        if pd.isna(row["rsi14"]) or pd.isna(prev["rsi14"]) or pd.isna(row["volume_sma20"]):
            rows.append({"ticker": ticker, "trend_ok": None, "volume_ok": None,
                         "momentum_ok": None, "ghi_chú": "chỉ báo chưa đủ làm nóng"})
            continue

        trend_ok = row["close"] > row["ema20"] > prev["ema20"]
        volume_ok = row["volume_sma20"] > 0 and row["volume"] >= VOLUME_SPIKE_RATIO * row["volume_sma20"]
        momentum_ok = RSI_BUY_MIN <= row["rsi14"] <= RSI_BUY_MAX
        rows.append({
            "ticker": ticker, "trend_ok": trend_ok, "volume_ok": volume_ok, "momentum_ok": momentum_ok,
            "rsi": round(float(row["rsi14"]), 1),
            "volume_ratio": round(float(row["volume"] / row["volume_sma20"]), 2) if row["volume_sma20"] else None,
            "ghi_chú": "",
        })

    df = pd.DataFrame(rows)
    text = f"Tổng số mã xét (đã qua Lớp 1+2): {len(watch_list)}\n"
    checkable = df[df["trend_ok"].notna()] if not df.empty else df
    
    if not checkable.empty:
        text += f"Đủ dữ liệu để xét: {len(checkable)}/{len(df)}\n"
        for cond, label in [("trend_ok", "EMA20 dốc lên & Giá>EMA20"),
                            ("volume_ok", f"Volume >= {VOLUME_SPIKE_RATIO}x SMA20"),
                            ("momentum_ok", f"RSI trong [{RSI_BUY_MIN}, {RSI_BUY_MAX}]")]:
            text += f" • {label}: {int(checkable[cond].sum())}/{len(checkable)} mã\n"
        
        buy_count = int((checkable['trend_ok'] & checkable['volume_ok'] & checkable['momentum_ok']).sum())
        text += f"🎯 Đạt CẢ 3 (MUA): {buy_count}/{len(checkable)}\n"
    
    text += "\nChi tiết từng mã:\n"
    
    # TRÌNH BÀY DẠNG LIST GỌN ĐỂ TRÁNH VỠ HÀNG TELEGRAM
    for _, r in df.iterrows():
        t = r["ticker"]
        if r["ghi_chú"]:
            text += f"• {t}: ⚠️ {r['ghi_chú']}\n"
            continue
            
        t_ok = "📈" if r["trend_ok"] else "❌"
        v_ok = "🔊" if r["volume_ok"] else "❌"
        m_ok = "⚡" if r["momentum_ok"] else "❌"
        
        if r["trend_ok"] and r["volume_ok"] and r["momentum_ok"]:
            text += f"🟢 {t}: ĐẠT MUA (RSI:{r['rsi']} | Vol:{r['volume_ratio']}x)\n"
        else:
            text += f"• {t}: [Trend:{t_ok} Vol:{v_ok} RSI:{m_ok}]\n"
            
    return text


# ----------------------------------------------------------------------------
# 7. Quét toàn bộ watch_list.json (đã qua Lớp 1 + Lớp 2)
# ----------------------------------------------------------------------------
def ta_run_scan(watch_list: list[dict], db_path: str | Path = DEFAULT_DB_PATH,
                 positions_path: str | Path = DEFAULT_POSITIONS_PATH,
                 realtime: bool = True) -> list[dict]:
    positions = ta_load_positions(positions_path)
    events = []
    loader = ta_load_price_history_realtime if realtime else ta_load_price_history

    for record in watch_list:
        ticker = record["ticker"]
        hist = loader(ticker, db_path)
        if hist.empty:
            continue
        hist = ta_compute_indicators(hist)

        current_position = positions.get(ticker)
        event, new_position = ta_evaluate_symbol(ticker, hist, current_position)

        if event is not None:
            event["fa_criteria"] = {
                "ROE": record.get("roe"),
                "EPS_Growth": record.get("eps_growth_qoq"),
                "Sector": record.get("sector"),
            }
            events.append(event)

        if new_position is not None:
            positions[ticker] = new_position
        elif ticker in positions:
            del positions[ticker]

    ta_save_positions(positions, positions_path)
    print(f"[TA] Quét {len(watch_list)} mã -> {len(events)} sự kiện BUY/SELL, "
          f"đang GIỮ {len(positions)} mã.")
    return events


# ----------------------------------------------------------------------------
# 8. Chạy thử: python strategies/ta_strategy.py [watch_list.json] [market_data.db]
# ----------------------------------------------------------------------------
if __name__ == "__main__":
    import sys

    wl_file = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_WATCH_LIST_PATH
    db_file = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_DB_PATH

    with open(wl_file, "r", encoding="utf-8") as f:
        watch_list = json.load(f)

    print(ta_criteria_report(watch_list, db_file))
    print()
    result = ta_run_scan(watch_list, db_file)
    for e in result:
        print(json.dumps(e, ensure_ascii=False, indent=2))

def ta_build_live_bar(ticker: str, db_path: str | Path = DEFAULT_DB_PATH) -> dict | None:
    """Dựng nến hôm nay từ tick real-time - Đã tối ưu tốc độ đọc SQLite."""
    conn = sqlite3.connect(str(db_path))
    try:
        # TẠO INDEX nếu chưa có -> Giúp SQLite truy vấn ngay lập tức thay vì quét toàn bộ DB
        conn.execute("CREATE INDEX IF NOT EXISTS idx_market_data_lookup ON market_data(symbol, data_type, timestamp);")
        
        today_str = date.today().isoformat()
        df = pd.read_sql_query(
            """
            SELECT price, volume
            FROM market_data
            WHERE symbol = ? AND data_type = 'match_price' AND timestamp >= ?
            ORDER BY timestamp ASC
            """,
            conn, params=(ticker.upper(), today_str),
        )
    finally:
        conn.close()

    if df.empty:
        return None

    return {
        "date": today_str,
        "open": float(df["price"].iloc[0]),
        "high": float(df["price"].max()),
        "low": float(df["price"].min()),
        "close": float(df["price"].iloc[-1]),
        "volume": float(df["volume"].sum()),
    }