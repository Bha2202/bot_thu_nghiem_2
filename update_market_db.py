import os
import sqlite3
import pandas as pd
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
from vnstock.api.quote import Quote

MARKET_DB_PATH = os.path.join("data", "market_data.db")
SYMBOLS_CSV_PATH = os.path.join("data", "symbols.csv")

def init_db():
    conn = sqlite3.connect(MARKET_DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS historical_ohlcv (
            symbol TEXT,
            date TEXT,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            volume REAL,
            PRIMARY KEY (symbol, date)
        )
    ''')
    conn.commit()
    conn.close()

def fetch_and_save_symbol(symbol):
    try:
        end_date = datetime.now().strftime('%Y-%m-%d')
        start_date = (datetime.now() - timedelta(days=180)).strftime('%Y-%m-%d')
        
        q = Quote(symbol=symbol, source='VCI')
        df = q.history(start=start_date, end=end_date)
        
        if df is not None and not df.empty:
            date_col = 'time' if 'time' in df.columns else 'date'
            df['date'] = pd.to_datetime(df[date_col]).dt.strftime('%Y-%m-%d')
            df['symbol'] = symbol.upper()
            
            # Lưu vào Database
            conn = sqlite3.connect(MARKET_DB_PATH)
            df[['symbol', 'date', 'open', 'high', 'low', 'close', 'volume']].to_sql(
                'historical_ohlcv', conn, if_exists='append', index=False, method='multi'
            )
            conn.close()
            return True
    except Exception:
        pass
    return False

def main():
    print("🚀 Bắt đầu cập nhật dữ liệu cho toàn bộ thị trường...")
    init_db()

    # Lấy danh sách mã từ symbols.csv
    if os.path.exists(SYMBOLS_CSV_PATH):
        df_sym = pd.read_csv(SYMBOLS_CSV_PATH)
        col = 'symbol' if 'symbol' in df_sym.columns else df_sym.columns[0]
        symbols = [str(s).upper().strip() for s in df_sym[col].dropna().unique()]
    else:
        print("❌ Không tìm thấy file data/symbols.csv!")
        return

    print(f"📊 Tìm thấy {len(symbols)} mã cổ phiếu. Đang tải dữ liệu...")

    # Chạy đa luồng tải dữ liệu giá về DB local[cite: 2]
    success_count = 0
    with ThreadPoolExecutor(max_workers=5) as executor:
        results = list(executor.map(fetch_and_save_symbol, symbols))
        success_count = sum(1 for r in results if r)

    print(f"✅ Hoàn tất! Đã cập nhật thành công dữ liệu cho {success_count}/{len(symbols)} mã vào DB[cite: 2].")

if __name__ == "__main__":
    main()