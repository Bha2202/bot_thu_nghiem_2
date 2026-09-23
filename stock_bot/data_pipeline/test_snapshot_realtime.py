
import time
import threading

from stock_bot.data_pipeline.collectors.vietcap_collector import (
    VietcapCollector
)

from stock_bot.data_pipeline.snapshot_loader import (
    SnapshotLoader
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
    print("       TEST SNAPSHOT → REALTIME UPDATE")
    print("=" * 70)

    # =====================================================
    # 1. TẠO MARKET STORE
    # =====================================================

    market_store = MarketStore()

    # =====================================================
    # 2. NẠP SNAPSHOT
    # =====================================================

    print("\n[TEST 1] Nạp snapshot ban đầu...")

    snapshot_loader = SnapshotLoader(
        market_store=market_store
    )

    saved_snapshot = snapshot_loader.load()

    print(
        f"\n[TEST] Snapshot đã nạp: "
        f"{saved_snapshot} mã"
    )

    initial_count = (
        market_store.count_latest()
    )

    print(
        f"[TEST] MarketStore ban đầu: "
        f"{initial_count} mã"
    )

    # =====================================================
    # 3. KIỂM TRA SNAPSHOT
    # =====================================================

    if initial_count == 1523:

        print(
            "✅ Snapshot có đủ 1.523 mã"
        )

    else:

        print(
            f"❌ Snapshot chỉ có "
            f"{initial_count} mã"
        )

    # =====================================================
    # 4. LƯU LẠI MỘT MÃ SNAPSHOT
    # =====================================================

    # Chọn FPT để kiểm tra dữ liệu ban đầu.
    # Không yêu cầu WebSocket phải gửi FPT.

    fpt_before = (
        market_store.get_latest("FPT")
    )

    print(
        "\n[TEST] FPT trước WebSocket:"
    )

    print(fpt_before)

    if fpt_before is not None:

        print(
            "✅ FPT đã có dữ liệu snapshot"
        )

    else:

        print(
            "❌ Không có FPT trong snapshot"
        )

    # =====================================================
    # 5. THEO DÕI CÁC MÃ ĐƯỢC WEBSOCKET CẬP NHẬT
    # =====================================================

    received_symbols = set()

    received_count = 0

    saved_count = 0

    def on_data(data_type, data):

        nonlocal received_count
        nonlocal saved_count

        # Chỉ xử lý match_price
        if data_type != "match_price":

            return

        received_count += 1

        # -------------------------------------------------
        # PARSE
        # -------------------------------------------------

        parsed_data = (
            VietcapParser.parse_match_price(
                data
            )
        )

        if not parsed_data:

            return

        # -------------------------------------------------
        # VALIDATE + SAVE
        # -------------------------------------------------

        for item in parsed_data:

            if not MarketValidator.validate(
                item
            ):

                continue

            symbol = item["symbol"]

            # Lưu mã đã nhận
            received_symbols.add(
                symbol
            )

            # Dữ liệu trước khi cập nhật
            before = (
                market_store.get_latest(
                    symbol
                )
            )

            old_price = None

            if before:

                old_price = before.get(
                    "price"
                )

            # ---------------------------------------------
            # Cập nhật MarketStore
            # ---------------------------------------------

            market_store.save(

                symbol=symbol,

                price=item["price"],

                volume=item["volume"],

                data_type="match_price",

                timestamp=item.get(
                    "timestamp"
                )
            )

            saved_count += 1

            # ---------------------------------------------
            # Dữ liệu sau khi cập nhật
            # ---------------------------------------------

            after = (
                market_store.get_latest(
                    symbol
                )
            )

            new_price = None

            if after:

                new_price = after.get(
                    "price"
                )

            print(
                f"\n[REALTIME UPDATE] "
                f"{symbol}"
            )

            print(
                f"    Giá trước : {old_price}"
            )

            print(
                f"    Giá mới   : {new_price}"
            )

    # =====================================================
    # 6. KHỞI ĐỘNG WEBSOCKET
    # =====================================================

    print(
        "\n[TEST 2] Khởi động WebSocket..."
    )

    collector = VietcapCollector(

        on_data=on_data,

        market_store=market_store
    )

    collector_thread = threading.Thread(

        target=collector.run,

        daemon=True
    )

    collector_thread.start()

    # =====================================================
    # 7. CHỜ REALTIME
    # =====================================================

    print(
        "\n[TEST 3] "
        "Theo dõi WebSocket trong 30 giây..."
    )

    for second in range(30):

        time.sleep(1)

        print(
            f"[{second + 1:02d}s] "
            f"Realtime events: "
            f"{received_count} | "
            f"Mã đã cập nhật: "
            f"{len(received_symbols)}"
        )

    # =====================================================
    # 8. KẾT QUẢ
    # =====================================================

    print("\n")
    print("=" * 70)
    print("                    KẾT QUẢ")
    print("=" * 70)

    print(
        f"Snapshot ban đầu       : "
        f"{initial_count} mã"
    )

    print(
        f"Match_price nhận được  : "
        f"{received_count}"
    )

    print(
        f"Match_price đã lưu     : "
        f"{saved_count}"
    )

    print(
        f"Mã được realtime cập nhật: "
        f"{len(received_symbols)}"
    )

    print(
        f"MarketStore cuối cùng  : "
        f"{market_store.count_latest()} mã"
    )

    # =====================================================
    # 9. KIỂM TRA FPT VẪN CÒN
    # =====================================================

    fpt_after = (
        market_store.get_latest("FPT")
    )

    print(
        "\nFPT sau khi WebSocket chạy:"
    )

    print(fpt_after)

    # =====================================================
    # 10. KIỂM TRA KIẾN TRÚC
    # =====================================================

    snapshot_ok = (
        initial_count == 1523
    )

    realtime_ok = (
        received_count > 0
        and saved_count > 0
    )

    fpt_preserved = (
        fpt_after is not None
    )

    # =====================================================
    # 11. KẾT LUẬN
    # =====================================================

    print("\n")

    if snapshot_ok:

        print(
            "✅ SNAPSHOT: PASS"
        )

    else:

        print(
            "❌ SNAPSHOT: FAIL"
        )

    if realtime_ok:

        print(
            "✅ WEBSOCKET REALTIME: PASS"
        )

    else:

        print(
            "❌ WEBSOCKET REALTIME: FAIL"
        )

    if fpt_preserved:

        print(
            "✅ DỮ LIỆU SNAPSHOT ĐƯỢC GIỮ: PASS"
        )

    else:

        print(
            "❌ DỮ LIỆU SNAPSHOT BỊ MẤT: FAIL"
        )

    if (
        snapshot_ok
        and realtime_ok
        and fpt_preserved
    ):

        print("\n")
        print(
            "🎉 SNAPSHOT → REALTIME PIPELINE: PASS"
        )

    else:

        print("\n")
        print(
            "❌ SNAPSHOT → REALTIME PIPELINE: "
            "CẦN KIỂM TRA"
        )

    print("=" * 70)

    # =====================================================
    # 12. ĐÓNG
    # =====================================================

    collector.stop()

    market_store.close()

    print(
        "\n[TEST] Đã đóng toàn bộ."
    )


if __name__ == "__main__":

    main()
