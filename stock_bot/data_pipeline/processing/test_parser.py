import sys
from pathlib import Path

# Thêm thư mục gốc project vào Python path
PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))


from vietcap_parser import VietcapParser
from stock_bot.data_pipeline.storage.market_store import MarketStore


# ==========================================
# 1. DỮ LIỆU GIẢ LẬP
# ==========================================

test_data = [
    {
        "symbol": "FPT",
        "price": 100.5,
        "volume": 1200
    },
    {
        "symbol": "VCB",
        "price": 95.2,
        "volume": 800
    }
]


# ==========================================
# 2. PARSE DỮ LIỆU
# ==========================================

parsed_data = VietcapParser.parse_match_price(test_data)


# ==========================================
# 3. KHỞI TẠO MARKET STORE
# ==========================================

store = MarketStore()


# ==========================================
# 4. LƯU DỮ LIỆU
# ==========================================

for item in parsed_data:

    store.save(
        symbol=item["symbol"],
        price=item["price"],
        volume=item["volume"],
        data_type="match_price"
    )


# ==========================================
# 5. GHI VÀO SQLITE
# ==========================================

count = store.flush()

print(f"\nĐã ghi {count} bản ghi vào SQLite")


# ==========================================
# 6. KIỂM TRA CACHE
# ==========================================

print("\n===== DỮ LIỆU MỚI NHẤT =====")

print("FPT:", store.get_latest("FPT"))
print("VCB:", store.get_latest("VCB"))


# ==========================================
# 7. ĐÓNG DATABASE
# ==========================================

store.close()

print("\n===== TEST HOÀN TẤT =====")