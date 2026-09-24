import requests
from datetime import datetime
from zoneinfo import ZoneInfo

from stock_bot.data_pipeline.collectors.dnse_auth import (
    DNSE_API_KEY,
    create_signature,
)


class DNSECollector:
    """
    Collector dữ liệu từ DNSE.

    Có 2 chức năng:
    1. get_latest_trade() -> realtime
    2. get_history()      -> lịch sử OHLCV, dùng làm backup cho KBS
    """

    BASE_URL = "https://openapi.dnse.com.vn"
    CHART_URL = "https://api.dnse.com.vn"

    def __init__(self, on_data=None):
        self.on_data = on_data

    # =========================================================
    # REALTIME
    # =========================================================

    def get_latest_trade(self, symbol):
        """
        Lấy giao dịch gần nhất của một mã.
        Dùng cho realtime.
        """

        symbol = str(symbol).strip().upper()

        if not symbol:
            return None

        path = f"/price/{symbol}/trades/latest"
        url = self.BASE_URL + path

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
        Chuẩn hóa dữ liệu realtime DNSE.
        """

        trades = data.get("trades", [])

        if not trades:
            print(f"[DNSE] {symbol}: không có giao dịch.")
            return None

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

        result = self.get_latest_trade(symbol)

        if result is None:
            return None

        if self.on_data:
            self.on_data(result)

        return result

    # =========================================================
    # LỊCH SỬ OHLCV
    # =========================================================

    def get_history(self, symbol, start, end):
        """
        Lấy lịch sử OHLCV từ DNSE.

        Dùng làm BACKUP khi KBS không trả dữ liệu.

        Parameters
        ----------
        symbol : str
            Mã cổ phiếu, ví dụ ACB

        start : str
            Ngày bắt đầu, ví dụ 2026-09-22

        end : str
            Ngày kết thúc, ví dụ 2026-09-23

        Returns
        -------
        pandas.DataFrame hoặc None
        """

        import pandas as pd

        symbol = str(symbol).strip().upper()

        if not symbol:
            return None

        try:
            # -------------------------------------------------
            # Chuyển ngày YYYY-MM-DD → Unix timestamp
            # -------------------------------------------------

            timezone = ZoneInfo("Asia/Ho_Chi_Minh")

            start_dt = datetime.strptime(
                start,
                "%Y-%m-%d"
            ).replace(
                hour=0,
                minute=0,
                second=0,
                tzinfo=timezone
            )

            end_dt = datetime.strptime(
                end,
                "%Y-%m-%d"
            ).replace(
                hour=23,
                minute=59,
                second=59,
                tzinfo=timezone
            )

            from_timestamp = int(start_dt.timestamp())
            to_timestamp = int(end_dt.timestamp())

            # -------------------------------------------------
            # Endpoint lịch sử OHLC của DNSE
            # -------------------------------------------------

            path = "/chart-api/v2/ohlcs/stock"

            params = {
                "from": from_timestamp,
                "to": to_timestamp,
                "symbol": symbol,
                "resolution": "1D",
            }

            url = self.CHART_URL + path

            print(
                f"[DNSE HISTORY] {symbol}: "
                f"{start} → {end}"
            )

            response = requests.get(
                url,
                params=params,
                timeout=20
            )

            if response.status_code != 200:
                print(
                    f"[DNSE HISTORY ERROR] {symbol}: "
                    f"HTTP {response.status_code}"
                )
                print(response.text[:500])
                return None

            data = response.json()

            # -------------------------------------------------
            # In response để kiểm tra lần đầu
            # -------------------------------------------------

            print(
                f"[DNSE HISTORY] {symbol}: "
                f"response type = {type(data).__name__}"
            )

            # -------------------------------------------------
            # DNSE thường trả các mảng dữ liệu OHLC
            # -------------------------------------------------

            timestamps = data.get("t", [])
            opens = data.get("o", [])
            highs = data.get("h", [])
            lows = data.get("l", [])
            closes = data.get("c", [])
            volumes = data.get("v", [])

            if not timestamps:
                print(
                    f"[DNSE HISTORY] {symbol}: "
                    f"không có dữ liệu."
                )
                return None

            # -------------------------------------------------
            # Kiểm tra độ dài
            # -------------------------------------------------

            lengths = [
                len(timestamps),
                len(opens),
                len(highs),
                len(lows),
                len(closes),
                len(volumes),
            ]

            min_length = min(lengths)

            if min_length == 0:
                print(
                    f"[DNSE HISTORY] {symbol}: "
                    f"thiếu dữ liệu OHLCV."
                )
                return None

            # -------------------------------------------------
            # Chuẩn hóa thành DataFrame
            # -------------------------------------------------

            rows = []

            for i in range(min_length):

                timestamp = timestamps[i]

                # DNSE có thể trả timestamp dạng giây
                # hoặc milliseconds
                if timestamp > 10_000_000_000:
                    timestamp = timestamp / 1000

                date = datetime.fromtimestamp(
                    timestamp,
                    tz=timezone
                ).strftime("%Y-%m-%d")

                rows.append({
                    "symbol": symbol,
                    "date": date,
                    "open": float(opens[i]),
                    "high": float(highs[i]),
                    "low": float(lows[i]),
                    "close": float(closes[i]),
                    "volume": float(volumes[i]),
                })

            df = pd.DataFrame(rows)

            if df.empty:
                print(
                    f"[DNSE HISTORY] {symbol}: "
                    f"DataFrame rỗng."
                )
                return None

            print(
                f"[DNSE HISTORY] {symbol}: "
                f"lấy được {len(df)} phiên."
            )

            return df[
                [
                    "symbol",
                    "date",
                    "open",
                    "high",
                    "low",
                    "close",
                    "volume",
                ]
            ]

        except requests.RequestException as e:

            print(
                f"[DNSE HISTORY ERROR] "
                f"{symbol}: {e}"
            )

            return None

        except Exception as e:

            print(
                f"[DNSE HISTORY ERROR] "
                f"{symbol}: {e}"
            )

            return None


# =========================================================
# TEST
# =========================================================

if __name__ == "__main__":

    collector = DNSECollector()

    print("==========================================")
    print("       TEST DNSE COLLECTOR")
    print("==========================================")

    # Test realtime
    print("\n--- TEST REALTIME ---")

    result = collector.get_latest_trade("ACB")

    if result:
        print("[REALTIME] SUCCESS")
        print(result)
    else:
        print("[REALTIME] FAILED")

    # Test lịch sử
    print("\n--- TEST HISTORY ---")

    history = collector.get_history(
        "ACB",
        "2026-09-22",
        "2026-09-23"
    )

    if history is not None:
        print("[HISTORY] SUCCESS")
        print(history)
    else:
        print("[HISTORY] FAILED")