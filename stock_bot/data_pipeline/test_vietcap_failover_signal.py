from stock_bot.data_pipeline.collectors.vietcap_collector import VietcapCollector


def connection_changed(status):
    if status:
        print("[TEST] 🟢 VIETCAP ONLINE")
    else:
        print("[TEST] 🔴 VIETCAP OFFLINE")


def main():

    print("==========================================")
    print("      TEST VIETCAP CONNECTION SIGNAL")
    print("==========================================")

    collector = VietcapCollector(
        on_connection_change=connection_changed
    )

    print("\n[TEST] Giả lập Vietcap ONLINE...")
    connection_changed(True)

    print("\n[TEST] Giả lập Vietcap OFFLINE...")
    connection_changed(False)

    print("\n[TEST] Hoàn thành.")


if __name__ == "__main__":
    main()