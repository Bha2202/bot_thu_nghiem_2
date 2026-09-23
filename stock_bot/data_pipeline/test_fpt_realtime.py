import time
import threading

from stock_bot.data_pipeline.collectors.vietcap_collector import VietcapCollector
from stock_bot.data_pipeline.processing.vietcap_parser import VietcapParser
from stock_bot.data_pipeline.processing.market_validator import MarketValidator
from stock_bot.data_pipeline.storage.market_store import MarketStore
from stock_bot.data_pipeline.data_service import DataService


def handle_realtime(
    data_type,
    data,
    market_store
):

    if data_type != "match_price":
        return

    parsed_data = (
        VietcapParser.parse_match_price(data)
    )

    if not parsed_data:
        return

    for item in parsed_data:

        if not MarketValidator.validate(item):
            continue

        symbol = item["symbol"]

        market_store.save(
            symbol=symbol,
            price=item.get("price"),
            volume=item.get("volume"),
            data_type="match_price",
            timestamp=item.get("timestamp")
        )


def main():

    print("=" * 70)
    print("        TEST REALTIME FPT")
    print("=" * 70)

    market_store = MarketStore()

    data_service = DataService(
        market_store=market_store
    )

    collector = VietcapCollector(
        on_data=lambda data_type, data:
            handle_realtime(
                data_type,
                data,
                market_store
            ),
        market_store=market_store
    )

    try:

        print("\n[1] Khởi động Vietcap...")

        thread = threading.Thread(
            target=collector.run,
            daemon=True
        )

        thread.start()

        print(
            "\n[2] Đang chờ dữ liệu FPT..."
        )

        # Chờ tối đa 120 giây
        for second in range(120):

            latest = (
                data_service.get_latest("FPT")
            )

            if latest:

                print("\n")
                print("=" * 70)
                print("ĐÃ NHẬN REALTIME FPT")
                print("=" * 70)

                print(
                    "Mã       :",
                    latest["symbol"]
                )

                print(
                    "Giá      :",
                    latest["price"]
                )

                print(
                    "Khối lượng:",
                    latest["volume"]
                )

                print(
                    "Thời gian:",
                    latest["timestamp"]
                )

                print(
                    "Loại     :",
                    latest["data_type"]
                )

                print("=" * 70)

                print(
                    "\n✅ DataService đã lấy được "
                    "giá realtime FPT."
                )

                return

            print(
                f"\rĐang chờ FPT... "
                f"{second + 1}/120 giây",
                end="",
                flush=True
            )

            time.sleep(1)

        print("\n")
        print("=" * 70)
        print("KHÔNG NHẬN ĐƯỢC MATCH_PRICE FPT")
        print("=" * 70)

        print(
            "Điều này chưa có nghĩa WebSocket lỗi."
        )

        print(
            "Có thể FPT chưa phát sinh giao dịch "
            "mới trong khoảng thời gian test."
        )

    finally:

        collector.stop()

        data_service.close()

        market_store.close()


if __name__ == "__main__":
    main()