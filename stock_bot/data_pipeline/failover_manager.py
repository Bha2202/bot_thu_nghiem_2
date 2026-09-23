from datetime import datetime, timezone

from stock_bot.data_pipeline.collectors.dnse_collector import DNSECollector


class FailoverManager:
    """
    Quản lý nguồn dữ liệu realtime.

    Vietcap = nguồn chính
    DNSE = nguồn dự phòng
    """

    def __init__(
        self,
        symbols=None,
        failure_threshold=3,
        recovery_threshold=2
    ):
        self.symbols = symbols or []

        self.failure_threshold = failure_threshold
        self.recovery_threshold = recovery_threshold

        self.vietcap_failures = 0
        self.vietcap_recoveries = 0

        self.source = "vietcap"

        self.dnse = DNSECollector()

        self.last_vietcap_data_time = None

    # ============================================================
    # VIETCAP SUCCESS
    # ============================================================

    def record_vietcap_success(self):
        """
        Gọi khi Vietcap hoạt động bình thường
        hoặc nhận được dữ liệu hợp lệ.
        """

        self.last_vietcap_data_time = datetime.now(
            timezone.utc
        )

        self.vietcap_failures = 0

        if self.source == "dnse":

            self.vietcap_recoveries += 1

            print(
                f"[FAILOVER] Vietcap hoạt động lại "
                f"({self.vietcap_recoveries}/"
                f"{self.recovery_threshold})"
            )

            if (
                self.vietcap_recoveries
                >= self.recovery_threshold
            ):

                self.source = "vietcap"

                self.vietcap_recoveries = 0

                print(
                    "[FAILOVER] "
                    "✅ Quay lại nguồn chính: VIETCAP"
                )

        else:
            self.vietcap_recoveries = 0

    # ============================================================
    # VIETCAP FAILURE
    # ============================================================

    def record_vietcap_failure(self):
        """
        Gọi khi Vietcap mất kết nối
        hoặc không hoạt động bình thường.
        """

        self.vietcap_failures += 1

        print(
            f"[FAILOVER] Vietcap lỗi "
            f"({self.vietcap_failures}/"
            f"{self.failure_threshold})"
        )

        if (
            self.vietcap_failures
            >= self.failure_threshold
        ):

            if self.source != "dnse":

                self.source = "dnse"

                self.vietcap_recoveries = 0

                print(
                    "[FAILOVER] "
                    "⚠️ Vietcap mất dữ liệu."
                )

                print(
                    "[FAILOVER] "
                    "🔄 Chuyển sang DNSE."
                )

    # ============================================================
    # CONNECTION SIGNAL
    # ============================================================

    def handle_vietcap_connection(self, connected):
        """
        Nhận tín hiệu kết nối từ VietcapCollector.
        """

        if connected:

            print(
                "[FAILOVER] 🟢 Vietcap ONLINE"
            )

            self.record_vietcap_success()

        else:

            print(
                "[FAILOVER] 🔴 Vietcap OFFLINE"
            )

            self.record_vietcap_failure()

    # ============================================================
    # CURRENT SOURCE
    # ============================================================

    def get_current_source(self):
        """
        Trả về nguồn dữ liệu hiện tại.
        """

        return self.source

    # ============================================================
    # DNSE
    # ============================================================

    def get_dnse_data(self, symbol):
        """
        Lấy dữ liệu từ DNSE khi đang failover.
        """

        if self.source != "dnse":

            print(
                "[FAILOVER] Vietcap vẫn hoạt động. "
                "Không gọi DNSE."
            )

            return None

        try:

            result = self.dnse.get_latest_trade(
                symbol
            )

            if result:

                print(
                    f"[FAILOVER] DNSE → "
                    f"{symbol}: "
                    f"{result['price']}"
                )

            return result

        except Exception as e:

            print(
                f"[FAILOVER] ❌ Lỗi lấy dữ liệu "
                f"DNSE {symbol}: {e}"
            )

            return None

    # ============================================================
    # STATUS
    # ============================================================

    def status(self):

        return {
            "source": self.source,
            "vietcap_failures": self.vietcap_failures,
            "vietcap_recoveries": self.vietcap_recoveries,
            "last_vietcap_data_time": (
                self.last_vietcap_data_time.isoformat()
                if self.last_vietcap_data_time
                else None
            )
        }