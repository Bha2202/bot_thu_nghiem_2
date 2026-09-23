from stock_bot.data_pipeline.collectors.dnse_collector import DNSECollector
from stock_bot.data_pipeline.processing.market_validator import MarketValidator
from stock_bot.data_pipeline.storage.market_store import MarketStore


def main():
    print("==========================================")
    print("       TEST DNSE → VALIDATOR → STORE")
    print("==========================================")

    # 1. Tạo MarketStore
    market_store = MarketStore()

    try:
        # 2. Lấy dữ liệu từ DNSE
        collector = DNSECollector()

        data = collector.get_latest_trade("ACB")

        if not data:
            print("[TEST] ❌ Không nhận được dữ liệu DNSE.")
            return

        print("\n[1] DNSE DATA:")
        print(data)

        # 3. Kiểm tra dữ liệu
        is_valid = MarketValidator.validate(data)

        print("\n[2] VALIDATOR:")

        if not is_valid:
            print("❌ Dữ liệu không hợp lệ.")
            return

        print("✅ Dữ liệu hợp lệ.")

        # 4. Lưu vào MarketStore
        market_store.save(
            symbol=data["symbol"],
            price=data["price"],
            volume=data["volume"],
            data_type=data["data_type"],
            timestamp=data["timestamp"]
        )

        print("\n[3] MARKET STORE:")

        saved = market_store.get_latest("ACB")

        if saved:
            print("✅ Đã lưu ACB:")
            print(saved)
        else:
            print("❌ Không tìm thấy ACB trong MarketStore.")

    finally:
        market_store.close()


if __name__ == "__main__":
    main()