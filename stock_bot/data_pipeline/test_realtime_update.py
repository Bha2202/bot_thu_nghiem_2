
import time
import threading

from stock_bot.data_pipeline.collectors.vietcap_collector import (
    VietcapCollector
)

from stock_bot.data_pipeline.processing.vietcap_parser import (
    VietcapParser
)

from stock_bot.data_pipeline.processing.market_validator import (
    MarketValidator
)

from stock_bot.data_pipeline.storage.market_store import (
    MarketStore
)


def main():

    print("=" * 70)
    print("       TEST REALTIME UPDATE")
    print("=" * 70)

    market_store = MarketStore()

    received_count = {
        "match_price": 0,
        "bid_ask": 0
    }

    saved_count = 0

    # =====================================================
    # CALLBACK
    # =====================================================

    def on_data(data_type, data):

        nonlocal saved_count

        # -------------------------------------------------
        # ĐẾM DỮ LIỆU NHẬN ĐƯỢC
        # -------------------------------------------------

        if data_type in received_count:

            received_count[data_type] += 1

        # -------------------------------------------------
        # CHỈ XỬ LÝ MATCH PRICE
        # -------------------------------------------------

        if data_type != "match_price":

            return

        # -------------------------------------------------
        # PARSE
        # -------------------------------------------------

        parsed_data = (
            VietcapParser.parse_match_price(
                data
            )
        )

        if not parsed_data:

            print(
                "[TEST] Parse match_price thất bại."
            )

            return

        # -------------------------------------------------
        # VALIDATE + SAVE
        # -------------------------------------------------

        for item in parsed_data:

            if not MarketValidator.validate(
                item
            ):

                print(
                    "[TEST] Dữ liệu không hợp lệ:",
                    item
                )

                continue

            market_store.save(

                symbol=item["symbol"],

                price=item["price"],

                volume=item["volume"],

                data_type="match_price",

                timestamp=item.get(
                    "timestamp"
                )
            )

            saved_count += 1

    # =====================================================
    # TẠO COLLECTOR
    # =====================================================

    collector = VietcapCollector(

        on_data=on_data,

        market_store=market_store
    )

    try:

        print(
            "\n[TEST] Đang khởi động WebSocket..."
        )

        collector_thread = threading.Thread(

            target=collector.run,

            daemon=True
        )

        collector_thread.start()

        # =================================================
        # THEO DÕI 30 GIÂY
        # =================================================

        print(
            "\n[TEST] Theo dõi realtime trong 30 giây..."
        )

        for second in range(30):

            time.sleep(1)

            fpt = (
                market_store.get_latest(
                    "FPT"
                )
            )

            if fpt:

                print(
                    f"[{second + 1:02d}s] "
                    f"FPT | "
                    f"price={fpt.get('price')} | "
                    f"volume={fpt.get('volume')} | "
                    f"type={fpt.get('data_type')}"
                )

            else:

                print(
                    f"[{second + 1:02d}s] "
                    f"FPT chưa có dữ liệu"
                )

        # =================================================
        # KẾT QUẢ
        # =================================================

        print("\n")
        print("=" * 70)
        print("                    KẾT QUẢ")
        print("=" * 70)

        print(
            "Match price nhận được:",
            received_count["match_price"]
        )

        print(
            "Bid/ask nhận được:",
            received_count["bid_ask"]
        )

        print(
            "Match price đã lưu:",
            saved_count
        )

        print(
            "Số mã trong MarketStore:",
            market_store.count_latest()
        )

        # -------------------------------------------------
        # FPT
        # -------------------------------------------------

        fpt = (
            market_store.get_latest(
                "FPT"
            )
        )

        print(
            "\nDữ liệu FPT cuối cùng:"
        )

        print(fpt)

        # =================================================
        # ĐÁNH GIÁ
        # =================================================

        if (
            received_count["match_price"] > 0
            and saved_count > 0
            and market_store.count_latest() > 0
        ):

            print(
                "\n✅ REALTIME UPDATE HOẠT ĐỘNG"
            )

            print(
                "✅ WebSocket nhận dữ liệu"
            )

            print(
                "✅ Parser xử lý dữ liệu"
            )

            print(
                "✅ Validator kiểm tra dữ liệu"
            )

            print(
                "✅ MarketStore lưu dữ liệu"
            )

        else:

            print(
                "\n❌ REALTIME UPDATE CHƯA HOẠT ĐỘNG"
            )

        print("=" * 70)

    except KeyboardInterrupt:

        print(
            "\n[TEST] Người dùng dừng test."
        )

    finally:

        collector.stop()

        market_store.close()

        print(
            "\n[TEST] Đã đóng test."
        )


if __name__ == "__main__":

    main()
