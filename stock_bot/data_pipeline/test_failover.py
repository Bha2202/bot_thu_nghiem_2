from stock_bot.data_pipeline.failover_manager import FailoverManager


def main():

    print("==========================================")
    print("          TEST FAILOVER MANAGER")
    print("==========================================")

    manager = FailoverManager(
        failure_threshold=3,
        recovery_threshold=2
    )

    # ========================================================
    # 1. BAN ĐẦU
    # ========================================================

    print("\n[TEST 1] Nguồn ban đầu")

    print(
        "Nguồn:",
        manager.get_current_source()
    )

    # ========================================================
    # 2. VIETCAP HOẠT ĐỘNG
    # ========================================================

    print("\n[TEST 2] Vietcap hoạt động")

    manager.record_vietcap_success()

    print(
        "Nguồn:",
        manager.get_current_source()
    )

    # ========================================================
    # 3. GIẢ LẬP VIETCAP LỖI 3 LẦN
    # ========================================================

    print("\n[TEST 3] Vietcap lỗi")

    for i in range(3):

        manager.record_vietcap_failure()

    print(
        "Nguồn sau khi Vietcap lỗi:",
        manager.get_current_source()
    )

    # ========================================================
    # 4. TEST DNSE
    # ========================================================

    print("\n[TEST 4] Lấy ACB từ DNSE")

    data = manager.get_dnse_data("ACB")

    if data:

        print("✅ DNSE hoạt động")

        print(data)

    else:

        print("❌ DNSE không trả dữ liệu")

    # ========================================================
    # 5. GIẢ LẬP VIETCAP QUAY LẠI
    # ========================================================

    print("\n[TEST 5] Vietcap hoạt động lại")

    manager.record_vietcap_success()

    print(
        "Nguồn:",
        manager.get_current_source()
    )

    manager.record_vietcap_success()

    print(
        "Nguồn:",
        manager.get_current_source()
    )

    # ========================================================
    # 6. STATUS
    # ========================================================

    print("\n[TEST 6] STATUS")

    print(manager.status())


if __name__ == "__main__":
    main()
print("\n[TEST 7] Vietcap OFFLINE → Failover")

manager = FailoverManager(
    failure_threshold=1,
    recovery_threshold=2
)

manager.handle_vietcap_connection(False)

print("Nguồn hiện tại:", manager.get_current_source())

print("\n[TEST 8] Vietcap ONLINE → Recovery")

manager.handle_vietcap_connection(True)
manager.handle_vietcap_connection(True)

print("Nguồn hiện tại:", manager.get_current_source())