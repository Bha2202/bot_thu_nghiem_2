import threading
import time

from stock_bot.data_pipeline.collectors.vietcap_collector import (
    VietcapCollector
)

from stock_bot.data_pipeline.processing.vietcap_parser import (
    VietcapParser
)

from stock_bot.data_pipeline.processing.market_validator import (
    MarketValidator
)

from stock_bot.data_pipeline.storage.market_store import (
    MarketStore
)

from stock_bot.data_pipeline.data_service import (
    DataService
)

from stock_bot.data_pipeline.update_history import (
    HistoricalUpdater
)

from stock_bot.data_pipeline.snapshot_loader import (
    SnapshotLoader
)

from stock_bot.data_pipeline.failover_manager import (
    FailoverManager
)


# =========================================================
# HELPER CHUẨN HÓA ĐƠN VỊ GIÁ
# =========================================================

def _normalize_price(price: float) -> float:
    """
    Đảm bảo giá khớp luôn theo đơn vị nghìn đồng.

    Ví dụ:
        20,900 VNĐ -> 20.9
        18,500 VNĐ -> 18.5

    Tránh lỗi lệch đơn vị làm PnL sai.
    """

    if price is None or price <= 0:
        return 0.0

    if price > 2000:
        return price / 1000.0

    return price


# =========================================================
# XỬ LÝ DỮ LIỆU REALTIME
# =========================================================

def handle_realtime_data(
    data_type,
    data,
    market_store,
    failover_manager
):

    # Chỉ xử lý match_price
    if data_type != "match_price":
        return

    parsed_data = (
        VietcapParser.parse_match_price(
            data
        )
    )

    if not parsed_data:

        print(
            "[REALTIME] Không có dữ liệu "
            "match_price hợp lệ."
        )

        return

    valid_count = 0
    invalid_count = 0

    for item in parsed_data:

        # -------------------------------------------------
        # Chuẩn hóa giá
        # -------------------------------------------------

        item["price"] = _normalize_price(
            item.get("price", 0.0)
        )

        # -------------------------------------------------
        # Kiểm tra dữ liệu
        # -------------------------------------------------

        if not MarketValidator.validate(item):

            invalid_count += 1

            continue

        # -------------------------------------------------
        # Lưu realtime vào MarketStore
        # -------------------------------------------------

        market_store.save(
            symbol=item["symbol"],
            price=item["price"],
            volume=item["volume"],
            data_type="match_price",
            timestamp=item.get("timestamp")
        )

        valid_count += 1

    # -----------------------------------------------------
    # Vietcap hoạt động bình thường
    # -----------------------------------------------------

    if valid_count > 0:

        failover_manager.record_vietcap_success()

        print(
            f"[REALTIME] Đã lưu "
            f"{valid_count} bản ghi."
        )

    # -----------------------------------------------------
    # Dữ liệu không hợp lệ
    # -----------------------------------------------------

    if invalid_count > 0:

        print(
            f"[REALTIME] Bỏ qua "
            f"{invalid_count} bản ghi không hợp lệ."
        )


# =========================================================
# XỬ LÝ TRẠNG THÁI KẾT NỐI VIETCAP
# =========================================================

def handle_vietcap_connection(
    connected,
    failover_manager
):

    failover_manager.handle_vietcap_connection(
        connected
    )


# =========================================================
# CẬP NHẬT DỮ LIỆU LỊCH SỬ
# TỰ ĐỘNG CHẠY LẠI MỖI 24 GIỜ
# =========================================================

def run_historical_update(
    stop_event
):

    UPDATE_INTERVAL = 24 * 60 * 60

    print(
        "[HISTORY] Automatic historical update "
        "đã khởi động."
    )

    while not stop_event.is_set():

        updater = HistoricalUpdater()

        try:

            print(
                "\n"
                "=========================================="
            )

            print(
                "       AUTOMATIC HISTORICAL UPDATE"
            )

            print(
                "=========================================="
            )

            updater.run()

            print(
                "[HISTORY] "
                "Cập nhật dữ liệu lịch sử hoàn tất."
            )

        except Exception as e:

            print(
                f"[HISTORY ERROR] {e}"
            )

        finally:

            try:

                updater.close()

            except Exception as e:

                print(
                    f"[HISTORY] "
                    f"Lỗi đóng HistoricalUpdater: {e}"
                )

        if stop_event.is_set():
            break

        print(
            "[HISTORY] "
            "Lần cập nhật tiếp theo sau 24 giờ."
        )

        stop_event.wait(
            UPDATE_INTERVAL
        )

    print(
        "[HISTORY] "
        "Automatic historical update đã dừng."
    )


# =========================================================
# DNSE FAILOVER
# =========================================================

def run_dnse_failover(
    failover_manager,
    market_store,
    symbols,
    stop_event
):

    print(
        "[FAILOVER THREAD] "
        "Đã khởi động."
    )

    while not stop_event.is_set():

        # -------------------------------------------------
        # Chỉ chạy DNSE khi đang failover
        # -------------------------------------------------

        if (
            failover_manager.get_current_source()
            != "dnse"
        ):

            stop_event.wait(2)

            continue

        print(
            "[FAILOVER THREAD] "
            "⚠️ Đang sử dụng DNSE."
        )

        # -------------------------------------------------
        # Lấy dữ liệu DNSE
        # -------------------------------------------------

        for symbol in symbols:

            if stop_event.is_set():
                break

            # Vietcap đã phục hồi
            if (
                failover_manager.get_current_source()
                != "dnse"
            ):

                break

            try:

                data = (
                    failover_manager.get_dnse_data(
                        symbol
                    )
                )

                if not data:
                    continue

                # -------------------------------------------------
                # Chuẩn hóa giá DNSE
                # -------------------------------------------------

                data["price"] = _normalize_price(
                    data.get("price", 0.0)
                )

                # -------------------------------------------------
                # Kiểm tra dữ liệu
                # -------------------------------------------------

                if not MarketValidator.validate(data):
                    continue

                # -------------------------------------------------
                # Lưu DNSE vào cùng MarketStore
                # -------------------------------------------------

                market_store.save(
                    symbol=data["symbol"],
                    price=data["price"],
                    volume=data["volume"],
                    data_type="dnse_latest_trade",
                    timestamp=data.get("timestamp")
                )

            except Exception as e:

                print(
                    f"[FAILOVER THREAD] "
                    f"Lỗi {symbol}: {e}"
                )

        # Không gọi DNSE liên tục
        stop_event.wait(10)

    print(
        "[FAILOVER THREAD] "
        "Đã dừng."
    )


# =========================================================
# =========================================================
# REALTIME PIPELINE DÙNG CHUNG CHO TELEGRAM BOT
# =========================================================
# =========================================================

_realtime_market_store = None
_realtime_collector = None
_realtime_failover_manager = None
_realtime_stop_event = None
_realtime_threads = []


# =========================================================
# KHỞI ĐỘNG REALTIME PIPELINE
# =========================================================

def start_realtime_pipeline():

    global _realtime_market_store
    global _realtime_collector
    global _realtime_failover_manager
    global _realtime_stop_event
    global _realtime_threads

    # -----------------------------------------------------
    # Nếu đã chạy thì không khởi động lần 2
    # -----------------------------------------------------

    if _realtime_collector is not None:

        print(
            "[REALTIME] Pipeline đã được khởi động."
        )

        return _realtime_market_store

    print(
        "\n=========================================="
    )

    print(
        "   KHỞI ĐỘNG REALTIME PIPELINE"
    )

    print(
        "=========================================="
    )

    # =====================================================
    # 1. MARKET STORE
    # =====================================================

    market_store = MarketStore()

    _realtime_market_store = market_store

    # =====================================================
    # 2. FAILOVER MANAGER
    # =====================================================

    failover_manager = FailoverManager(
        failure_threshold=3,
        recovery_threshold=2
    )

    _realtime_failover_manager = failover_manager

    # =====================================================
    # 3. STOP EVENT
    # =====================================================

    stop_event = threading.Event()

    _realtime_stop_event = stop_event

    # =====================================================
    # 4. NẠP SNAPSHOT
    # =====================================================

    try:

        snapshot_loader = SnapshotLoader(
            market_store=market_store
        )

        saved_count = snapshot_loader.load()

        print(
            f"[REALTIME] Snapshot đã nạp: "
            f"{saved_count} mã"
        )

    except Exception as e:

        print(
            f"[REALTIME] Lỗi nạp snapshot: {e}"
        )

    # =====================================================
    # 5. VIETCAP COLLECTOR
    # =====================================================

    print(
        "[REALTIME] Khởi tạo Vietcap Collector..."
    )

    collector = VietcapCollector(

        # -------------------------------------------------
        # Dữ liệu realtime
        # -------------------------------------------------

        on_data=lambda data_type, data:
            handle_realtime_data(
                data_type,
                data,
                market_store,
                failover_manager
            ),

        # -------------------------------------------------
        # Trạng thái kết nối
        # -------------------------------------------------

        on_connection_change=lambda connected:
            handle_vietcap_connection(
                connected,
                failover_manager
            ),

        # -------------------------------------------------
        # Dùng chung MarketStore
        # -------------------------------------------------

        market_store=market_store
    )

    # =====================================================
    # 6. LOAD SYMBOL
    # =====================================================

    collector.load_symbols()

    if not collector.symbols:

        raise RuntimeError(
            "Không có mã cổ phiếu để chạy realtime."
        )

    print(
        f"[REALTIME] Đã tải "
        f"{len(collector.symbols)} mã."
    )

    _realtime_collector = collector

    # =====================================================
    # 7. DNSE FAILOVER THREAD
    # =====================================================

    failover_thread = threading.Thread(

        target=run_dnse_failover,

        args=(
            failover_manager,
            market_store,
            collector.symbols,
            stop_event
        ),

        daemon=True
    )

    failover_thread.start()

    _realtime_threads.append(
        failover_thread
    )

    print(
        "[REALTIME] "
        "Failover thread đã chạy background."
    )

    # =====================================================
    # 8. VIETCAP WEBSOCKET THREAD
    # =====================================================

    def run_vietcap():

        try:

            print(
                "[REALTIME] Đang khởi động "
                "Vietcap WebSocket..."
            )

            collector.run()

        except Exception as e:

            print(
                f"[REALTIME ERROR] "
                f"Vietcap WebSocket: {e}"
            )

    vietcap_thread = threading.Thread(

        target=run_vietcap,

        daemon=True
    )

    vietcap_thread.start()

    _realtime_threads.append(
        vietcap_thread
    )

    print(
        "[REALTIME] "
        "✅ Vietcap realtime đã chạy background."
    )

    return market_store


# =========================================================
# LẤY MARKET STORE DÙNG CHUNG
# =========================================================

def get_realtime_market_store():

    return _realtime_market_store


# =========================================================
# DỪNG REALTIME PIPELINE
# =========================================================

def stop_realtime_pipeline():

    global _realtime_market_store
    global _realtime_collector
    global _realtime_failover_manager
    global _realtime_stop_event
    global _realtime_threads

    print(
        "[REALTIME] "
        "Đang dừng realtime pipeline..."
    )

    # -----------------------------------------------------
    # Dừng thread
    # -----------------------------------------------------

    if _realtime_stop_event is not None:

        _realtime_stop_event.set()

    # -----------------------------------------------------
    # Dừng Vietcap
    # -----------------------------------------------------

    if _realtime_collector is not None:

        try:

            _realtime_collector.stop()

        except Exception as e:

            print(
                f"[REALTIME] "
                f"Lỗi đóng collector: {e}"
            )

    # -----------------------------------------------------
    # Chờ các thread
    # -----------------------------------------------------

    for thread in _realtime_threads:

        if thread.is_alive():

            thread.join(
                timeout=2
            )

    # -----------------------------------------------------
    # Đóng MarketStore
    # -----------------------------------------------------

    if _realtime_market_store is not None:

        try:

            _realtime_market_store.close()

        except Exception as e:

            print(
                f"[REALTIME] "
                f"Lỗi đóng MarketStore: {e}"
            )

    # -----------------------------------------------------
    # Reset trạng thái
    # -----------------------------------------------------

    _realtime_collector = None
    _realtime_market_store = None
    _realtime_failover_manager = None
    _realtime_stop_event = None
    _realtime_threads = []

    print(
        "[REALTIME] "
        "Đã dừng."
    )


# =========================================================
# MAIN
# =========================================================

def main():

    print(
        "=========================================="
    )

    print(
        "      DATA PIPELINE - STOCK BOT"
    )

    print(
        "=========================================="
    )

    # =====================================================
    # MARKET STORE
    # =====================================================

    market_store = MarketStore()

    # =====================================================
    # DATA SERVICE
    # =====================================================

    data_service = DataService(
        market_store=market_store
    )

    # =====================================================
    # FAILOVER MANAGER
    # =====================================================

    failover_manager = FailoverManager(
        failure_threshold=3,
        recovery_threshold=2
    )

    # =====================================================
    # STOP EVENT
    # =====================================================

    stop_event = threading.Event()

    collector = None
    failover_thread = None
    history_thread = None

    try:

        # =================================================
        # 1. NẠP SNAPSHOT BAN ĐẦU
        # =================================================

        print(
            "\n[MAIN] Đang nạp snapshot ban đầu..."
        )

        snapshot_loader = SnapshotLoader(
            market_store=market_store
        )

        saved_count = snapshot_loader.load()

        print(
            f"[MAIN] Snapshot đã nạp: "
            f"{saved_count} mã"
        )

        realtime_count = (
            market_store.count_latest()
        )

        print(
            f"[MAIN] Realtime cache hiện tại: "
            f"{realtime_count} mã"
        )

        # =================================================
        # 2. KIỂM TRA SNAPSHOT
        # =================================================

        if saved_count != 1523:

            print(
                "[MAIN WARNING] "
                "Snapshot chưa đủ 1.523 mã."
            )

            print(
                "[MAIN WARNING] "
                "Kiểm tra lại dữ liệu Vietcap."
            )

        else:

            print(
                "[MAIN] "
                "✅ Snapshot 1.523 mã đã sẵn sàng."
            )

        # =================================================
        # 3. KHỞI TẠO VIETCAP COLLECTOR
        # =================================================

        print(
            "\n[MAIN] Khởi tạo "
            "Vietcap Collector..."
        )

        collector = VietcapCollector(

            on_data=lambda data_type, data:
                handle_realtime_data(
                    data_type,
                    data,
                    market_store,
                    failover_manager
                ),

            on_connection_change=lambda connected:
                handle_vietcap_connection(
                    connected,
                    failover_manager
                ),

            market_store=market_store
        )

        # =================================================
        # 4. LOAD SYMBOL
        # =================================================

        print(
            "\n[MAIN] Đang tải danh sách mã..."
        )

        collector.load_symbols()

        if not collector.symbols:

            raise RuntimeError(
                "Không có mã cổ phiếu để chạy pipeline."
            )

        print(
            f"[MAIN] Đã tải "
            f"{len(collector.symbols)} mã."
        )

        # =================================================
        # 5. DNSE FAILOVER THREAD
        # =================================================

        failover_thread = threading.Thread(

            target=run_dnse_failover,

            args=(
                failover_manager,
                market_store,
                collector.symbols,
                stop_event
            ),

            daemon=True
        )

        failover_thread.start()

        print(
            "[MAIN] "
            "Failover thread đang chạy background..."
        )

        # =================================================
        # 6. HISTORICAL UPDATE
        # =================================================

        history_thread = threading.Thread(

            target=run_historical_update,

            args=(
                stop_event,
            ),

            daemon=True
        )

        history_thread.start()

        print(
            "[MAIN] "
            "Historical update đang chạy background "
            "và sẽ tự cập nhật mỗi 24 giờ..."
        )

        # =================================================
        # 7. VIETCAP REALTIME WEBSOCKET
        # =================================================

        print(
            "\n[MAIN] Khởi động "
            "Vietcap WebSocket..."
        )

        collector.run()

    except KeyboardInterrupt:

        print(
            "\n[MAIN] Người dùng dừng hệ thống."
        )

    except Exception as e:

        print(
            f"\n[MAIN ERROR] {e}"
        )

    finally:

        print(
            "\n[MAIN] Đang shutdown Data Pipeline..."
        )

        # =================================================
        # DỪNG BACKGROUND THREADS
        # =================================================

        stop_event.set()

        # -------------------------------------------------
        # DỪNG FAILOVER THREAD
        # -------------------------------------------------

        if (
            failover_thread is not None
            and failover_thread.is_alive()
        ):

            failover_thread.join(
                timeout=2
            )

        # -------------------------------------------------
        # DỪNG HISTORICAL THREAD
        # -------------------------------------------------

        if (
            history_thread is not None
            and history_thread.is_alive()
        ):

            history_thread.join(
                timeout=2
            )

        # =================================================
        # ĐÓNG VIETCAP COLLECTOR
        # =================================================

        if collector is not None:

            try:

                collector.stop()

            except Exception as e:

                print(
                    f"[MAIN] "
                    f"Lỗi đóng collector: {e}"
                )

        # =================================================
        # ĐÓNG DATA SERVICE
        # =================================================

        try:

            data_service.close()

        except Exception as e:

            print(
                f"[MAIN] "
                f"Lỗi đóng DataService: {e}"
            )

        # =================================================
        # ĐÓNG MARKET STORE
        # =================================================

        try:

            market_store.close()

        except Exception as e:

            print(
                f"[MAIN] "
                f"Lỗi đóng MarketStore: {e}"
            )

        print(
            "[MAIN] Data Pipeline đã đóng."
        )


# =========================================================
# ENTRY POINT
# =========================================================

if __name__ == "__main__":

    main()