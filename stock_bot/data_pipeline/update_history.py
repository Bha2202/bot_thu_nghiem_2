import csv
import time
import sys


# =============================================================
# UTF-8 CHO WINDOWS
# =============================================================


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")




from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo


from stock_bot.data_pipeline.collectors.historical_collector import (
    HistoricalCollector
)


from stock_bot.data_pipeline.storage.historical_store import (
    HistoricalStore
)




class HistoricalUpdater:


    # =========================================================
    # 48 MÃ KHÔNG HOẠT ĐỘNG
    # =========================================================


    INACTIVE_SYMBOLS = {
        "ART", "BCV", "BHG", "BT6", "CMK", "CMP",
        "CNA", "CPH", "DAG", "EGL", "FBC", "GTT",
        "HHN", "HLA", "HLT", "HNR", "HSA", "ITA",
        "KTT", "MBN", "MES", "MHL", "MTB", "NDF",
        "NSS", "PID", "PPI", "PQN", "SD8", "SJF",
        "SVH", "TBW", "TGG", "TKA", "TNA", "TQW",
        "TTB", "TTZ", "UMC", "UTT", "VCE", "VDB",
        "VLP", "VMA", "VPW", "VTM", "VXP", "X77"
    }


    # Múi giờ Việt Nam
    TIMEZONE = ZoneInfo("Asia/Ho_Chi_Minh")


    def __init__(
        self,
        db_path="data/market_data.db",
        symbols_path="data/symbols.csv",
        start_date="2025-01-01",
        request_delay=1.1,
        max_retry=3
    ):


        self.db_path = db_path
        self.symbols_path = symbols_path
        self.start_date = start_date
        self.request_delay = request_delay
        self.max_retry = max_retry


        self.collector = HistoricalCollector(
            source="KBS"
        )


        self.store = HistoricalStore(
            db_path=self.db_path
        )


        self.failed_symbols = []


    # =========================================================
    # THỜI GIAN VIỆT NAM
    # =========================================================


    @classmethod
    def now_vietnam(cls):


        return datetime.now(
            cls.TIMEZONE
        )


    # =========================================================
    # XÁC ĐỊNH PHIÊN CUỐI CÙNG
    # =========================================================


    @classmethod
    def get_last_completed_trading_date(cls):


        now = cls.now_vietnam()


        # Thứ 7
        if now.weekday() == 5:
            return (
                now.date()
                - timedelta(days=1)
            )


        # Chủ nhật
        if now.weekday() == 6:
            return (
                now.date()
                - timedelta(days=2)
            )


        # Trước 15:15
        if (
            now.hour < 15
            or (
                now.hour == 15
                and now.minute < 15
            )
        ):


            previous_day = (
                now.date()
                - timedelta(days=1)
            )


        else:


            # Sau 15:15 có thể lấy dữ liệu hôm nay
            previous_day = now.date()


        # Nếu rơi vào cuối tuần thì lùi lại
        while previous_day.weekday() >= 5:
            previous_day -= timedelta(days=1)


        return previous_day


    # =========================================================
    # KIỂM TRA CÓ ĐƯỢC CẬP NHẬT KHÔNG
    # =========================================================


    @classmethod
    def can_update_history(cls):


        now = cls.now_vietnam()


        # Thứ 7 / Chủ nhật
        if now.weekday() >= 5:
            return False


        # Trước 15:00
        if now.hour < 15:
            return False


        # 15:00 - 15:14
        if now.hour == 15 and now.minute < 15:
            return False


        return True


    # =========================================================
    # ĐỌC DANH SÁCH MÃ
    # =========================================================


    def load_symbols(self):


        symbols = []


        path = Path(
            self.symbols_path
        )


        if not path.exists():


            print(
                f"[HISTORY] Không tìm thấy: {path}",
                flush=True
            )


            return symbols


        with open(
            path,
            "r",
            encoding="utf-8-sig",
            newline=""
        ) as file:


            reader = csv.DictReader(file)


            for row in reader:


                symbol = row.get("symbol")


                if not symbol:
                    continue


                symbol = symbol.strip().upper()


                if not symbol:
                    continue


                # Bỏ qua mã inactive
                if symbol in self.INACTIVE_SYMBOLS:
                    continue


                symbols.append(symbol)


        symbols = sorted(
            set(symbols)
        )


        print(
            f"[HISTORY] Mã hoạt động cần kiểm tra: "
            f"{len(symbols)}",
            flush=True
        )


        print(
            f"[HISTORY] Bỏ qua inactive: "
            f"{len(self.INACTIVE_SYMBOLS)}",
            flush=True
        )


        return symbols


    # =========================================================
    # KIỂM TRA 1 MÃ CÓ THIẾU DỮ LIỆU KHÔNG
    # =========================================================


    def needs_update(
        self,
        symbol,
        target_date
    ):


        last_date = self.store.get_last_date(
            symbol
        )


        # Chưa có lịch sử
        if not last_date:
            return True


        return str(last_date) < target_date.isoformat()


    # =========================================================
    # CẬP NHẬT 1 MÃ
    # =========================================================


    def update_symbol(
        self,
        symbol,
        target_date
    ):


        symbol = symbol.upper()


        try:


            last_date = self.store.get_last_date(
                symbol
            )


            # -------------------------------------------------
            # Chưa có dữ liệu
            # -------------------------------------------------


            if not last_date:


                start = self.start_date


            # -------------------------------------------------
            # Đã có dữ liệu
            # Chỉ lấy phần còn thiếu
            # -------------------------------------------------


            else:


                last_date_obj = datetime.strptime(
                    str(last_date),
                    "%Y-%m-%d"
                ).date()


                start = (
                    last_date_obj
                    + timedelta(days=1)
                ).isoformat()


            end = target_date.isoformat()


            # -------------------------------------------------
            # Đã cập nhật đủ
            # -------------------------------------------------


            if start > end:


                print(
                    f"[SKIP] {symbol}: "
                    f"đã có dữ liệu đến {last_date}",
                    flush=True
                )


                return "skipped"


            print(
                f"[HISTORY] {symbol}: "
                f"{start} → {end}",
                flush=True
            )


            # -------------------------------------------------
            # GỌI KBS
            # -------------------------------------------------


            df = None


            for retry in range(
                1,
                self.max_retry + 1
            ):


                try:


                    print(
                        f"[API] {symbol}: "
                        f"Đang lấy dữ liệu "
                        f"(lần {retry}/{self.max_retry})...",
                        flush=True
                    )


                    df = self.collector.get_history(
                        symbol=symbol,
                        start=start,
                        end=end
                    )


                    print(
                        f"[API] {symbol}: "
                        f"Đã nhận dữ liệu.",
                        flush=True
                    )


                    break


                except Exception as e:


                    print(
                        f"[RETRY] {symbol}: "
                        f"lần {retry}/{self.max_retry}",
                        flush=True
                    )


                    print(
                        f"[ERROR] {type(e).__name__}: {e}",
                        flush=True
                    )


                    if retry >= self.max_retry:
                        raise


                    print(
                        "[RATE LIMIT] "
                        "Chờ 60 giây...",
                        flush=True
                    )


                    time.sleep(60)


            # -------------------------------------------------
            # KHÔNG CÓ DỮ LIỆU MỚI
            # -------------------------------------------------


            if df is None or df.empty:


                print(
                    f"[NO NEW DATA] {symbol}",
                    flush=True
                )


                return "no_data"


            # -------------------------------------------------
            # LƯU SQLITE
            # -------------------------------------------------


            print(
                f"[DB] {symbol}: "
                f"Đang lưu {len(df)} dòng...",
                flush=True
            )


            self.store.save(df)


            print(
                f"[UPDATED] {symbol}: "
                f"thêm {len(df)} dòng.",
                flush=True
            )


            return "updated"


        except Exception as e:


            print(
                f"[FAILED] {symbol}: {e}",
                flush=True
            )


            self.failed_symbols.append(
                symbol
            )


            return "failed"


    # =========================================================
    # CHẠY CẬP NHẬT
    # =========================================================


    def run(self):


        print(
            flush=True
        )


        print(
            "=" * 70,
            flush=True
        )


        print(
            "       AUTOMATIC HISTORICAL UPDATE",
            flush=True
        )


        print(
            "=" * 70,
            flush=True
        )


        now = self.now_vietnam()


        print(
            f"[HISTORY] Vietnam time: "
            f"{now.strftime('%Y-%m-%d %H:%M:%S')}",
            flush=True
        )


        # -----------------------------------------------------
        # KHÔNG CẬP NHẬT TRONG GIỜ GIAO DỊCH
        # -----------------------------------------------------


        if not self.can_update_history():


            print(
                "[HISTORY] Chưa đến thời điểm "
                "cập nhật lịch sử.",
                flush=True
            )


            print(
                "[HISTORY] Realtime vẫn tiếp tục "
                "hoạt động bình thường.",
                flush=True
            )


            return


        # -----------------------------------------------------
        # XÁC ĐỊNH PHIÊN CUỐI CÙNG
        # -----------------------------------------------------


        target_date = (
            self.get_last_completed_trading_date()
        )


        print(
            f"[HISTORY] Phiên cuối cần kiểm tra: "
            f"{target_date}",
            flush=True
        )


        # -----------------------------------------------------
        # ĐỌC MÃ
        # -----------------------------------------------------


        symbols = self.load_symbols()


        if not symbols:


            print(
                "[HISTORY] Không có mã hoạt động.",
                flush=True
            )


            return


        total = len(symbols)


        updated_count = 0
        skipped_count = 0
        no_data_count = 0
        failed_count = 0


        print(
            f"[HISTORY] Bắt đầu kiểm tra "
            f"{total} mã...",
            flush=True
        )


        # -----------------------------------------------------
        # DUYỆT DANH SÁCH
        # -----------------------------------------------------


        for index, symbol in enumerate(
            symbols,
            start=1
        ):


            print(
                f"\n[{index}/{total}] {symbol}",
                flush=True
            )


            # -------------------------------------------------
            # KIỂM TRA DB TRƯỚC
            # -------------------------------------------------


            if not self.needs_update(
                symbol,
                target_date
            ):


                print(
                    f"[SKIP] {symbol}: "
                    f"đã đủ dữ liệu.",
                    flush=True
                )


                skipped_count += 1


                continue


            # -------------------------------------------------
            # CHỈ MÃ THIẾU MỚI GỌI API
            # -------------------------------------------------


            result = self.update_symbol(
                symbol,
                target_date
            )


            if result == "updated":


                updated_count += 1


            elif result == "skipped":


                skipped_count += 1


            elif result == "no_data":


                no_data_count += 1


            elif result == "failed":


                failed_count += 1


            # -------------------------------------------------
            # NGHỈ GIỮA CÁC REQUEST
            # -------------------------------------------------


            if result == "updated":


                print(
                    f"[WAIT] Nghỉ "
                    f"{self.request_delay} giây "
                    f"trước mã tiếp theo...",
                    flush=True
                )


                time.sleep(
                    self.request_delay
                )


        # =====================================================
        # LƯU DANH SÁCH LỖI
        # =====================================================


        if self.failed_symbols:


            failed_path = (
                Path("data")
                / "history_failed_symbols.csv"
            )


            with open(
                failed_path,
                "w",
                encoding="utf-8",
                newline=""
            ) as file:


                writer = csv.writer(file)


                writer.writerow(
                    ["symbol"]
                )


                for symbol in self.failed_symbols:


                    writer.writerow(
                        [symbol]
                    )


            print(
                f"\n[HISTORY] "
                f"Có {len(self.failed_symbols)} mã lỗi.",
                flush=True
            )


        # =====================================================
        # TỔNG KẾT
        # =====================================================


        print(
            flush=True
        )


        print(
            "=" * 70,
            flush=True
        )


        print(
            "       HISTORICAL UPDATE FINISHED",
            flush=True
        )


        print(
            "=" * 70,
            flush=True
        )


        print(
            f"Tổng mã hoạt động : {total}",
            flush=True
        )


        print(
            f"Đã cập nhật       : {updated_count}",
            flush=True
        )


        print(
            f"Đã đủ dữ liệu     : {skipped_count}",
            flush=True
        )


        print(
            f"Không có dữ liệu  : {no_data_count}",
            flush=True
        )


        print(
            f"Lỗi               : {failed_count}",
            flush=True
        )


        print(
            "=" * 70,
            flush=True
        )


    # =========================================================
    # ĐÓNG
    # =========================================================


    def close(self):


        self.store.close()




# =============================================================
# CHẠY ĐỘC LẬP
# =============================================================


if __name__ == "__main__":


    updater = HistoricalUpdater()


    try:


        updater.run()


    finally:


        updater.close()

