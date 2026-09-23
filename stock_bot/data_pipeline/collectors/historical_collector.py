
from vnstock.api.quote import Quote


class HistoricalCollector:

    def __init__(self, source="KBS"):
        self.source = source

    def get_history(self, symbol, start, end):

        symbol = symbol.upper()

        try:

            print(
                f"[HISTORY] {symbol}: "
                f"đang lấy dữ liệu..."
            )

            # ==================================================
            # KẾT NỐI NGUỒN DỮ LIỆU
            # ==================================================

            quote = Quote(
                symbol=symbol,
                source=self.source
            )

            # ==================================================
            # LẤY DỮ LIỆU OHLCV
            # ==================================================

            df = quote.history(
                start=start,
                end=end
            )

            # ==================================================
            # KIỂM TRA DỮ LIỆU RỖNG
            # ==================================================

            if df is None or df.empty:

                print(
                    f"[NO DATA] {symbol}: "
                    f"nguồn {self.source} không trả dữ liệu "
                    f"trong khoảng {start} → {end}"
                )

                return None

            # ==================================================
            # KIỂM TRA CỘT
            # ==================================================

            required_columns = [
                "time",
                "open",
                "high",
                "low",
                "close",
                "volume"
            ]

            missing_columns = [
                column
                for column in required_columns
                if column not in df.columns
            ]

            if missing_columns:

                print(
                    f"[DATA ERROR] {symbol}: "
                    f"thiếu cột {missing_columns}"
                )

                return None

            # ==================================================
            # CHỈ GIỮ DỮ LIỆU THÔ CẦN THIẾT
            # ==================================================

            df = df[
                required_columns
            ].copy()

            # ==================================================
            # CHUẨN HÓA TÊN CỘT
            # ==================================================

            df.columns = [
                "date",
                "open",
                "high",
                "low",
                "close",
                "volume"
            ]

            # ==================================================
            # LOẠI BỎ DÒNG THIẾU DỮ LIỆU
            # ==================================================

            before_count = len(df)

            df = df.dropna(
                subset=[
                    "date",
                    "close",
                    "volume"
                ]
            )

            removed_count = (
                before_count - len(df)
            )

            if removed_count > 0:

                print(
                    f"[VALIDATION] {symbol}: "
                    f"loại {removed_count} dòng thiếu dữ liệu"
                )

            # ==================================================
            # KIỂM TRA SAU KHI LÀM SẠCH
            # ==================================================

            if df.empty:

                print(
                    f"[NO DATA] {symbol}: "
                    f"không còn dữ liệu hợp lệ sau khi làm sạch."
                )

                return None

            # ==================================================
            # THÊM MÃ CỔ PHIẾU
            # ==================================================

            df["symbol"] = symbol

            # ==================================================
            # ĐƯA SYMBOL LÊN ĐẦU
            # ==================================================

            df = df[
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

            # ==================================================
            # THÔNG BÁO THÀNH CÔNG
            # ==================================================

            print(
                f"[SUCCESS] {symbol}: "
                f"lấy được {len(df)} phiên."
            )

            return df

        # ======================================================
        # LỖI RATE LIMIT
        # ======================================================

        except Exception as e:

            message = str(e).lower()

            rate_limit_keywords = [
                "rate limit",
                "request limit",
                "maximum api request",
                "too many requests",
                "429",
                "wait to retry",
                "giới hạn tối đa số lượt yêu cầu",
                "vượt giới hạn"
            ]

            if any(
                keyword in message
                for keyword in rate_limit_keywords
            ):

                print(
                    f"[RATE LIMIT] {symbol}: "
                    f"nguồn {self.source} đang giới hạn API."
                )

                # Ném lỗi ra ngoài để HistoricalUpdater
                # tự động chờ và thử lại
                raise

            # ==================================================
            # LỖI KHÁC
            # ==================================================

            print(
                f"[API ERROR] "
                f"{symbol}: {e}"
            )

            return None


# ==========================================================
# TEST
# ==========================================================

if __name__ == "__main__":

    collector = HistoricalCollector()

    stocks = {
        "FPT": "HOSE",
        "SHS": "HNX",
        "A32": "UPCOM"
    }

    for symbol, exchange in stocks.items():

        print(
            f"\n===== {symbol} | {exchange} ====="
        )

        df = collector.get_history(
            symbol=symbol,
            start="2025-01-01",
            end="2025-01-10"
        )

        if df is not None:

            print(df)

            print(
                "\nCác cột:",
                list(df.columns)
            )
