import sys
from pathlib import Path
import json
import logging
import time
import threading
import csv
from typing import Callable, Optional

import requests
import socketio


# =========================================================
# LOGGER
# =========================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

logger = logging.getLogger(__name__)


# =========================================================
# PROJECT ROOT
# =========================================================

PROJECT_ROOT = Path(__file__).resolve().parents[3]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# =========================================================
# MARKET STORE
# =========================================================

from stock_bot.data_pipeline.storage.market_store import MarketStore


class VietcapCollector:

    # =========================================================
    # VIETCAP CONFIG
    # =========================================================

    BASE_URL = "https://trading.vietcap.com.vn"

    SOCKET_PATH = "ws/price/socket.io"

    INDEX_SYMBOLS = [
        "VNINDEX",
        "VN30",
        "VN100",
        "HNXIndex",
        "HNX30",
        "HNXUpcomIndex",
    ]

    BATCH_SIZE = 100
    SUBSCRIBE_DELAY = 0.1
    RECONNECT_DELAY = 3

    # =========================================================
    # INIT
    # =========================================================

    def __init__(
        self,
        on_data: Optional[Callable] = None,
        market_store: Optional[MarketStore] = None,
        on_connection_change: Optional[Callable] = None
    ):

        self.on_data = on_data
        self.on_connection_change = on_connection_change
        # -----------------------------------------------------
        # MARKET STORE
        # -----------------------------------------------------

        self.market_store = (
            market_store
            if market_store is not None
            else MarketStore()
        )

        # -----------------------------------------------------
        # DANH SÁCH MÃ
        # -----------------------------------------------------

        self.symbols = []

        self.symbols_by_exchange = {
            "HOSE": [],
            "HNX": [],
            "UPCOM": []
        }

        # -----------------------------------------------------
        # SOCKET.IO
        # -----------------------------------------------------

        self.sio = socketio.Client(
            logger=False,
            engineio_logger=False,
            reconnection=False
        )

        self.connected = False
        self.running = False

        # -----------------------------------------------------
        # CHỐNG STOP NHIỀU LẦN
        # -----------------------------------------------------

        self._stop_lock = threading.Lock()
        self._stopped = False

        # -----------------------------------------------------
        # EVENTS
        # -----------------------------------------------------

        self._register_events()

    # =========================================================
    # 1. LẤY DANH SÁCH MÃ
    # =========================================================

    def load_symbols(self):

        exchanges = [
            "HOSE",
            "HNX",
            "UPCOM"
        ]

        all_symbols = []

        headers = {
            "Content-Type": "application/json",

            "User-Agent": (
                "Mozilla/5.0 "
                "(Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/120.0.0.0 "
                "Safari/537.36"
            ),

            "Referer": (
                "https://trading.vietcap.com.vn/"
            ),

            "Origin": (
                "https://trading.vietcap.com.vn"
            )
        }

        url = (
            f"{self.BASE_URL}"
            "/api/price/v1/w/priceboard/"
            "tickers/price/group"
        )

        # =====================================================
        # 1. LẤY DANH SÁCH TỪ VIETCAP
        # =====================================================

        for exchange in exchanges:

            try:

                response = requests.post(
                    url,
                    json={
                        "group": exchange
                    },
                    headers=headers,
                    timeout=10
                )

                logger.info(
                    f"Vietcap {exchange}: "
                    f"HTTP {response.status_code}"
                )

                if response.status_code != 200:

                    logger.error(
                        f"Không lấy được danh sách "
                        f"{exchange}"
                    )

                    continue

                data = response.json()

                # -------------------------------------------------
                # TÌM MÃ
                # -------------------------------------------------

                symbols = self._extract_symbols(data)

                # -------------------------------------------------
                # LOẠI TRÙNG
                # -------------------------------------------------

                symbols = list(
                    dict.fromkeys(symbols)
                )

                if not symbols:

                    logger.warning(
                        f"Vietcap trả về 0 mã "
                        f"cho {exchange}."
                    )

                    logger.warning(
                        f"Kiểu dữ liệu response: "
                        f"{type(data).__name__}"
                    )

                    logger.warning(
                        f"Sample JSON: "
                        f"{str(data)[:1000]}"
                    )

                    continue

                self.symbols_by_exchange[
                    exchange
                ] = symbols

                all_symbols.extend(
                    symbols
                )

                logger.info(
                    f"{exchange}: "
                    f"{len(symbols)} mã"
                )

            except requests.RequestException as e:

                logger.error(
                    f"Lỗi HTTP khi lấy danh sách "
                    f"{exchange}: {e}"
                )

            except Exception as e:

                logger.exception(
                    f"Lỗi lấy danh sách "
                    f"{exchange}: {e}"
                )

        # =====================================================
        # 2. LOẠI TRÙNG DANH SÁCH VIETCAP
        # =====================================================

        all_symbols = list(
            dict.fromkeys(all_symbols)
        )

        logger.info(
            f"Vietcap trả về tổng cộng: "
            f"{len(all_symbols)} mã"
        )

        # =====================================================
        # 3. FALLBACK NẾU VIETCAP KHÔNG TRẢ DANH SÁCH
        # =====================================================

        if not all_symbols:

            logger.warning(
                "Không lấy được danh sách mã "
                "từ Vietcap."
            )

            logger.info(
                "Chuyển sang đọc "
                "data/symbols.csv..."
            )

            csv_symbols = (
                self._load_symbols_from_csv()
            )

            if csv_symbols:

                all_symbols = csv_symbols

                logger.info(
                    f"Đã tải {len(all_symbols)} mã "
                    f"từ data/symbols.csv"
                )

            else:

                logger.error(
                    "Không thể lấy danh sách mã "
                    "từ Vietcap hoặc symbols.csv."
                )

        # =====================================================
        # 4. ĐỌC DANH SÁCH CHUẨN CỦA DỰ ÁN
        # =====================================================

        project_symbols = set(
            self._load_symbols_from_csv()
        )

        # =====================================================
        # 5. LỌC VIETCAP THEO symbols.csv
        # =====================================================

        if project_symbols:

            vietcap_symbols = set(
                symbol.strip().upper()
                for symbol in all_symbols
                if symbol
            )

            filtered_symbols = (
                vietcap_symbols
                & project_symbols
            )

            extra_symbols = (
                vietcap_symbols
                - project_symbols
            )

            missing_symbols = (
                project_symbols
                - vietcap_symbols
            )

            logger.info("")

            logger.info(
                "=========================================="
            )

            logger.info(
                "       KẾT QUẢ LỌC DANH SÁCH MÃ"
            )

            logger.info(
                "=========================================="
            )

            logger.info(
                f"Vietcap trả về       : "
                f"{len(vietcap_symbols)} mã"
            )

            logger.info(
                f"Danh sách dự án     : "
                f"{len(project_symbols)} mã"
            )

            logger.info(
                f"Được phép realtime   : "
                f"{len(filtered_symbols)} mã"
            )

            logger.info(
                f"Vietcap dư           : "
                f"{len(extra_symbols)} mã"
            )

            logger.info(
                f"Dự án thiếu trên VC : "
                f"{len(missing_symbols)} mã"
            )

            logger.info(
                "=========================================="
            )

            # -------------------------------------------------
            # VIETCAP DƯ
            # -------------------------------------------------

            if extra_symbols:

                logger.info(
                    "Một số mã Vietcap bị loại: "
                    + ", ".join(
                        sorted(extra_symbols)[:20]
                    )
                )

                if len(extra_symbols) > 20:

                    logger.info(
                        f"... và "
                        f"{len(extra_symbols) - 20} mã khác."
                    )

            # -------------------------------------------------
            # DỰ ÁN THIẾU TRÊN VIETCAP
            # -------------------------------------------------

            if missing_symbols:

                logger.warning(
                    "Một số mã dự án không có "
                    "trên Vietcap: "
                    + ", ".join(
                        sorted(missing_symbols)[:20]
                    )
                )

                if len(missing_symbols) > 20:

                    logger.warning(
                        f"... và "
                        f"{len(missing_symbols) - 20} mã khác."
                    )

            # -------------------------------------------------
            # DANH SÁCH CUỐI CÙNG
            # -------------------------------------------------

            all_symbols = sorted(
                filtered_symbols
            )

        else:

            logger.warning(
                "Không đọc được symbols.csv."
            )

            logger.warning(
                "Sử dụng toàn bộ danh sách "
                "Vietcap làm fallback."
            )

        # =====================================================
        # 6. LƯU DANH SÁCH CUỐI CÙNG
        # =====================================================

        self.symbols = list(
            dict.fromkeys(all_symbols)
        )

        logger.info(
            f"TỔNG CỘNG SAU KHI LỌC: "
            f"{len(self.symbols)} mã"
        )

        return self.symbols

    # =========================================================
    # 1.1. ĐỌC SYMBOLS.CSV
    # =========================================================

    def _load_symbols_from_csv(self):

        csv_path = (
            PROJECT_ROOT
            / "data"
            / "symbols.csv"
        )

        if not csv_path.exists():

            logger.error(
                f"Không tìm thấy file: "
                f"{csv_path}"
            )

            return []

        symbols = []

        try:

            with open(
                csv_path,
                "r",
                encoding="utf-8-sig",
                newline=""
            ) as file:

                reader = csv.DictReader(file)

                if not reader.fieldnames:

                    logger.error(
                        "symbols.csv không có header."
                    )

                    return []

                symbol_column = None

                for column in reader.fieldnames:

                    normalized = (
                        str(column)
                        .strip()
                        .lower()
                        .replace(" ", "")
                        .replace("_", "")
                    )

                    if normalized in {
                        "symbol",
                        "ticker",
                        "code",
                        "stockcode",
                        "ma",
                        "mã"
                    }:

                        symbol_column = column

                        break

                if symbol_column is None:

                    symbol_column = (
                        reader.fieldnames[0]
                    )

                    logger.warning(
                        "Không xác định được "
                        "cột mã cổ phiếu."
                    )

                    logger.warning(
                        f"Dùng cột đầu tiên: "
                        f"{symbol_column}"
                    )

                for row in reader:

                    value = row.get(
                        symbol_column
                    )

                    if not isinstance(
                        value,
                        str
                    ):
                        continue

                    symbol = (
                        value
                        .strip()
                        .upper()
                    )

                    if not symbol:
                        continue

                    if not (
                        2 <= len(symbol) <= 10
                    ):
                        continue

                    if not symbol.isalnum():
                        continue

                    symbols.append(
                        symbol
                    )

            symbols = list(
                dict.fromkeys(symbols)
            )

            logger.info(
                f"Đọc symbols.csv: "
                f"{len(symbols)} mã"
            )

            return symbols

        except Exception as e:

            logger.exception(
                f"Lỗi đọc symbols.csv: {e}"
            )

            return []

    # =========================================================
    # 2. TÌM SYMBOL TRONG RESPONSE VIETCAP
    # =========================================================

    def _extract_symbols(self, data):

        symbols = []

        valid_keys = {
            "s",
            "sym",
            "symbol",
            "ticker",
            "code",
            "stocksymbol",
            "secsymbol",
            "tickersymbol",
            "stockcode",
            "stock_code"
        }

        def add_symbol(value):

            if not isinstance(
                value,
                str
            ):
                return

            symbol = (
                value
                .strip()
                .upper()
            )

            if not symbol:
                return

            if not (
                2 <= len(symbol) <= 10
            ):
                return

            if not symbol.isalnum():
                return

            symbols.append(
                symbol
            )

        def recursive_find(obj):

            if isinstance(
                obj,
                dict
            ):

                for key, value in obj.items():

                    key_lower = str(
                        key
                    ).lower()

                    if key_lower in valid_keys:

                        if isinstance(
                            value,
                            str
                        ):

                            add_symbol(
                                value
                            )

                        elif isinstance(
                            value,
                            list
                        ):

                            for item in value:

                                add_symbol(
                                    item
                                )

                    recursive_find(
                        value
                    )

            elif isinstance(
                obj,
                list
            ):

                for item in obj:

                    recursive_find(
                        item
                    )

            elif isinstance(
                obj,
                str
            ):

                text = obj.strip()

                if not text:
                    return

                if (
                    text.startswith("{")
                    or text.startswith("[")
                ):

                    try:

                        nested = json.loads(
                            text
                        )

                        recursive_find(
                            nested
                        )

                        return

                    except (
                        json.JSONDecodeError,
                        TypeError
                    ):

                        pass

                if (
                    2 <= len(text) <= 10
                    and text.isalnum()
                ):

                    add_symbol(
                        text
                    )

        recursive_find(
            data
        )

        return list(
            dict.fromkeys(
                symbols
            )
        )

    # =========================================================
    # 3. SOCKET.IO EVENTS
    # =========================================================

    def _register_events(self):

        @self.sio.event
        def connect():

            self.connected = True

            logger.info(
                "✓ Đã kết nối Vietcap WebSocket"
            )
            if self.on_connection_change:
                self.on_connection_change(True)

            try:

                self._subscribe()

            except Exception as e:

                logger.exception(
                    f"Lỗi subscribe Vietcap: {e}"
                )

        @self.sio.event
        def disconnect():

            self.connected = False

            logger.warning(
                "⚠ Vietcap WebSocket bị ngắt kết nối"
            )
            if self.on_connection_change:
                self.on_connection_change(False)
        # -----------------------------------------------------
        # CHỈ NHẬN MATCH PRICE
        # -----------------------------------------------------

        @self.sio.on(
            "w-match-price"
        )
        def on_match_price(data):

            self._handle_data(
                "match_price",
                data
            )

        # -----------------------------------------------------
        # KHÔNG SUBSCRIBE BID/ASK
        # -----------------------------------------------------
        #
        # Không đăng ký event w-bid-ask vì phần realtime
        # hiện tại chỉ cần giá khớp + khối lượng.
        #
        # Bid/Ask không thuộc dữ liệu cần thiết của pipeline
        # hiện tại và làm tăng lượng dữ liệu xử lý.
        #

        # -----------------------------------------------------
        # INDEX
        # -----------------------------------------------------

        @self.sio.on(
            "index"
        )
        def on_index(data):

            self._handle_data(
                "index",
                data
            )

    # =========================================================
    # 4. SUBSCRIBE REALTIME
    # =========================================================

    def _subscribe(self):

        if not self.connected:

            logger.warning(
                "Chưa kết nối WebSocket, "
                "không thể subscribe."
            )

            return

        if not self.symbols:

            logger.warning(
                "Chưa có danh sách mã "
                "để subscribe."
            )

            return

        # -----------------------------------------------------
        # INDEX
        # -----------------------------------------------------

        index_payload = json.dumps(
            {
                "symbols": self.INDEX_SYMBOLS
            },
            separators=(
                ",",
                ":"
            )
        )

        try:

            self.sio.emit(
                "index",
                index_payload
            )

            logger.info(
                "Đã subscribe dữ liệu index."
            )

        except Exception as e:

            logger.warning(
                f"Không thể subscribe index: {e}"
            )

        # -----------------------------------------------------
        # CHIA SYMBOL THÀNH CÁC NHÓM
        # -----------------------------------------------------

        batches = [
            self.symbols[
                i:i + self.BATCH_SIZE
            ]

            for i in range(
                0,
                len(self.symbols),
                self.BATCH_SIZE
            )
        ]

        logger.info(
            f"Subscribe "
            f"{len(self.symbols)} mã "
            f"→ {len(batches)} nhóm"
        )

        # -----------------------------------------------------
        # SUBSCRIBE TỪNG NHÓM
        # -----------------------------------------------------

        for (
            batch_number,
            batch
        ) in enumerate(
            batches,
            start=1
        ):

            if not self.running:
                break

            if not self.connected:

                logger.warning(
                    "WebSocket mất kết nối "
                    "trong lúc subscribe."
                )

                break

            payload = json.dumps(
                {
                    "symbols": batch
                },
                separators=(
                    ",",
                    ":"
                )
            )

            # -------------------------------------------------
            # CHỈ MATCH PRICE
            # -------------------------------------------------

            self.sio.emit(
                "w-match-price",
                payload
            )

            logger.info(
                f"Đã subscribe nhóm "
                f"{batch_number}/"
                f"{len(batches)} "
                f"({len(batch)} mã)"
            )

            time.sleep(
                self.SUBSCRIBE_DELAY
            )

    # =========================================================
    # 5. HANDLE DATA
    # =========================================================

    def _handle_data(
        self,
        data_type,
        data
    ):

        try:

            # -------------------------------------------------
            # INDEX KHÔNG ĐƯA VÀO PIPELINE HIỆN TẠI
            # -------------------------------------------------
            print("🔥 VIETCAP REALTIME:", data, flush=True)
            if data_type == "index":

                return

            # -------------------------------------------------
            # CHỈ XỬ LÝ MATCH PRICE
            # -------------------------------------------------

            if data_type != "match_price":

                return

            # -------------------------------------------------
            # CALLBACK CHỈ GỌI 1 LẦN
            # -------------------------------------------------

            if self.on_data:

                try:

                    self.on_data(
                        data_type,
                        data
                    )

                except Exception as e:

                    logger.exception(
                        f"Lỗi callback dữ liệu "
                        f"{data_type}: {e}"
                    )

        except Exception as e:

            logger.exception(
                f"Lỗi xử lý dữ liệu "
                f"{data_type}: {e}"
            )

    # =========================================================
    # 6. KẾT NỐI
    # =========================================================

    def connect(self):

        self.sio.connect(
            self.BASE_URL,
            socketio_path=self.SOCKET_PATH,
            transports=[
                "websocket"
            ],
            wait_timeout=10
        )

    # =========================================================
    # 7. CHẠY COLLECTOR
    # =========================================================

    def run(self):

        self.running = True
        self._stopped = False

        # -----------------------------------------------------
        # LOAD SYMBOL
        # -----------------------------------------------------

        if not self.symbols:
            self.load_symbols()


        if not self.symbols:

            logger.error(
                "Không có mã cổ phiếu nào "
                "sau khi lọc."
            )

            self.running = False

            return

        # -----------------------------------------------------
        # CONNECT / RECONNECT LOOP
        # -----------------------------------------------------

        while self.running:

            try:

                logger.info(
                    "Đang kết nối Vietcap "
                    "WebSocket..."
                )

                self.connect()

                if not self.connected:

                    raise ConnectionError(
                        "Socket.IO connect() "
                        "không thiết lập được kết nối."
                    )

                logger.info(
                    "✓ WebSocket đang hoạt động."
                )

                # -------------------------------------------------
                # THEO DÕI KẾT NỐI
                # -------------------------------------------------

                while (
                    self.running
                    and self.connected
                ):

                    time.sleep(1)

                # -------------------------------------------------
                # NGƯỜI DÙNG DỪNG
                # -------------------------------------------------

                if not self.running:

                    break

                # -------------------------------------------------
                # VIETCAP NGẮT
                # -------------------------------------------------

                logger.warning(
                    "WebSocket đã mất kết nối."
                )

            except KeyboardInterrupt:

                logger.info(
                    "Đang dừng collector..."
                )

                self.running = False

                break

            except Exception as e:

                logger.exception(
                    f"Lỗi kết nối Vietcap: {e}"
                )

            # -----------------------------------------------------
            # RECONNECT
            # -----------------------------------------------------

            if self.running:

                logger.warning(
                    "⚠ Mất kết nối Vietcap."
                )

                logger.info(
                    "Sẽ thử kết nối lại sau "
                    f"{self.RECONNECT_DELAY} giây..."
                )

                # -------------------------------------------------
                # Đóng socket cũ
                # -------------------------------------------------

                try:

                    if self.sio.connected:

                        self.sio.disconnect()

                except Exception as e:

                    logger.debug(
                        f"Lỗi đóng socket cũ: {e}"
                    )

                self.connected = False

                # -------------------------------------------------
                # Chờ reconnect
                # -------------------------------------------------

                for _ in range(
                    self.RECONNECT_DELAY
                ):

                    if not self.running:
                        break

                    time.sleep(1)

        # ---------------------------------------------------------
        # DỪNG
        # ---------------------------------------------------------

        self.stop()

    # =========================================================
    # 8. DỪNG
    # =========================================================

    def stop(self):

        with self._stop_lock:

            if self._stopped:

                return

            self._stopped = True

        self.running = False
        self.connected = False

        # -----------------------------------------------------
        # ĐÓNG SOCKET
        # -----------------------------------------------------

        try:

            if self.sio.connected:

                self.sio.disconnect()

        except Exception as e:

            logger.debug(
                f"Lỗi đóng Vietcap WebSocket: {e}"
            )

        # -----------------------------------------------------
        # IN CACHE REALTIME
        # -----------------------------------------------------

        try:

            logger.info(
                "Realtime cache: "
                f"{self.market_store.count_latest()} mã"
            )

        except Exception:

            pass

        logger.info(
            "Vietcap Collector đã dừng."
        )


# =========================================================
# MAIN
# =========================================================

if __name__ == "__main__":

    collector = VietcapCollector()

    try:

        collector.run()

    except KeyboardInterrupt:

        logger.info(
            "Người dùng yêu cầu dừng collector."
        )

        collector.stop()