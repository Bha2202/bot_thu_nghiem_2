import sqlite3
from pathlib import Path


DB_PATH = Path("data/market_data.db")


def check_ohlc_errors():

    print("=" * 70)
    print("              KIỂM TRA 425 DÒNG OHLC")
    print("=" * 70)

    conn = sqlite3.connect(DB_PATH)

    try:

        rows = conn.execute("""
            SELECT
                symbol,
                date,
                open,
                high,
                low,
                close,
                volume
            FROM historical_ohlcv
            WHERE
                high < low
                OR high < open
                OR high < close
                OR low > open
                OR low > close
            ORDER BY symbol, date
        """).fetchall()

        print(
            f"\nTổng số dòng bất thường: {len(rows)}"
        )

        if not rows:
            print(
                "\n✅ Không còn dòng OHLC bất thường."
            )
            return

        print("\n20 dòng đầu tiên:")
        print("-" * 70)

        for row in rows[:20]:

            symbol, date, open_, high, low, close, volume = row

            print(
                f"{symbol:8} | "
                f"{date} | "
                f"O={open} "
                f"H={high} "
                f"L={low} "
                f"C={close} "
                f"V={volume}"
            )

        # =====================================================
        # THỐNG KÊ THEO MÃ
        # =====================================================

        print("\n")
        print("SỐ DÒNG BẤT THƯỜNG THEO MÃ")
        print("-" * 70)

        error_by_symbol = {}

        for row in rows:

            symbol = row[0]

            error_by_symbol[symbol] = (
                error_by_symbol.get(symbol, 0) + 1
            )

        sorted_errors = sorted(
            error_by_symbol.items(),
            key=lambda x: x[1],
            reverse=True
        )

        for symbol, count in sorted_errors[:30]:

            print(
                f"{symbol:8}: {count} dòng"
            )

        if len(sorted_errors) > 30:

            print(
                f"... và "
                f"{len(sorted_errors) - 30} mã khác"
            )

        # =====================================================
        # PHÂN LOẠI LOẠI LỖI
        # =====================================================

        high_low_error = 0
        high_open_error = 0
        high_close_error = 0
        low_open_error = 0
        low_close_error = 0

        for row in rows:

            _, _, open_, high, low, close, _ = row

            if high < low:
                high_low_error += 1

            if high < open_:
                high_open_error += 1

            if high < close:
                high_close_error += 1

            if low > open_:
                low_open_error += 1

            if low > close:
                low_close_error += 1

        print("\n")
        print("PHÂN LOẠI BẤT THƯỜNG")
        print("-" * 70)

        print(
            f"High < Low    : {high_low_error}"
        )

        print(
            f"High < Open   : {high_open_error}"
        )

        print(
            f"High < Close  : {high_close_error}"
        )

        print(
            f"Low > Open    : {low_open_error}"
        )

        print(
            f"Low > Close   : {low_close_error}"
        )

    finally:

        conn.close()


if __name__ == "__main__":
    check_ohlc_errors()