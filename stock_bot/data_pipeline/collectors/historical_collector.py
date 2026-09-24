from vnstock.api.quote import Quote

from stock_bot.data_pipeline.collectors.dnse_collector import DNSECollector


class HistoricalCollector:
    """
    Collector dữ liệu lịch sử.

    Luồng:
        1. KBS = nguồn chính
        2. KBS lỗi / rate limit / không có dữ liệu
           → chuyển sang DNSE
        3. DNSE cũng không có
           → trả None
        4. Không để lỗi một mã làm chết toàn bộ chương trình
    """

    def __init__(self, source="KBS"):
        self.source = source
        self.dnse = DNSECollector()

        # Theo dõi nguồn dữ liệu thực tế
        self.last_source = None

        # Khi KBS rate limit thì đánh dấu để updater biết
        self.kbs_rate_limited = False

    # ==========================================================
    # LẤY DỮ LIỆU LỊCH SỬ
    # ==========================================================

    def get_history(self, symbol, start, end):

        symbol = str(symbol).strip().upper()

        self.last_source = None
        self.kbs_rate_limited = False

        if not symbol:
            return None

        print(
            f"[HISTORY] {symbol}: "
            f"đang lấy dữ liệu từ KBS..."
        )

        # ======================================================
        # 1. THỬ KBS
        # ======================================================

        try:

            quote = Quote(
                symbol=symbol,
                source="KBS"
            )

            df = quote.history(
                start=start,
                end=end
            )

            # --------------------------------------------------
            # KBS trả rỗng
            # --------------------------------------------------

            if df is None or df.empty:

                print(
                    f"[KBS NO DATA] {symbol}: "
                    f"KBS không có dữ liệu."
                )

                return self._get_history_from_dnse(
                    symbol,
                    start,
                    end
                )

            # --------------------------------------------------
            # Kiểm tra cột
            # --------------------------------------------------

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
                    f"[KBS DATA ERROR] {symbol}: "
                    f"thiếu cột {missing_columns}"
                )

                return self._get_history_from_dnse(
                    symbol,
                    start,
                    end
                )

            # --------------------------------------------------
            # Chuẩn hóa
            # --------------------------------------------------

            df = df[required_columns].copy()

            df.columns = [
                "date",
                "open",
                "high",
                "low",
                "close",
                "volume"
            ]

            # --------------------------------------------------
            # Làm sạch
            # --------------------------------------------------

            df = df.dropna(
                subset=[
                    "date",
                    "close",
                    "volume"
                ]
            )

            if df.empty:

                print(
                    f"[KBS NO DATA] {symbol}: "
                    f"không còn dữ liệu hợp lệ."
                )

                return self._get_history_from_dnse(
                    symbol,
                    start,
                    end
                )

            # --------------------------------------------------
            # Chuẩn hóa ngày
            # --------------------------------------------------

            try:

                import pandas as pd

                df["date"] = (
                    pd.to_datetime(df["date"])
                    .dt.strftime("%Y-%m-%d")
                )

            except Exception as e:

                print(
                    f"[KBS DATE ERROR] {symbol}: {e}"
                )

                return self._get_history_from_dnse(
                    symbol,
                    start,
                    end
                )

            # --------------------------------------------------
            # Thêm symbol
            # --------------------------------------------------

            df["symbol"] = symbol

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

            self.last_source = "KBS"

            print(
                f"[KBS SUCCESS] {symbol}: "
                f"lấy được {len(df)} phiên."
            )

            return df

        # ======================================================
        # 2. KBS LỖI
        # ======================================================

        except Exception as e:

            message = str(e).lower()

            rate_limit_keywords = [
                "rate limit",
                "rate_limit",
                "request limit",
                "maximum api request",
                "too many requests",
                "429",
                "wait to retry",
                "giới hạn tối đa số lượt yêu cầu",
                "vượt giới hạn",
                "rate limit exceeded"
            ]

            is_rate_limit = any(
                keyword in message
                for keyword in rate_limit_keywords
            )

            if is_rate_limit:

                self.kbs_rate_limited = True

                print(
                    f"[KBS RATE LIMIT] {symbol}: "
                    f"KBS đã đạt giới hạn API."
                )

                print(
                    f"[FALLBACK] {symbol}: "
                    f"chuyển sang DNSE."
                )

            else:

                print(
                    f"[KBS ERROR] {symbol}: {e}"
                )

                print(
                    f"[FALLBACK] {symbol}: "
                    f"KBS không lấy được → DNSE."
                )

            # ==================================================
            # KBS lỗi → DNSE
            # ==================================================

            return self._get_history_from_dnse(
                symbol,
                start,
                end
            )

    # ==========================================================
    # DNSE DỰ PHÒNG
    # ==========================================================

    def _get_history_from_dnse(
        self,
        symbol,
        start,
        end
    ):

        print(
            f"[DNSE FALLBACK] {symbol}: "
            f"đang lấy dữ liệu lịch sử..."
        )

        try:

            df = self.dnse.get_history(
                symbol=symbol,
                start=start,
                end=end
            )

            if df is None or df.empty:

                print(
                    f"[DNSE NO DATA] {symbol}: "
                    f"DNSE cũng không có dữ liệu."
                )

                return None

            required_columns = [
                "symbol",
                "date",
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
                    f"[DNSE DATA ERROR] {symbol}: "
                    f"thiếu cột {missing_columns}"
                )

                return None

            df = df[
                required_columns
            ].copy()

            self.last_source = "DNSE"

            print(
                f"[DNSE FALLBACK SUCCESS] {symbol}: "
                f"lấy được {len(df)} phiên."
            )

            return df

        except Exception as e:

            print(
                f"[DNSE FALLBACK ERROR] "
                f"{symbol}: {e}"
            )

            return None


# ==========================================================
# TEST
# ==========================================================

if __name__ == "__main__":

    collector = HistoricalCollector(
        source="KBS"
    )

    print(
        "=========================================="
    )

    print(
        "     TEST KBS → DNSE FALLBACK"
    )

    print(
        "=========================================="
    )

    df = collector.get_history(
        symbol="A32",
        start="2026-09-22",
        end="2026-09-23"
    )

    print()

    if df is not None:

        print("[TEST SUCCESS]")
        print()
        print(df)
        print()
        print("Nguồn:", collector.last_source)
        print("Các cột:", list(df.columns))

    else:

        print(
            "[TEST NO DATA] "
            "KBS và DNSE đều không có dữ liệu."
        )