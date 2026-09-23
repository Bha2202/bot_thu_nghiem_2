import requests

from stock_bot.data_pipeline.collectors.dnse_auth import (
    DNSE_API_KEY,
    create_signature,
)


class DNSECollector:
    """
    Collector dự phòng cho dữ liệu giao dịch realtime từ DNSE.

    Giai đoạn đầu:
    - Test 1 mã
    - Lấy giao dịch gần nhất
    - Chưa chạy 1.523 mã
    """

    BASE_URL = "https://openapi.dnse.com.vn"

    def __init__(self, on_data=None):
        self.on_data = on_data

    def get_latest_trade(self, symbol):
        """
        Lấy giao dịch gần nhất của một mã.
        """

        symbol = str(symbol).strip().upper()

        if not symbol:
            return None

        path = f"/price/{symbol}/trades/latest"
        url = self.BASE_URL + path

        # Tạo chữ ký mới cho request
        auth = create_signature(
            method="GET",
            path=path
        )

        headers = {
            "X-API-Key": DNSE_API_KEY,
            "X-Signature": auth["signature"],
            "Date": auth["date"],
            "Accept": "application/json",
        }

        try:
            response = requests.get(
                url,
                headers=headers,
                timeout=10
            )

            if response.status_code != 200:
                print(
                    f"[DNSE] {symbol} "
                    f"HTTP {response.status_code}: "
                    f"{response.text}"
                )
                return None

            data = response.json()

            return self._parse_response(
                data,
                symbol
            )

        except requests.RequestException as e:
            print(f"[DNSE] Lỗi request {symbol}: {e}")
            return None

        except Exception as e:
            print(f"[DNSE] Lỗi xử lý {symbol}: {e}")
            return None

    def _parse_response(self, data, symbol):
        """
        Chuẩn hóa response DNSE thành format
        mà pipeline hiện tại có thể sử dụng.
        """

        trades = data.get("trades", [])

        if not trades:
            print(f"[DNSE] {symbol}: không có giao dịch.")
            return None

        # --------------------------------------------------
        # Ưu tiên G1 = lô chẵn
        # --------------------------------------------------

        g1_trades = [
            trade
            for trade in trades
            if trade.get("boardId") == "G1"
        ]

        if g1_trades:
            trade = g1_trades[0]
        else:
            trade = trades[0]

        match_price = trade.get("matchPrice")
        match_qtty = trade.get("matchQtty")
        total_volume = trade.get("totalVolumeTraded")
        trade_time = trade.get("time")

        if match_price is None:
            print(f"[DNSE] {symbol}: thiếu matchPrice.")
            return None

        # --------------------------------------------------
        # Format chuẩn của pipeline
        # --------------------------------------------------

        result = {
            "symbol": symbol,
            "price": float(match_price),
            "volume": float(
                total_volume
                if total_volume is not None
                else match_qtty or 0
            ),
            "timestamp": trade_time,
            "data_type": "dnse_latest_trade",
        }

        return result

    def fetch_and_callback(self, symbol):
        """
        Lấy dữ liệu và gửi sang callback.
        """

        result = self.get_latest_trade(symbol)

        if result is None:
            return None

        if self.on_data:
            self.on_data(result)

        return result


# ============================================================
# TEST
# ============================================================

if __name__ == "__main__":

    collector = DNSECollector()

    print("==========================================")
    print("       TEST DNSE COLLECTOR")
    print("==========================================")

    result = collector.get_latest_trade("ACB")

    if result:
        print("[DNSE COLLECTOR] ✅ SUCCESS")
        print()
        print("Dữ liệu sau khi chuẩn hóa:")
        print(result)
    else:
        print("[DNSE COLLECTOR] ❌ FAILED")