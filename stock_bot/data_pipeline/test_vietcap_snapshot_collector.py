from stock_bot.data_pipeline.collectors.vietcap_snapshot import (
    VietcapSnapshotCollector
)


def main():

    print("=" * 70)
    print("       TEST SNAPSHOT COLLECTOR")
    print("=" * 70)

    collector = (
        VietcapSnapshotCollector()
    )

    # =====================================================
    # TEST 1: LẤY TOÀN BỘ
    # =====================================================

    print("\n[TEST 1] Lấy toàn bộ snapshot...")

    data = collector.get_all()

    print(
        f"\nTổng số bản ghi nhận được: "
        f"{len(data)}"
    )

    # =====================================================
    # TEST 2: KIỂM TRA FPT
    # =====================================================

    print("\n[TEST 2] Tìm FPT...")

    fpt = None

    for item in data:

        if item["symbol"] == "FPT":

            fpt = item

            break

    if fpt:

        print("\nDỮ LIỆU FPT:")

        for key, value in fpt.items():

            print(
                f"{key:15s}: {value}"
            )

    else:

        print(
            "❌ Không tìm thấy FPT"
        )

    # =====================================================
    # TEST 3: KIỂM TRA SỐ MÃ KHÔNG TRÙNG
    # =====================================================

    symbols = {
        item["symbol"]
        for item in data
    }

    print(
        "\nSố mã không trùng:",
        len(symbols)
    )

    # =====================================================
    # KẾT QUẢ
    # =====================================================

    print("\n")
    print("=" * 70)

    if fpt and len(symbols) > 1400:

        print(
            "✅ SNAPSHOT COLLECTOR HOẠT ĐỘNG"
        )

        print(
            "✅ Có dữ liệu FPT"
        )

        print(
            "✅ Có hơn 1.400 mã"
        )

    else:

        print(
            "❌ Cần kiểm tra lại snapshot"
        )

    print("=" * 70)


if __name__ == "__main__":

    main()