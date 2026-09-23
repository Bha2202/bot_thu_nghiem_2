from vnstock.api.quote import Quote
import time


symbols = [
    'ART', 'BCV', 'BHG', 'BT6', 'CMK', 'CMP', 'CNA', 'CPH',
    'DAG', 'EGL', 'FBC', 'GTT', 'HHN', 'HLA', 'HLT', 'HNR',
    'HSA', 'ITA', 'KTT', 'MBN', 'MES', 'MHL', 'MTB', 'NDF',
    'NSS', 'PID', 'PPI', 'PQN', 'SD8', 'SJF', 'SVH', 'TBW',
    'TGG', 'TKA', 'TNA', 'TQW', 'TTB', 'TTZ', 'UMC', 'UTT',
    'VCE', 'VDB', 'VLP', 'VMA', 'VPW', 'VTM', 'VXP', 'X77'
]


co_du_lieu = []
khong_co_du_lieu = []
loi = []


print("=" * 70)
print("KIỂM TRA 48 MÃ THIẾU")
print("=" * 70)


for i, symbol in enumerate(symbols, 1):

    print(f"\n[{i}/48] Đang kiểm tra {symbol}...")

    try:
        quote = Quote(
            symbol=symbol,
            source="KBS"
        )

        df = quote.history(
            start="2025-01-01",
            end="2025-12-31"
        )

        if df is not None and not df.empty:
            so_dong = len(df)

            print(f"  ✓ CÓ DỮ LIỆU: {so_dong} dòng")

            co_du_lieu.append(
                (symbol, so_dong)
            )

        else:
            print("  ✗ KHÔNG CÓ DỮ LIỆU")

            khong_co_du_lieu.append(symbol)

    except Exception as e:

        print(f"  ! LỖI: {e}")

        loi.append(
            (symbol, str(e))
        )

    time.sleep(0.5)


print("\n")
print("=" * 70)
print("KẾT QUẢ")
print("=" * 70)


print("\n1. CÓ DỮ LIỆU:")
for symbol, rows in co_du_lieu:
    print(f"   {symbol}: {rows} dòng")


print("\n2. KHÔNG CÓ DỮ LIỆU:")
for symbol in khong_co_du_lieu:
    print(f"   {symbol}")


print("\n3. BỊ LỖI:")
for symbol, error in loi:
    print(f"   {symbol}: {error}")


print("\n" + "=" * 70)
print(f"Có dữ liệu       : {len(co_du_lieu)} mã")
print(f"Không có dữ liệu : {len(khong_co_du_lieu)} mã")
print(f"Bị lỗi           : {len(loi)} mã")
print("=" * 70)