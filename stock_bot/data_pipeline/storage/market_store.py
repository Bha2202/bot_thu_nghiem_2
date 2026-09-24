
import sqlite3
import threading
from pathlib import Path


class MarketStore:

    def __init__(
        self,
        db_path="data/market_data.db"
    ):

        self.db_path = db_path

        Path(db_path).parent.mkdir(
            parents=True,
            exist_ok=True
        )

        self.conn = sqlite3.connect(
            self.db_path,
            check_same_thread=False
        )

        self.cursor = self.conn.cursor()

        self.lock = threading.Lock()

        # Cache dữ liệu mới nhất của từng mã
        self.latest = {}

        self._create_database()

    # =====================================================
    # TẠO DATABASE
    # =====================================================

    def _create_database(self):

        with self.lock:

            self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS market_data (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    price REAL,
                    volume REAL,
                    bid REAL,
                    ask REAL,
                    data_type TEXT,
                    timestamp TEXT
                )
            """)

            self.cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_market_symbol
                ON market_data(symbol)
            """)

            self.cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_market_timestamp
                ON market_data(timestamp)
            """)

            self.conn.commit()

    # =====================================================
    # LƯU / CẬP NHẬT DỮ LIỆU
    # =====================================================

    def save(
        self,
        symbol,
        price=None,
        volume=None,
        bid=None,
        ask=None,
        data_type=None,
        timestamp=None
    ):

        if not symbol:
            return

        symbol = (
            str(symbol)
            .strip()
            .upper()
        )

        if not symbol:
            return

        if timestamp is None:
            return
        with self.lock:

            # ---------------------------------------------
            # Lấy dữ liệu cũ
            # ---------------------------------------------

            old_record = (
                self.latest.get(symbol)
            )

            # ---------------------------------------------
            # Nếu đã có dữ liệu cũ
            # thì chỉ cập nhật những trường được truyền vào
            # ---------------------------------------------

            if old_record is not None:

                if price is None:
                    price = old_record.get("price")

                if volume is None:
                    volume = old_record.get("volume")

                if bid is None:
                    bid = old_record.get("bid")

                if ask is None:
                    ask = old_record.get("ask")

            # ---------------------------------------------
            # Tạo record mới
            # ---------------------------------------------

            record = {

                "symbol": symbol,

                "price": price,

                "volume": volume,

                "bid": bid,

                "ask": ask,

                "data_type": data_type,

                "timestamp": timestamp
            }

            # ---------------------------------------------
            # Cập nhật cache
            # ---------------------------------------------

            self.latest[symbol] = record

    # =====================================================
    # LẤY DỮ LIỆU MỚI NHẤT
    # =====================================================

    def get_latest(self, symbol):

        if not symbol:
            return None

        symbol = (
            str(symbol)
            .strip()
            .upper()
        )

        with self.lock:

            record = self.latest.get(
                symbol
            )

            if record is None:
                return None

            # Trả bản copy để bên ngoài
            # không vô tình sửa cache
            return record.copy()

    # =====================================================
    # LẤY TOÀN BỘ DỮ LIỆU MỚI NHẤT
    # =====================================================

    def get_all_latest(self):

        with self.lock:

            return {
                symbol: record.copy()
                for symbol, record
                in self.latest.items()
            }

    # =====================================================
    # ĐẾM SỐ MÃ ĐANG CÓ DỮ LIỆU
    # =====================================================

    def count_latest(self):

        with self.lock:

            return len(
                self.latest
            )

    # =====================================================
    # ĐÓNG STORE
    # =====================================================

    def close(self):

        with self.lock:

            self.conn.close()

        print(
            "[STORE] MarketStore đã đóng."
        )