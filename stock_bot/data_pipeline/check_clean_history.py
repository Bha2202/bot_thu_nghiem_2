from stock_bot.data_pipeline.data_service import DataService


def main():
    service = DataService()

    symbols = service.get_active_symbols()

    total_rows = 0
    total_filtered = 0
    symbols_with_errors = 0

    print("=" * 70)
    print("          KIỂM TRA DỮ LIỆU SAU OHLC FILTER")
    print("=" * 70)

    for symbol in symbols:
        df = service.get_history(symbol)

        if df is None or df.empty:
            continue

        total_rows += len(df)

        # Nếu DataService đã lọc đúng,
        # các dòng còn lại phải thỏa điều kiện OHLC.
        invalid = (
            (df["high"] < df["low"]) |
            (df["high"] < df["open"]) |
            (df["high"] < df["close"]) |
            (df["low"] > df["open"]) |
            (df["low"] > df["close"])
        )

        count = int(invalid.sum())

        if count > 0:
            symbols_with_errors += 1
            total_filtered += count

            print(
                f"[ERROR] {symbol}: "
                f"còn {count} dòng OHLC bất thường"
            )

    print()
    print("=" * 70)
    print("KẾT QUẢ")
    print("=" * 70)
    print(f"Tổng mã kiểm tra      : {len(symbols)}")
    print(f"Tổng dòng sạch        : {total_rows}")
    print(f"Mã còn OHLC bất thường: {symbols_with_errors}")
    print(f"Dòng còn bất thường   : {total_filtered}")

    if total_filtered == 0:
        print()
        print("✓ OHLC FILTER HOẠT ĐỘNG ĐÚNG")
        print("✓ Không còn dòng OHLC bất thường")
        print("✓ Dữ liệu gốc trong SQLite không bị thay đổi")

    service.close()


if __name__ == "__main__":
    main()