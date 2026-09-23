import pandas as pd

from stock_bot.data_pipeline.storage.historical_store import HistoricalStore
from stock_bot.data_pipeline.storage.market_store import MarketStore


class DataService:

    # =========================================================
    # KHỞI TẠO
    # =========================================================

    def __init__(self, market_store=None):

        # Kho dữ liệu lịch sử
        self.historical_store = HistoricalStore()

        # Kho dữ liệu realtime
        # Nhận MarketStore từ main để dùng chung cache
        self.market_store = market_store

    # =========================================================
    # LẤY DỮ LIỆU LỊCH SỬ CỦA 1 MÃ
    # =========================================================

    # =========================================================
    # LẤY DỮ LIỆU LỊCH SỬ CỦA 1 MÃ (ĐÃ CHUẨN HÓA ĐÓNG CỬA PHIÊN)
    # =========================================================

    def get_history(self, symbol):
        if not symbol:
            return None

        symbol = symbol.strip().upper()

        rows = self.historical_store.get_history(symbol)

        if not rows:
            return None

        # HistoricalStore trả về list → chuyển sang DataFrame
        df = pd.DataFrame(
            rows,
            columns=[
                "symbol",
                "date",
                "open",
                "high",
                "low",
                "close",
                "volume"
            ]
        )

        if df.empty:
            return None

        # Chuẩn hóa symbol
        df["symbol"] = df["symbol"].astype(str).str.strip().str.upper()

        # Chuẩn hóa ngày
        df["date"] = pd.to_datetime(df["date"], errors="coerce")

        # Chuẩn hóa dữ liệu số
        numeric_columns = ["open", "high", "low", "close", "volume"]
        for column in numeric_columns:
            df[column] = pd.to_numeric(df[column], errors="coerce")

        # Loại dòng thiếu dữ liệu quan trọng
        df = df.dropna(subset=["date", "close", "volume"])

        if df.empty:
            return None

        # -----------------------------------------------------
        # BỔ SUNG: CHỈ LẤY PHIÊN ĐÃ ĐÓNG CỬA HOÀN CHỈNH
        # -----------------------------------------------------
        from datetime import datetime, time
        now = datetime.now()
        today = now.date()
        market_close_time = time(15, 0) # 15:00 là giờ đóng cửa hẳn của thị trường VN

        # Nếu thời điểm hiện tại CHƯA QUA 15:00 ngày hôm nay, 
        # ta loại bỏ dòng của ngày hôm nay khỏi dữ liệu lịch sử.
        if now.time() < market_close_time:
            df = df[df["date"].dt.date < today]

        if df.empty:
            return None

        # =====================================================
        # KIỂM TRA OHLC
        # =====================================================

        ohlc_invalid = (
            (df["high"] < df["low"]) |
            (df["high"] < df["open"]) |
            (df["high"] < df["close"]) |
            (df["low"] > df["open"]) |
            (df["low"] > df["close"])
        )

        invalid_count = int(ohlc_invalid.sum())

        if invalid_count > 0:
            print(
                f"[OHLC FILTER] {symbol}: "
                f"loại {invalid_count} dòng OHLC bất thường "
                f"khỏi dữ liệu phân tích."
            )
            df = df.loc[~ohlc_invalid].copy()

        if df.empty:
            print(
                f"[OHLC FILTER] {symbol}: "
                f"không còn dữ liệu OHLC hợp lệ."
            )
            return None

        # Sắp xếp theo ngày
        df = df.sort_values("date")

        # Đánh lại index
        df = df.reset_index(drop=True)

        return df[
            [
                "symbol",
                "date",
                "open",
                "high",
                "low",
                "close",
                "volume"
            ]
        ]
    # =========================================================
    # KIỂM TRA CÓ DỮ LIỆU LỊCH SỬ HAY KHÔNG
    # =========================================================

    def has_history(self, symbol):

        df = self.get_history(symbol)

        return df is not None and not df.empty
    # =========================================================
    # LẤY NGÀY CUỐI CÙNG CỦA DỮ LIỆU LỊCH SỬ
    # =========================================================

    def get_last_date(self, symbol):

        if not symbol:
            return None

        symbol = symbol.strip().upper()

        return self.historical_store.get_last_date(
            symbol
        )

    # =========================================================
    # LẤY REALTIME MỚI NHẤT CỦA 1 MÃ
    # =========================================================

    def get_latest(self, symbol):

        if not symbol:
            return None

        if self.market_store is None:
            return None

        symbol = symbol.strip().upper()

        return self.market_store.get_latest(
            symbol
        )

    # =========================================================
    # LẤY TOÀN BỘ REALTIME ĐANG CÓ TRONG CACHE
    # =========================================================

    def get_all_latest(self):

        if self.market_store is None:
            return {}

        return self.market_store.get_all_latest()

    # =========================================================
    # ĐẾM SỐ MÃ ĐANG CÓ DỮ LIỆU REALTIME
    # =========================================================

    def count_realtime(self):

        if self.market_store is None:
            return 0

        return self.market_store.count_latest()

    # =========================================================
    # LẤY DANH SÁCH MÃ ĐANG CÓ REALTIME
    # =========================================================

    def get_realtime_symbols(self):

        latest = self.get_all_latest()

        return sorted(
            latest.keys()
        )

    # =========================================================
    # LẤY DANH SÁCH MÃ CÓ DỮ LIỆU LỊCH SỬ
    # =========================================================

    def get_active_symbols(self):

        """
        Lấy các mã đang có dữ liệu lịch sử
        trong database.

        Hiện tại database của dự án có:
        - 1.475 mã có dữ liệu
        - 48 mã được xem là không còn hoạt động
        """

        query = """
            SELECT DISTINCT symbol
            FROM historical_ohlcv
            WHERE symbol IS NOT NULL
            ORDER BY symbol
        """

        try:

            rows = self.historical_store.conn.execute(
                query
            ).fetchall()

            return [
                row[0].upper()
                for row in rows
                if row[0]
            ]

        except Exception as e:

            print(
                f"[DATA SERVICE ERROR] "
                f"Không lấy được danh sách mã: {e}"
            )

            return []

    # =========================================================
    # KIỂM TRA 1 MÃ CÓ DỮ LIỆU REALTIME HAY KHÔNG
    # =========================================================

    def has_realtime(self, symbol):

        return self.get_latest(
            symbol
        ) is not None

    # =========================================================
    # ĐÓNG DATA SERVICE
    # =========================================================

    def close(self):

        self.historical_store.close()


# =============================================================
# TEST DATA SERVICE
# =============================================================

if __name__ == "__main__":

    print("==========================================")
    print("       TEST DATA SERVICE")
    print("==========================================")

    market_store = MarketStore()

    service = DataService(
        market_store=market_store
    )

    try:

        # -----------------------------------------------------
        # TEST 1: LẤY LỊCH SỬ FPT
        # -----------------------------------------------------

        print("\n[TEST 1] Lấy lịch sử FPT")

        df = service.get_history("FPT")

        print(
            f"Số dòng dữ liệu FPT: {len(df)}"
        )

        if not df.empty:

            print("\n5 dòng đầu:")

            print(
                df.head()
            )

            print(
                "\nNgày cuối:",
                service.get_last_date("FPT")
            )

        else:

            print(
                "[WARNING] "
                "Không có dữ liệu lịch sử FPT."
            )

        # -----------------------------------------------------
        # TEST 2: KIỂM TRA LỊCH SỬ
        # -----------------------------------------------------

        print(
            "\n[TEST 2] Kiểm tra dữ liệu lịch sử"
        )

        print(
            "FPT có lịch sử:",
            service.has_history("FPT")
        )

        print(
            "XYZ có lịch sử:",
            service.has_history("XYZ")
        )

        # -----------------------------------------------------
        # TEST 3: LẤY DANH SÁCH MÃ LỊCH SỬ
        # -----------------------------------------------------

        print(
            "\n[TEST 3] Danh sách mã có dữ liệu lịch sử"
        )

        active_symbols = (
            service.get_active_symbols()
        )

        print(
            "Số mã:",
            len(active_symbols)
        )

        print(
            "Một số mã:",
            active_symbols[:20]
        )

        # -----------------------------------------------------
        # TEST 4: GIẢ LẬP REALTIME
        # -----------------------------------------------------

        print(
            "\n[TEST 4] Lưu realtime giả lập"
        )

        market_store.save(
            symbol="FPT",
            price=126.50,
            volume=1500000,
            bid=126.40,
            ask=126.50,
            data_type="match_price",
            timestamp="2026-09-21T04:30:00.000Z"
        )

        # -----------------------------------------------------
        # TEST 5: LẤY REALTIME FPT
        # -----------------------------------------------------

        print(
            "\n[TEST 5] Lấy realtime FPT"
        )

        latest = service.get_latest(
            "FPT"
        )

        print(
            latest
        )

        # -----------------------------------------------------
        # TEST 6: KIỂM TRA REALTIME
        # -----------------------------------------------------

        print(
            "\n[TEST 6] Kiểm tra realtime"
        )

        print(
            "FPT có realtime:",
            service.has_realtime("FPT")
        )

        print(
            "XYZ có realtime:",
            service.has_realtime("XYZ")
        )

        # -----------------------------------------------------
        # TEST 7: ĐẾM CACHE
        # -----------------------------------------------------

        print(
            "\n[TEST 7] Kiểm tra realtime cache"
        )

        print(
            "Số mã trong cache:",
            service.count_realtime()
        )

        # -----------------------------------------------------
        # TEST 8: LẤY TOÀN BỘ CACHE
        # -----------------------------------------------------

        print(
            "\n[TEST 8] Lấy toàn bộ realtime cache"
        )

        all_latest = (
            service.get_all_latest()
        )

        print(
            "Các mã trong cache:",
            list(all_latest.keys())
        )

        # -----------------------------------------------------
        # TEST 9: DANH SÁCH MÃ REALTIME
        # -----------------------------------------------------

        print(
            "\n[TEST 9] Danh sách mã realtime"
        )

        realtime_symbols = (
            service.get_realtime_symbols()
        )

        print(
            "Số mã:",
            len(realtime_symbols)
        )

        print(
            "Danh sách:",
            realtime_symbols
        )

    finally:

        service.close()

        market_store.close()

        print(
            "\n[TEST] Data Service đã đóng."
        )

# =========================================================
   # =========================================================
    # LẤY CHỈ SỐ TÀI CHÍNH CƠ BẢN (FA: ROE, PE, EPS, PB)
    # =========================================================

    def get_fa_data(self, symbol):
        """Lấy thông tin tài chính cơ bản từ API TCBS."""
        if not symbol:
            return {}

        symbol = symbol.strip().upper()
        url = f"https://apipub.tcbs.com.vn/tsci/v1/company/overview?ticker={symbol}"
        
        try:
            import requests
            response = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=3)
            if response.status_code == 200:
                data = response.json()
                return {
                    "ticker": symbol,
                    "roe": round(float(data.get("roe", 0) or 0) * 100, 2),
                    "pe": round(float(data.get("pe", 0) or 0), 2),
                    "pb": round(float(data.get("pb", 0) or 0), 2),
                    "eps": float(data.get("eps", 0) or 0),
                    "eps_growth_yoy": round(float(data.get("epsChange3Yr", 0) or 0) * 100, 2)
                }
        except Exception as e:
            print(f"[DATA SERVICE ERROR] Lỗi lấy FA cho {symbol}: {e}")

        return {}
# -----------------------------------------------------
        # TEST 10: LẤY THÔNG TIN FA (ROE, PE, EPS)
        # -----------------------------------------------------
        print("\n[TEST 10] Lấy thông tin FA HPG")
        fa_info = service.get_fa_data("HPG")
        print(fa_info)