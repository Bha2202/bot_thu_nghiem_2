import logging
import time

logger = logging.getLogger(__name__)


class FailoverManager:

    def __init__(self):
        self.primary = "vietcap"
        self.backup = "dnse"

        self.active_source = None

        self.vietcap_healthy = False
        self.dnse_healthy = False

        self.last_vietcap_data = None
        self.last_dnse_data = None

    def update_health(self, source, healthy):
        """
        Cập nhật trạng thái của từng nguồn dữ liệu.
        """

        if source == "vietcap":
            self.vietcap_healthy = healthy

        elif source == "dnse":
            self.dnse_healthy = healthy

        self._select_source()

    def _select_source(self):
        """
        Chọn nguồn dữ liệu đang hoạt động.
        Ưu tiên Vietcap, sau đó DNSE.
        """

        if self.vietcap_healthy:
            new_source = "vietcap"

        elif self.dnse_healthy:
            new_source = "dnse"

        else:
            new_source = None

        if new_source != self.active_source:

            if new_source == "vietcap":
                logger.info(
                    "✓ Failover: Đang sử dụng Vietcap"
                )

            elif new_source == "dnse":
                logger.warning(
                    "⚠ Vietcap không khả dụng → "
                    "chuyển sang DNSE"
                )

            else:
                logger.error(
                    "✗ Vietcap và DNSE đều không khả dụng"
                )

            self.active_source = new_source

    def get_active_source(self):
        """
        Trả về nguồn dữ liệu hiện đang được sử dụng.
        """

        return self.active_source

    def is_available(self):
        """
        Kiểm tra có ít nhất một nguồn hoạt động hay không.
        """

        return self.active_source is not None

    def status(self):
        """
        Trả về trạng thái hiện tại.
        """

        return {
            "active_source": self.active_source,
            "vietcap": self.vietcap_healthy,
            "dnse": self.dnse_healthy
        }