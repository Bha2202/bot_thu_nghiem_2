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
# HELPER CHUẨN HÓA ĐƠN VỊ GIÁ (Tránh lỗi +97563.6% PnL)
# =========================================================

def _normalize_price(price: float) -> float:
    """
    Đảm bảo giá khớp luôn theo đơn vị nghìn đồng (VD: 20,900 VNĐ -> 20.9).
    Tránh trường hợp lệch đơn vị làm % Lãi/Lỗ tính ra con số khổng lồ.
    """
    if price is None or price <= 0:
        return 0.0
    if price > 2000:  # Giá nhận về theo VNĐ (VD: 20900)
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

        # Chuẩn hóa giá trước khi kiểm tra & lưu
        item["price"] = _normalize_price(item.get("price", 0.0))

        # Kiểm tra dữ liệu
        if not MarketValidator.validate(item):

            invalid_count += 1
            continue

        # Lưu dữ liệu realtime vào RAM
        market_store.save(
            symbol=item["symbol"],
            price=item["price"],
            volume=item["volume"],
            data_type="match_price",
            timestamp=item.get("timestamp")
        )

        valid_count += 1

    if valid_count > 0:

        # Báo cho FailoverManager rằng
        # Vietcap đang hoạt động bình thường.
        failover_manager.record_vietcap_success()

        print(
            f"[REALTIME] Đã lưu "
            f"{valid_count} bản ghi."
        )

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

        # Chờ 24 giờ nhưng vẫn có thể
        # dừng ngay khi bot shutdown.
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
        # CHỈ CHẠY DNSE KHI ĐANG FAILOVER
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
        # LẤY DỮ LIỆU DNSE
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

                # Chuẩn hóa giá DNSE
                data["price"] = _normalize_price(data.get("price", 0.0))

                # Kiểm tra dữ liệu DNSE
                if not MarketValidator.validate(
                    data
                ):
                    continue

                # Lưu vào cùng MarketStore
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
    # STOP EVENT CHO BACKGROUND THREAD
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

            # ---------------------------------------------
            # DỮ LIỆU REALTIME
            # ---------------------------------------------

            on_data=lambda data_type, data:
                handle_realtime_data(
                    data_type,
                    data,
                    market_store,
                    failover_manager
                ),

            # ---------------------------------------------
            # TRẠNG THÁI KẾT NỐI
            # ---------------------------------------------

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
        # 5. KHỞI ĐỘNG FAILOVER THREAD
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
        # 6. KHỞI ĐỘNG HISTORICAL UPDATE
        # TỰ ĐỘNG LẶP MỖI 24 GIỜ
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