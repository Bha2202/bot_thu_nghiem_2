
from stock_bot.data_pipeline.storage.market_store import (
    MarketStore
)


def main():

    print("=" * 70)
    print("       TEST MARKET STORE - UPDATE TỪNG PHẦN")
    print("=" * 70)

    store = MarketStore()

    # =====================================================
    # TEST 1: SNAPSHOT
    # =====================================================

    print("\n[TEST 1] Lưu snapshot FPT...")

    store.save(
        symbol="FPT",
        price=65400,
        volume=5782700,
        bid=65400,
        ask=65500,
        data_type="snapshot",
        timestamp="2026-09-21T07:12:54Z"
    )

    print(
        store.get_latest("FPT")
    )

    # =====================================================
    # TEST 2: MATCH PRICE
    # =====================================================

    print(
        "\n[TEST 2] Cập nhật match_price..."
    )

    store.save(
        symbol="FPT",
        price=65500,
        volume=5800000,
        data_type="match_price",
        timestamp="2026-09-21T07:13:00Z"
    )

    fpt = store.get_latest("FPT")

    print(fpt)

    # =====================================================
    # KIỂM TRA BID / ASK CÓ ĐƯỢC GIỮ KHÔNG
    # =====================================================

    if (
        fpt["price"] == 65500
        and fpt["volume"] == 5800000
        and fpt["bid"] == 65400
        and fpt["ask"] == 65500
    ):

        print(
            "✅ Match_price không làm mất bid/ask"
        )

    else:

        print(
            "❌ Match_price đã làm mất dữ liệu cũ"
        )

    # =====================================================
    # TEST 3: BID/ASK UPDATE
    # =====================================================

    print(
        "\n[TEST 3] Cập nhật bid/ask..."
    )

    store.save(
        symbol="FPT",
        bid=65500,
        ask=65600,
        data_type="bid_ask",
        timestamp="2026-09-21T07:13:02Z"
    )

    fpt = store.get_latest("FPT")

    print(fpt)

    # =====================================================
    # KIỂM TRA PRICE / VOLUME CÓ ĐƯỢC GIỮ KHÔNG
    # =====================================================

    if (
        fpt["price"] == 65500
        and fpt["volume"] == 5800000
        and fpt["bid"] == 65500
        and fpt["ask"] == 65600
    ):

        print(
            "✅ Bid/ask update không làm mất "
            "price/volume"
        )

    else:

        print(
            "❌ Bid/ask update làm mất dữ liệu"
        )

    # =====================================================
    # TEST 4: COUNT
    # =====================================================

    print(
        "\n[TEST 4] Kiểm tra số mã..."
    )

    print(
        "Số mã:",
        store.count_latest()
    )

    if store.count_latest() == 1:

        print(
            "✅ MarketStore hoạt động đúng"
        )

    else:

        print(
            "❌ MarketStore có vấn đề"
        )

    print("=" * 70)

    store.close()


if __name__ == "__main__":

    main()
