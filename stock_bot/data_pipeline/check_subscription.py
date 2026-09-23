from stock_bot.data_pipeline.collectors.vietcap_collector import VietcapCollector


def main():

    print("=" * 70)
    print("        KIỂM TRA SUBSCRIPTION VIETCAP")
    print("=" * 70)

    collector = VietcapCollector()

    try:

        # =====================================================
        # 1. TẢI VÀ LỌC DANH SÁCH MÃ
        # =====================================================

        print("\n[1] Đang tải danh sách mã...")

        collector.load_symbols()

        symbols = collector.symbols

        print(
            f"\nTổng số mã sau khi lọc: {len(symbols)}"
        )

        # =====================================================
        # 2. KIỂM TRA DANH SÁCH
        # =====================================================

        print("\n[2] Kiểm tra danh sách mã...")

        unique_symbols = set(
            symbol.upper()
            for symbol in symbols
        )

        print(
            f"Tổng mã                 : {len(symbols)}"
        )

        print(
            f"Mã không trùng           : {len(unique_symbols)}"
        )

        duplicate_count = (
            len(symbols)
            - len(unique_symbols)
        )

        print(
            f"Mã bị trùng              : {duplicate_count}"
        )

        # =====================================================
        # 3. KIỂM TRA THEO SÀN
        # =====================================================

        print("\n[3] Phân bố theo sàn...")

        for exchange, exchange_symbols in (
            collector.symbols_by_exchange.items()
        ):

            print(
                f"{exchange:8s}: "
                f"{len(exchange_symbols)} mã"
            )

        # =====================================================
        # 4. KIỂM TRA BATCH
        # =====================================================

        print("\n[4] Kiểm tra chia batch...")

        batch_size = 100

        batches = [
            symbols[i:i + batch_size]
            for i in range(
                0,
                len(symbols),
                batch_size
            )
        ]

        print(
            f"Tổng số batch: {len(batches)}"
        )

        total_in_batches = sum(
            len(batch)
            for batch in batches
        )

        print(
            f"Tổng mã trong batch: "
            f"{total_in_batches}"
        )

        # =====================================================
        # 5. IN CHI TIẾT TỪNG BATCH
        # =====================================================

        print("\n[5] Chi tiết subscription...")

        for i, batch in enumerate(
            batches,
            start=1
        ):

            print(
                f"Batch {i:2d}/{len(batches)}"
                f" -> {len(batch):3d} mã"
                f" | {batch[0]} -> {batch[-1]}"
            )

        # =====================================================
        # 6. KIỂM TRA CÓ MẤT MÃ KHÔNG
        # =====================================================

        batch_symbols = []

        for batch in batches:

            batch_symbols.extend(batch)

        batch_symbols_set = set(
            symbol.upper()
            for symbol in batch_symbols
        )

        missing_from_batch = (
            unique_symbols
            - batch_symbols_set
        )

        extra_in_batch = (
            batch_symbols_set
            - unique_symbols
        )

        print("\n[6] Kiểm tra tính toàn vẹn...")

        print(
            f"Mã bị mất khỏi batch : "
            f"{len(missing_from_batch)}"
        )

        print(
            f"Mã dư trong batch    : "
            f"{len(extra_in_batch)}"
        )

        # =====================================================
        # 7. KẾT LUẬN
        # =====================================================

        print("\n")
        print("=" * 70)
        print("KẾT QUẢ")
        print("=" * 70)

        if (
            len(unique_symbols) == len(symbols)
            and total_in_batches == len(symbols)
            and len(missing_from_batch) == 0
            and len(extra_in_batch) == 0
        ):

            print(
                "✅ SUBSCRIPTION LIST HOÀN CHỈNH"
            )

            print(
                f"✅ {len(symbols)} mã được "
                f"chia thành {len(batches)} batch."
            )

        else:

            print(
                "❌ DANH SÁCH SUBSCRIPTION CÓ VẤN ĐỀ"
            )

        print("=" * 70)

    finally:

        collector.stop()


if __name__ == "__main__":

    main()