import sqlite3
from pathlib import Path
import pandas as pd


class HistoricalStore:
    def __init__(self, db_path="data/market_data.db"):
        self.db_path = db_path

        Path(db_path).parent.mkdir(
            parents=True,
            exist_ok=True
        )

        # Thêm timeout=30 để tránh lỗi 'database is locked' khi đa tiến trình
        self.conn = sqlite3.connect(
            self.db_path,
            timeout=30.0
        )

        self.cursor = self.conn.cursor()

        # Kích hoạt WAL mode để tối ưu đọc/ghi đồng thời
        self.cursor.execute("PRAGMA journal_mode=WAL;")
        self._create_table()

    def _create_table(self):
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS historical_ohlcv (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                date TEXT NOT NULL,
                open REAL,
                high REAL,
                low REAL,
                close REAL,
                volume REAL,
                UNIQUE(symbol, date)
            )
        """)

        self.cursor.execute("""
            CREATE INDEX IF NOT EXISTS
            idx_historical_symbol_date
            ON historical_ohlcv(symbol, date)
        """)

        self.conn.commit()

    def save(self, df: pd.DataFrame) -> int:
        if df is None or df.empty:
            return 0

        records = []

        for _, row in df.iterrows():
            date = str(row["date"])[:10]  # Format YYYY-MM-DD

            symbol = str(row["symbol"]).upper() if "symbol" in row else None
            if not symbol and "ticker" in row:
                symbol = str(row["ticker"]).upper()

            if symbol:
                records.append((
                    symbol,
                    date,
                    float(row["open"]) if pd.notna(row["open"]) else None,
                    float(row["high"]) if pd.notna(row["high"]) else None,
                    float(row["low"]) if pd.notna(row["low"]) else None,
                    float(row["close"]) if pd.notna(row["close"]) else None,
                    float(row["volume"]) if pd.notna(row["volume"]) else 0.0
                ))

        if not records:
            return 0

        # Dùng REPLACE thay cho IGNORE để cập nhật giá chốt phiên mới nhất
        self.cursor.executemany("""
            INSERT OR REPLACE INTO historical_ohlcv
            (
                symbol,
                date,
                open,
                high,
                low,
                close,
                volume
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, records)

        self.conn.commit()
        return self.cursor.rowcount

    def get_history(self, symbol: str) -> list:
        self.cursor.execute("""
            SELECT
                symbol,
                date,
                open,
                high,
                low,
                close,
                volume
            FROM historical_ohlcv
            WHERE symbol = ?
            ORDER BY date ASC
        """, (symbol.upper().strip(),))

        return self.cursor.fetchall()

    def get_last_date(self, symbol: str) -> str:
        self.cursor.execute("""
            SELECT MAX(date)
            FROM historical_ohlcv
            WHERE symbol = ?
        """, (symbol.upper().strip(),))

        result = self.cursor.fetchone()

        if result is None or result[0] is None:
            return None

        return result[0]

    def close(self):
        try:
            self.conn.close()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()