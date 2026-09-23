import sys
from pathlib import Path

# Thêm thư mục gốc project
PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))


from market_validator import MarketValidator


# =========================================================
# TEST 1 — DỮ LIỆU HỢP LỆ
# =========================================================

valid_data = {
    "symbol": "FPT",
    "price": 100.5,
    "volume": 1200,
    "bid": 100.4,
    "ask": 100.6
}


# =========================================================
# TEST 2 — GIÁ ÂM
# =========================================================

invalid_price = {
    "symbol": "VCB",
    "price": -95.2,
    "volume": 800
}


# =========================================================
# TEST 3 — KHỐI LƯỢNG ÂM
# =========================================================

invalid_volume = {
    "symbol": "HPG",
    "price": 25.5,
    "volume": -100
}


# =========================================================
# TEST 4 — THIẾU MÃ
# =========================================================

missing_symbol = {
    "price": 50,
    "volume": 1000
}


# =========================================================
# TEST 5 — GIÁ KHÔNG PHẢI SỐ
# =========================================================

invalid_number = {
    "symbol": "VIC",
    "price": "abc",
    "volume": 1000
}


# =========================================================
# CHẠY TEST
# =========================================================

print("===== TEST MARKET VALIDATOR =====")


print(
    "Dữ liệu hợp lệ:",
    MarketValidator.validate(valid_data)
)


print(
    "Giá âm:",
    MarketValidator.validate(invalid_price)
)


print(
    "Khối lượng âm:",
    MarketValidator.validate(invalid_volume)
)


print(
    "Thiếu mã:",
    MarketValidator.validate(missing_symbol)
)


print(
    "Giá không phải số:",
    MarketValidator.validate(invalid_number)
)


print("=================================")