
import csv
from pathlib import Path

import requests


class VietcapSnapshotCollector:

    URL = (
        "https://trading.vietcap.com.vn/"
        "api/price/v1/w/priceboard/tickers/price/group"
    )

    HEADERS = {
        "accept": "application/json, text/plain, */*",
        "content-type": "application/json",
        "origin": "https://trading.vietcap.com.vn",
        "referer": "https://trading.vietcap.com.vn/",
        "user-agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/153.0.0.0 Safari/537.36"
        )
    }

    EXCHANGES = [
        "HOSE",
        "HNX",
        "UPCOM"
    ]

    def __init__(self, timeout=15):

        self.timeout = timeout

    # =====================================================
    # ĐỌC DANH SÁCH MÃ CỦA DỰ ÁN
    # =====================================================

    def load_project_symbols(self):

        symbols_path = Path("data/symbols.csv")

        if not symbols_path.exists():

            raise FileNotFoundError(
                f"Không tìm thấy file: {symbols_path}"
            )

        symbols = set()

        with open(
            symbols_path,
            "r",
            encoding="utf-8-sig",
            newline=""
        ) as file:

            reader = csv.DictReader(file)

            for row in reader:

                symbol = row.get("symbol")

                if symbol:

                    symbol = (
                        symbol
                        .strip()
                        .upper()
                    )

                    symbols.add(symbol)

        print(
            f"[SNAPSHOT] Đọc symbols.csv: "
            f"{len(symbols)} mã"
        )

        return symbols

    # =====================================================
    # LẤY SNAPSHOT 1 SÀN
    # =====================================================

    def get_exchange(self, exchange):

        payload = {
            "group": exchange
        }

        response = requests.post(
            self.URL,
            headers=self.HEADERS,
            json=payload,
            timeout=self.timeout
        )

        response.raise_for_status()

        data = response.json()

        if not isinstance(data, list):

            raise ValueError(
                f"Vietcap trả về dữ liệu "
                f"không phải list: {exchange}"
            )

        return data

    # =====================================================
    # CHUẨN HÓA 1 BẢN GHI
    # =====================================================

    def normalize(self, item):

        if not isinstance(item, dict):
            return None

        symbol = item.get("s")

        if not symbol:
            return None

        symbol = str(
            symbol
        ).strip().upper()

        if not symbol:
            return None

        return {

            "symbol": symbol,

            # Giá hiện tại / giá khớp gần nhất
            "price": item.get("c"),

            # Khối lượng khớp
            "volume": item.get("vo"),

            # OHLC
            "open": item.get("op"),
            "high": item.get("h"),
            "low": item.get("l"),

            # Giá bình quân
            "average_price": item.get("avgp"),

            # Bid 1
            "bid_price": item.get("bp1"),
            "bid_volume": item.get("bv1"),

            # Ask 1
            "ask_price": item.get("ap1"),
            "ask_volume": item.get("av1"),

            # Sàn
            "exchange": item.get("bo"),

            # Tên công ty
            "company_name": item.get("orgn"),

            # Mã chứng khoán đầy đủ
            "security_code": item.get("co")
        }

    # =====================================================
    # LỌC THEO DANH SÁCH CỦA DỰ ÁN
    # =====================================================

    def filter_project_symbols(self, records):

        project_symbols = (
            self.load_project_symbols()
        )

        filtered = []

        for record in records:

            symbol = record.get("symbol")

            if not symbol:
                continue

            symbol = (
                symbol
                .strip()
                .upper()
            )

            if symbol in project_symbols:

                filtered.append(record)

        filtered_symbols = {
            record["symbol"]
            for record in filtered
            if record.get("symbol")
        }

        print(
            f"[SNAPSHOT] Vietcap trả về : "
            f"{len(records)} mã"
        )

        print(
            f"[SNAPSHOT] Dự án cho phép  : "
            f"{len(project_symbols)} mã"
        )

        print(
            f"[SNAPSHOT] Sau khi lọc    : "
            f"{len(filtered_symbols)} mã"
        )

        return filtered

    # =====================================================
    # LẤY TOÀN BỘ SNAPSHOT
    # =====================================================

    def get_all(self):

        all_data = []

        for exchange in self.EXCHANGES:

            print(
                f"[SNAPSHOT] Đang lấy {exchange}..."
            )

            data = self.get_exchange(
                exchange
            )

            print(
                f"[SNAPSHOT] {exchange}: "
                f"{len(data)} mã"
            )

            for item in data:

                normalized = self.normalize(
                    item
                )

                if normalized is not None:

                    all_data.append(
                        normalized
                    )

        # Lọc Vietcap 1547 mã
        # thành danh sách 1523 mã của dự án
        return self.filter_project_symbols(
            all_data
        )

    # =====================================================
    # LẤY SNAPSHOT THEO MÃ
    # =====================================================

    def get_symbol(self, symbol):

        if not symbol:
            return None

        symbol = (
            symbol
            .strip()
            .upper()
        )

        all_data = self.get_all()

        for item in all_data:

            if item["symbol"] == symbol:

                return item

        return None

