#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
patch_free_float.py
Tính và cập nhật tỷ lệ free_float_pct chuẩn xác từ endpoint Profile của KBS.
Công thức: Free Float (%) = 100% - Tổng tỷ lệ sở hữu của các cổ đông lớn (OR >= 5.0%).
"""

import json
import os
import time
import requests

JSON_PATH = "data/financial_data.json"
PROFILE_URL = "https://kbbuddywts.kbsec.com.vn/iis-server/investment/stockinfo/profile/{symbol}"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
}

def calculate_free_float(profile_data: dict) -> float:
    """
    Tính Free Float (%) dựa trên mảng Shareholders.
    Chỉ cộng dồn cổ đông sở hữu >= 5.0% (định nghĩa Cổ đông lớn).
    Nếu không có dữ liệu cổ đông lớn, mặc định Free Float = 100.0%.
    """
    shareholders = profile_data.get("Shareholders", [])
    if not isinstance(shareholders, list) or not shareholders:
        return 100.0

    total_major_holding = 0.0
    for sh in shareholders:
        or_val = sh.get("OR")
        if or_val is not None:
            try:
                val = float(or_val)
                # Chỉ trừ những cổ đông lớn sở hữu từ 5% trở lên
                if val >= 5.0:
                    total_major_holding += val
            except (ValueError, TypeError):
                continue

    free_float = 100.0 - total_major_holding
    # Đảm bảo giá trị luôn nằm trong đoạn logic [0, 100]
    free_float = max(0.0, min(100.0, free_float))
    return round(free_float, 2)

def main():
    if not os.path.exists(JSON_PATH):
        print(f"❌ Không tìm thấy file {JSON_PATH}")
        return

    with open(JSON_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    tickers = list(data.keys())
    total = len(tickers)
    print(f"🚀 Bắt đầu cập nhật free_float_pct cho toàn bộ {total} mã...")

    updated_count = 0
    for idx, ticker in enumerate(tickers, start=1):
        url = PROFILE_URL.format(symbol=ticker)
        try:
            res = requests.get(url, headers=HEADERS, timeout=5)
            if res.status_code == 200:
                profile = res.json()
                ff_pct = calculate_free_float(profile)
                data[ticker]["free_float_pct"] = ff_pct
                print(f"[{idx:04d}/{total:04d}] {ticker:<5} ➔ ✅ Free Float: {ff_pct}%")
                updated_count += 1
            else:
                data[ticker]["free_float_pct"] = None
                print(f"[{idx:04d}/{total:04d}] {ticker:<5} ➔ ⚠️ HTTP {res.status_code}")
        except Exception as e:
            data[ticker]["free_float_pct"] = None
            print(f"[{idx:04d}/{total:04d}] {ticker:<5} ➔ ❌ Lỗi kết nối: {e}")

        # Ghi tạm vào file phụ rồi ghi đè để tránh hỏng dữ liệu nếu mất điện/dừng đột ngột
        if idx % 10 == 0 or idx == total:
            tmp_path = JSON_PATH + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, JSON_PATH)

        # Giãn cách nhẹ 0.05s tránh quá tải mạng
        time.sleep(0.05)

    print(f"\n🎉 Hoàn tất cập nhật {updated_count}/{total} mã vào file {JSON_PATH}!")

if __name__ == "__main__":
    main()