import sys
from pathlib import Path

# Đưa thư mục gốc project vào Python path
PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))


from vietcap_parser import VietcapParser
from market_validator import MarketValidator
from stock_bot.data_pipeline.storage.market_store import MarketStore


# =========================================================
# DỮ LIỆU TEST
# =========================================================

test_data = [
    # 1. Dữ liệu hợp lệ
    {
        "symbol": "FPT",
        "price": 100.5,
        "volume": 1200
    },

    # 2. Giá âm → phải loại
    {
        "symbol": "VCB",
        "price": -95.2,
        "volume": 800
    },

    # 3. Volume âm → phải loại
    {
        "symbol": "HPG",
        "price": 25.5,
        "volume": -100
    },

    # 4. Thiếu mã → phải loại
    {
        "price": 50,
        "volume": 1000
    },

    # 5. Giá không phải số → phải loại
    {
        "symbol": "VIC",
        "price": "abc",
        "volume": 1000
    },

    # 6. Dữ liệu hợp lệ
    {
        "symbol": "MWG",
        "price": 60.5,
        "volume": 500
    }
]


# =========================================================
# 1. PARSER
# =========================================================

print("========================================")
print("        TEST DATA PIPELINE")
print("========================================")

parsed_data = VietcapParser.parse_match_price(
    test_data
)

print(
    f"\nParser nhận được: "
    f"{len(parsed_data)} bản ghi"
)


# =========================================================
# 2. MARKET STORE
# =========================================================

store = MarketStore()


valid_count = 0
invalid_count = 0


# =========================================================
# 3. VALIDATOR
# =========================================================

for item in parsed_data:

    if MarketValidator.validate(item):

        store.save(
            symbol=item["symbol"],
            price=item["price"],
            volume=item["volume"],
            data_type="match_price"
        )

        valid_count += 1

    else:

        invalid_count += 1


# =========================================================
# 4. KẾT QUẢ
# =========================================================

print("\n========================================")
print("             KẾT QUẢ")
print("========================================")

print(
    f"Dữ liệu hợp lệ : {valid_count}"
)

print(
    f"Dữ liệu bị loại : {invalid_count}"
)


# =========================================================
# 5. KIỂM TRA CACHE
# =========================================================

print("\n===== CACHE =====")

print(
    "FPT:",
    store.get_latest("FPT")
)

print(
    "MWG:",
    store.get_latest("MWG")
)

print(
    "VCB:",
    store.get_latest("VCB")
)


# =========================================================
# 6. ĐÓNG STORE
# =========================================================

store.close()


print("\n========================================")
print("        TEST PIPELINE HOÀN TẤT")
print("========================================")