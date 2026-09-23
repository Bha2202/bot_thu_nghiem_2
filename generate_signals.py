import os
import json
import sqlite3
import pandas as pd
import ta
import concurrent.futures
from datetime import datetime
import config

# Đọc cấu hình từ config, nếu thiếu sẽ tự lấy giá trị mặc định chuẩn
TA_RSI_BUY = getattr(config, 'TA_RSI_BUY', 50.0)
TA_RSI_SELL = getattr(config, 'TA_RSI_SELL', 70.0)
TA_VOLUME_RATIO_MIN = getattr(config, 'TA_VOLUME_RATIO_MIN', 1.2)

MARKET_DB_PATH = os.path.join("data", "market_data.db")
SIGNALS_JSON_PATH = os.path.join("data", "signals.json")

def process_single_ticker(ticker):
    """Phân tích kỹ thuật cho 1 mã, chỉ trả về nếu có tín hiệu MUA hoặc BÁN."""
    try:
        conn = sqlite3.connect(MARKET_DB_PATH)
        df = pd.read_sql_query(f"""
            SELECT date, open, high, low, close, volume
            FROM historical_ohlcv
            WHERE symbol = '{ticker}'
            ORDER BY date ASC
        """, conn)
        conn.close()

        if len(df) < 50:
            return None

        # Tính toán các chỉ báo Technical
        df['price'] = df['close']
        df['EMA20'] = ta.trend.ema_indicator(df['price'], window=20)
        df['EMA50'] = ta.trend.ema_indicator(df['price'], window=50)
        df['MA50'] = df['price'].rolling(50).mean()
        df['RSI_14'] = ta.momentum.rsi(df['price'], window=14)
        df['volume_MA20'] = df['volume'].rolling(20).mean()
        df['volume_ratio'] = df['volume'] / df['volume_MA20']
        
        df = df.dropna()
        if df.empty:
            return None

        latest = df.iloc[-1]

        # Điều kiện lọc MUA
        buy_ok = (
            latest['price'] >= latest['MA50'] and
            latest['EMA20'] > latest['EMA50'] and
            latest['RSI_14'] > TA_RSI_BUY and
            latest['volume_ratio'] >= TA_VOLUME_RATIO_MIN
        )

        # Điều kiện lọc BÁN
        sell_ok = latest['RSI_14'] > TA_RSI_SELL

        if buy_ok:
            return {
                'ticker': ticker,
                'signal_type': 'BUY',
                'price': float(latest['price']),
                'rsi': round(float(latest['RSI_14']), 1),
                'volume_ratio': round(float(latest['volume_ratio']), 2),
                'updated_at': datetime.now().strftime('%H:%M - %d/%m/%Y')
            }
        elif sell_ok:
            return {
                'ticker': ticker,
                'signal_type': 'SELL',
                'price': float(latest['price']),
                'rsi': round(float(latest['RSI_14']), 1),
                'volume_ratio': round(float(latest['volume_ratio']), 2),
                'updated_at': datetime.now().strftime('%H:%M - %d/%m/%Y')
            }

    except Exception:
        pass
    return None

def scan_all_market():
    """Lọc toàn bộ 1.523 mã bằng Đa Luồng và xuất dữ liệu ra signals.json"""
    print("🚀 Bắt đầu quét 1.523 mã tìm tín hiệu MUA/BÁN...")
    
    if not os.path.exists(MARKET_DB_PATH):
        print("❌ DB không tồn tại!")
        return

    conn = sqlite3.connect(MARKET_DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT UPPER(symbol) FROM historical_ohlcv")
    tickers = [row[0] for row in cursor.fetchall() if row[0]]
    conn.close()

    print(f"📊 Tìm thấy {len(tickers)} mã trong Database. Đang chạy lọc...")

    signals = []
    # Dùng 15 luồng để quét cực nhanh
    with concurrent.futures.ThreadPoolExecutor(max_workers=15) as executor:
        results = list(executor.map(process_single_ticker, tickers))
        signals = [r for r in results if r is not None]

    # Ghi kết quả vào file signals.json
    os.makedirs("data", exist_ok=True)
    with open(SIGNALS_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(signals, f, ensure_ascii=False, indent=2)

    print(f"✅ Quét xong! Tìm thấy {len(signals)} mã có tín hiệu khuyến nghị. Đã lưu vào {SIGNALS_JSON_PATH}.")

if __name__ == "__main__":
    scan_all_market()