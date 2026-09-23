
from datetime import datetime, timezone

from stock_bot.data_pipeline.collectors.vietcap_snapshot import (
    VietcapSnapshotCollector
)


class SnapshotLoader:

    def __init__(self, market_store):

        self.market_store = market_store

        self.collector = (
            VietcapSnapshotCollector()
        )

    def load(self):

        print("=" * 70)
        print("[SNAPSHOT LOADER] Bắt đầu nạp dữ liệu snapshot")
        print("=" * 70)

        # Lấy snapshot 1523 mã
        data = self.collector.get_all()

        if not data:

            print(
                "[SNAPSHOT LOADER] "
                "❌ Không có dữ liệu snapshot."
            )

            return 0

        # Thời điểm lấy snapshot
        timestamp = (
            datetime.now(timezone.utc)
            .isoformat()
        )

        saved_count = 0

        for item in data:

            symbol = item.get("symbol")

            if not symbol:
                continue

            self.market_store.save(

                symbol=symbol,

                price=item.get("price"),

                volume=item.get("volume"),

                bid=item.get("bid_price"),

                ask=item.get("ask_price"),

                data_type="snapshot",

                timestamp=timestamp
            )

            saved_count += 1

        print(
            f"[SNAPSHOT LOADER] "
            f"Đã nạp {saved_count} mã vào MarketStore."
        )

        print(
            f"[SNAPSHOT LOADER] "
            f"Thời điểm snapshot: {timestamp}"
        )

        print("=" * 70)

        return saved_count

