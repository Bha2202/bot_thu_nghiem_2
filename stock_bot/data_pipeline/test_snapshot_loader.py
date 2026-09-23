
from stock_bot.data_pipeline.storage.market_store import (
    MarketStore
)

from stock_bot.data_pipeline.snapshot_loader import (
    SnapshotLoader
)


def main():

    print("=" * 70)
    print("       TEST SNAPSHOT LOADER")
    print("=" * 70)

    market_store = MarketStore()

    loader = SnapshotLoader(
        market_store=market_store
    )

    # =====================================================
    # TEST 1: NẠP SNAPSHOT
    # =====================================================

    print("\n[TEST 1] Nạp snapshot...")

    saved_count = loader.load()

    print(
        f"\nSố mã đã lưu: {saved_count}"
    )

    # =====================================================
    # TEST 2: KIỂM TRA SỐ LƯỢNG CACHE
    # =====================================================

    print("\n[TEST 2] Kiểm tra MarketStore...")

    count = market_store.count_latest()

    print(
        f"Số mã trong realtime cache: {count}"
    )

    # =====================================================
    # TEST 3: KIỂM TRA FPT
    # =====================================================

    print("\n[TEST 3] Kiểm tra FPT...")

    fpt = market_store.get_latest("FPT")

    if fpt:

        print("\nDỮ LIỆU FPT TRONG MARKETSTORE:")

        for key, value in fpt.items():

            print(
                f"{key:15s}: {value}"
            )

    else:

        print(
            "❌ Không tìm thấy FPT trong MarketStore"
        )

    # =====================================================
    # KẾT QUẢ
    # =====================================================

    print("\n")
    print("=" * 70)

    if (
        saved_count == 1523
        and count == 1523
        and fpt is not None
    ):

        print(
            "✅ SNAPSHOT LOADER HOẠT ĐỘNG"
        )

        print(
            "✅ Đã nạp đủ 1.523 mã"
        )

        print(
            "✅ FPT có dữ liệu trong MarketStore"
        )

    else:

        print(
            "❌ SNAPSHOT LOADER CHƯA ĐẠT"
        )

    print("=" * 70)

    market_store.close()


if __name__ == "__main__":

    main()
