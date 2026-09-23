import sqlite3
from pathlib import Path


DB_PATH = Path("data/market_data.db")


def check_data_quality():

    print("=" * 60)
    print("          KIỂM TRA CHẤT LƯỢNG DỮ LIỆU")
    print("=" * 60)

    if not DB_PATH.exists():
        print(f"[ERROR] Không tìm thấy database: {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)

    try:

        # =====================================================
        # 1. THỐNG KÊ TỔNG QUAN
        # =====================================================

        total_symbols = conn.execute("""
            SELECT COUNT(DISTINCT symbol)
            FROM historical_ohlcv
        """).fetchone()[0]

        total_rows = conn.execute("""
            SELECT COUNT(*)
            FROM historical_ohlcv
        """).fetchone()[0]

        print("\n[1] TỔNG QUAN")
        print("-" * 60)
        print(f"Tổng số mã có dữ liệu : {total_symbols}")
        print(f"Tổng số dòng dữ liệu  : {total_rows}")

        # =====================================================
        # 2. KIỂM TRA NULL
        # =====================================================

        null_close = conn.execute("""
            SELECT COUNT(*)
            FROM historical_ohlcv
            WHERE close IS NULL
        """).fetchone()[0]

        null_volume = conn.execute("""
            SELECT COUNT(*)
            FROM historical_ohlcv
            WHERE volume IS NULL
        """).fetchone()[0]

        null_date = conn.execute("""
            SELECT COUNT(*)
            FROM historical_ohlcv
            WHERE date IS NULL
               OR date = ''
        """).fetchone()[0]

        print("\n[2] KIỂM TRA DỮ LIỆU THIẾU")
        print("-" * 60)
        print(f"Thiếu date   : {null_date}")
        print(f"Thiếu close  : {null_close}")
        print(f"Thiếu volume : {null_volume}")

        # =====================================================
        # 3. KIỂM TRA GIÁ
        # =====================================================

        invalid_close = conn.execute("""
            SELECT COUNT(*)
            FROM historical_ohlcv
            WHERE close IS NOT NULL
              AND close <= 0
        """).fetchone()[0]

        invalid_open = conn.execute("""
            SELECT COUNT(*)
            FROM historical_ohlcv
            WHERE open IS NOT NULL
              AND open <= 0
        """).fetchone()[0]

        invalid_high = conn.execute("""
            SELECT COUNT(*)
            FROM historical_ohlcv
            WHERE high IS NOT NULL
              AND high <= 0
        """).fetchone()[0]

        invalid_low = conn.execute("""
            SELECT COUNT(*)
            FROM historical_ohlcv
            WHERE low IS NOT NULL
              AND low <= 0
        """).fetchone()[0]

        print("\n[3] KIỂM TRA GIÁ")
        print("-" * 60)
        print(f"Close <= 0 : {invalid_close}")
        print(f"Open  <= 0 : {invalid_open}")
        print(f"High  <= 0 : {invalid_high}")
        print(f"Low   <= 0 : {invalid_low}")

        # =====================================================
        # 4. KIỂM TRA VOLUME
        # =====================================================

        invalid_volume = conn.execute("""
            SELECT COUNT(*)
            FROM historical_ohlcv
            WHERE volume IS NOT NULL
              AND volume < 0
        """).fetchone()[0]

        print("\n[4] KIỂM TRA KHỐI LƯỢNG")
        print("-" * 60)
        print(f"Volume < 0 : {invalid_volume}")

        # =====================================================
        # 5. KIỂM TRA OHLC
        # =====================================================

        invalid_ohlc = conn.execute("""
            SELECT COUNT(*)
            FROM historical_ohlcv
            WHERE
                open IS NOT NULL
                AND high IS NOT NULL
                AND low IS NOT NULL
                AND close IS NOT NULL
                AND (
                    high < low
                    OR high < open
                    OR high < close
                    OR low > open
                    OR low > close
                )
        """).fetchone()[0]

        print("\n[5] KIỂM TRA QUAN HỆ OHLC")
        print("-" * 60)
        print(f"OHLC bất thường : {invalid_ohlc}")

        # =====================================================
        # 6. KIỂM TRA TRÙNG SYMBOL + DATE
        # =====================================================

        duplicate_groups = conn.execute("""
            SELECT COUNT(*)
            FROM (
                SELECT symbol, date
                FROM historical_ohlcv
                GROUP BY symbol, date
                HAVING COUNT(*) > 1
            )
        """).fetchone()[0]

        duplicate_rows = conn.execute("""
            SELECT COALESCE(
                SUM(cnt - 1),
                0
            )
            FROM (
                SELECT COUNT(*) AS cnt
                FROM historical_ohlcv
                GROUP BY symbol, date
                HAVING COUNT(*) > 1
            )
        """).fetchone()[0]

        print("\n[6] KIỂM TRA TRÙNG DỮ LIỆU")
        print("-" * 60)
        print(f"Nhóm symbol + date bị trùng : {duplicate_groups}")
        print(f"Số dòng bị trùng dư         : {duplicate_rows}")

        # =====================================================
        # 7. KIỂM TRA SỐ PHIÊN CỦA TỪNG MÃ
        # =====================================================

        print("\n[7] KIỂM TRA SỐ PHIÊN")
        print("-" * 60)

        min_days = conn.execute("""
            SELECT MIN(cnt)
            FROM (
                SELECT symbol, COUNT(*) AS cnt
                FROM historical_ohlcv
                GROUP BY symbol
            )
        """).fetchone()[0]

        max_days = conn.execute("""
            SELECT MAX(cnt)
            FROM (
                SELECT symbol, COUNT(*) AS cnt
                FROM historical_ohlcv
                GROUP BY symbol
            )
        """).fetchone()[0]

        avg_days = conn.execute("""
            SELECT AVG(cnt)
            FROM (
                SELECT symbol, COUNT(*) AS cnt
                FROM historical_ohlcv
                GROUP BY symbol
            )
        """).fetchone()[0]

        print(f"Ít nhất : {min_days} phiên")
        print(f"Nhiều nhất : {max_days} phiên")
        print(
            f"Trung bình : {avg_days:.2f} phiên"
            if avg_days is not None
            else "Trung bình : 0"
        )

        # Những mã có dưới 100 phiên
        low_history = conn.execute("""
            SELECT symbol, COUNT(*) AS cnt
            FROM historical_ohlcv
            GROUP BY symbol
            HAVING COUNT(*) < 100
            ORDER BY cnt ASC
        """).fetchall()

        print(
            f"Mã có dưới 100 phiên : {len(low_history)}"
        )

        if low_history:
            print("\nDanh sách:")
            for symbol, count in low_history[:30]:
                print(
                    f"  {symbol}: {count} phiên"
                )

            if len(low_history) > 30:
                print(
                    f"  ... và "
                    f"{len(low_history) - 30} mã khác"
                )

        # =====================================================
        # 8. KIỂM TRA NGÀY CUỐI
        # =====================================================

        print("\n[8] KIỂM TRA NGÀY DỮ LIỆU CUỐI")
        print("-" * 60)

        last_date = conn.execute("""
            SELECT MAX(date)
            FROM historical_ohlcv
        """).fetchone()[0]

        print(
            f"Ngày cuối cùng trong database : {last_date}"
        )

        # Thống kê theo ngày cuối
        last_dates = conn.execute("""
            SELECT date, COUNT(DISTINCT symbol) AS cnt
            FROM historical_ohlcv
            GROUP BY date
            ORDER BY date DESC
            LIMIT 10
        """).fetchall()

        print("\n10 ngày gần nhất:")

        for date, count in last_dates:
            print(
                f"  {date}: {count} mã"
            )

        # =====================================================
        # 9. TÌM MÃ CÓ NGÀY CUỐI QUÁ CŨ
        # =====================================================

        old_symbols = conn.execute("""
            SELECT
                symbol,
                MAX(date) AS last_date
            FROM historical_ohlcv
            GROUP BY symbol
            ORDER BY last_date ASC
        """).fetchall()

        print("\n[9] CÁC MÃ CÓ NGÀY CUỐI CŨ NHẤT")
        print("-" * 60)

        for symbol, date in old_symbols[:20]:
            print(
                f"  {symbol}: {date}"
            )

        # =====================================================
        # 10. KIỂM TRA DANH SÁCH symbols.csv
        # =====================================================

        symbols_path = Path(
            "data/symbols.csv"
        )

        csv_symbols = set()

        if symbols_path.exists():

            import csv

            with open(
                symbols_path,
                "r",
                encoding="utf-8-sig",
                newline=""
            ) as file:

                reader = csv.reader(file)

                for row in reader:

                    if not row:
                        continue

                    symbol = row[0].strip().upper()

                    if (
                        symbol
                        and symbol != "SYMBOL"
                    ):
                        csv_symbols.add(symbol)

        db_symbols = set(
            row[0]
            for row in conn.execute("""
                SELECT DISTINCT symbol
                FROM historical_ohlcv
            """).fetchall()
        )

        missing_symbols = sorted(
            csv_symbols - db_symbols
        )

        print("\n[10] SO SÁNH symbols.csv VÀ DATABASE")
        print("-" * 60)
        print(
            f"symbols.csv : {len(csv_symbols)} mã"
        )
        print(
            f"Database    : {len(db_symbols)} mã"
        )
        print(
            f"Có trong CSV nhưng không có DB : "
            f"{len(missing_symbols)} mã"
        )

        if missing_symbols:
            print("\nDanh sách:")
            print(
                ", ".join(missing_symbols)
            )

        # =====================================================
        # 11. TỔNG KẾT
        # =====================================================

        total_problems = (
            null_close
            + null_volume
            + null_date
            + invalid_close
            + invalid_open
            + invalid_high
            + invalid_low
            + invalid_volume
            + invalid_ohlc
            + duplicate_rows
        )

        print("\n")
        print("=" * 60)
        print("                 TỔNG KẾT")
        print("=" * 60)

        if total_problems == 0:

            print(
                "✅ KHÔNG PHÁT HIỆN LỖI DỮ LIỆU CƠ BẢN."
            )

        else:

            print(
                f"⚠ PHÁT HIỆN {total_problems} "
                f"trường hợp cần kiểm tra."
            )

        print(
            f"Mã có dữ liệu : {total_symbols}"
        )

        print(
            f"Tổng số dòng  : {total_rows}"
        )

        print("=" * 60)

    finally:

        conn.close()


if __name__ == "__main__":
    check_data_quality()