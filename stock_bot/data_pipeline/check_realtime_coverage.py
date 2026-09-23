import time
import threading

from stock_bot.data_pipeline.collectors.vietcap_collector import VietcapCollector
from stock_bot.data_pipeline.processing.vietcap_parser import VietcapParser
from stock_bot.data_pipeline.processing.market_validator import MarketValidator
from stock_bot.data_pipeline.storage.market_store import MarketStore


# =========================================================
# CẤU HÌNH
# =========================================================

TEST_SECONDS = 60


# =========================================================
# THỐNG KÊ
# =========================================================

match_price_symbols = set()
bid_ask_symbols = set()

match_price_packets = 0
bid_ask_packets = 0

parser_match_ok = 0
parser_match_empty = 0

valid_match = 0
invalid_match = 0


# =========================================================
# CALLBACK
# =========================================================

def handle_realtime_data(
    data_type,
    data,
    market_store
):

    global match_price_packets
    global bid_ask_packets
    global parser_match_ok
    global parser_match_empty
    global valid_match
    global invalid_match

    # =====================================================
    # MATCH PRICE
    # =====================================================

    if data_type == "match_price":

        match_price_packets += 1

        try:

            parsed_data = (
                VietcapParser.parse_match_price(data)
            )

        except Exception as e:

            print(
                f"\n[PARSER ERROR] match_price: {e}"
            )

            return

        if not parsed_data:

            parser_match_empty += 1

            return

        parser_match_ok += 1

        for item in parsed_data:

            symbol = item.get("symbol")

            if not symbol:
                continue

            symbol = symbol.upper()

            # Kiểm tra validator

            try:

                valid = MarketValidator.validate(
                    item
                )

            except Exception:

                valid = False

            if not valid:

                invalid_match += 1

                continue

            valid_match += 1

            match_price_symbols.add(
                symbol
            )

            # Lưu realtime

            market_store.save(
                symbol=symbol,
                price=item.get("price"),
                volume=item.get("volume"),
                data_type="match_price",
                timestamp=item.get("timestamp")
            )

    # =====================================================
    # BID ASK
    # =====================================================

    elif data_type == "bid_ask":

        bid_ask_packets += 1

        # -------------------------------------------------
        # Lấy ticker trực tiếp từ protobuf
        # -------------------------------------------------

        try:

            fields = (
                collector._decode_protobuf(data)
            )

        except Exception:

            return

        ticker = None

        for item in fields:

            if item["field"] == 3:

                ticker = item["value"]

                break

        if not ticker:
            return

        ticker = str(
            ticker
        ).strip().upper()

        if not ticker:
            return

        bid_ask_symbols.add(
            ticker
        )


# =========================================================
# MAIN
# =========================================================

def main():

    global collector

    print("=" * 70)
    print("       KIỂM TRA ĐỘ PHỦ REALTIME VIETCAP")
    print("=" * 70)

    # =====================================================
    # STORE
    # =====================================================

    market_store = MarketStore()

    # =====================================================
    # COLLECTOR
    # =====================================================

    collector = VietcapCollector(
        on_data=lambda data_type, data:
            handle_realtime_data(
                data_type,
                data,
                market_store
            ),
        market_store=market_store
    )

    try:

        # =================================================
        # 1. LOAD SYMBOLS
        # =================================================

        print(
            "\n[1] Đang tải danh sách mã..."
        )

        symbols = collector.load_symbols()

        project_symbols = set(
            symbol.upper()
            for symbol in symbols
        )

        print(
            f"\nTổng mã dự án: "
            f"{len(project_symbols)}"
        )

        if not project_symbols:

            print(
                "[ERROR] Không có mã."
            )

            return

        # =================================================
        # 2. START COLLECTOR
        # =================================================

        print(
            f"\n[2] Bắt đầu kiểm tra "
            f"{TEST_SECONDS} giây..."
        )

        thread = threading.Thread(
            target=collector.run,
            daemon=True
        )

        thread.start()

        # =================================================
        # 3. ĐẾM THỜI GIAN
        # =================================================

        start = time.time()

        while (
            time.time() - start
            < TEST_SECONDS
        ):

            elapsed = int(
                time.time() - start
            )

            print(
                f"\rĐã chạy: {elapsed:3d}s"
                f" | match_price: "
                f"{len(match_price_symbols):4d}"
                f" | bid_ask: "
                f"{len(bid_ask_symbols):4d}",
                end="",
                flush=True
            )

            time.sleep(1)

        print(
            "\n\n[3] Hết thời gian kiểm tra."
        )

        # =================================================
        # 4. STOP
        # =================================================

        collector.stop()

        time.sleep(1)

        # =================================================
        # 5. CHỈ GIỮ MÃ TRONG 1523 MÃ
        # =================================================

        match_price_symbols.intersection_update(
            project_symbols
        )

        bid_ask_symbols.intersection_update(
            project_symbols
        )

        # =================================================
        # 6. HỢP NHẤT
        # =================================================

        all_realtime_symbols = (
            match_price_symbols
            | bid_ask_symbols
        )

        missing_symbols = (
            project_symbols
            - all_realtime_symbols
        )

        # =================================================
        # 7. KẾT QUẢ
        # =================================================

        total = len(
            project_symbols
        )

        match_count = len(
            match_price_symbols
        )

        bid_count = len(
            bid_ask_symbols
        )

        realtime_count = len(
            all_realtime_symbols
        )

        missing_count = len(
            missing_symbols
        )

        coverage = (
            realtime_count / total * 100
            if total > 0
            else 0
        )

        print("\n")
        print("=" * 70)
        print("THỐNG KÊ REALTIME")
        print("=" * 70)

        print(
            f"Match price packets nhận : "
            f"{match_price_packets}"
        )

        print(
            f"Bid/ask packets nhận     : "
            f"{bid_ask_packets}"
        )

        print(
            f"Match price parse OK     : "
            f"{parser_match_ok}"
        )

        print(
            f"Match price parse rỗng   : "
            f"{parser_match_empty}"
        )

        print(
            f"Match price hợp lệ       : "
            f"{valid_match}"
        )

        print(
            f"Match price không hợp lệ : "
            f"{invalid_match}"
        )

        print("\n")
        print("=" * 70)
        print("KẾT QUẢ ĐỘ PHỦ")
        print("=" * 70)

        print(
            f"Tổng mã dự án       : "
            f"{total}"
        )

        print(
            f"Có match_price      : "
            f"{match_count}"
        )

        print(
            f"Có bid_ask          : "
            f"{bid_count}"
        )

        print(
            f"Có ít nhất 1 loại   : "
            f"{realtime_count}"
        )

        print(
            f"Chưa nhận loại nào  : "
            f"{missing_count}"
        )

        print(
            f"Độ phủ realtime     : "
            f"{coverage:.2f}%"
        )

        # =================================================
        # 8. DANH SÁCH
        # =================================================

        print("\n")
        print(
            "Một số mã có realtime:"
        )

        print(
            ", ".join(
                sorted(all_realtime_symbols)[:100]
            )
        )

        print("\n")
        print(
            "Một số mã chưa nhận:"
        )

        print(
            ", ".join(
                sorted(missing_symbols)[:100]
            )
        )

    finally:

        collector.stop()

        market_store.close()

        print(
            "\n\n[END] Kiểm tra hoàn tất."
        )


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":

    main()