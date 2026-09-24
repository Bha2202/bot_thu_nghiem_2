import csv
import time
import sys
import shutil

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

    TIMEZONE = ZoneInfo("Asia/Ho_Chi_Minh")

    # =========================================================
    # KHỞI TẠO
    # =========================================================

    def __init__(
        self,
        db_path="data/market_data.db",
        symbols_path="data/symbols.csv",
        start_date="2025-01-01",
        request_delay=1.5,
        max_retry=3
    ):

        self.db_path = db_path
        self.symbols_path = symbols_path
        self.start_date = start_date
        self.request_delay = request_delay
        self.max_retry = max_retry

        # =====================================================
        # KBS CHÍNH → DNSE FALLBACK
        # =====================================================

        self.collector = HistoricalCollector(
            source="KBS"
        )

        # =====================================================
        # TRẠNG THÁI RATE LIMIT KBS
        #
        # False = vẫn dùng KBS
        # True  = KBS đã bị limit → mã sau dùng DNSE
        # =====================================================

        self.kbs_rate_limited = False

        self.store = HistoricalStore(
            db_path=self.db_path
        )

        self.failed_symbols = []

        # =====================================================
        # THỐNG KÊ
        # =====================================================

        self.kbs_count = 0
        self.dnse_fallback_count = 0
        self.no_data_count = 0
        self.failed_count = 0
        self.updated_count = 0
        self.skipped_count = 0

        # =====================================================
        # BACKUP
        # =====================================================

        self.backup_path = None

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

        # -----------------------------------------------------
        # THỨ 7 / CHỦ NHẬT
        # Không có phiên giao dịch
        # -----------------------------------------------------

        if now.weekday() >= 5:
            return None

        # -----------------------------------------------------
        # TRƯỚC 15:15
        # Phiên hôm nay chưa kết thúc
        # → lấy phiên giao dịch gần nhất trước đó
        # -----------------------------------------------------

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

            # Nếu là thứ 2 thì lùi từ Chủ nhật
            # về thứ 6
            while previous_day.weekday() >= 5:

                previous_day -= timedelta(days=1)

            return previous_day

        # -----------------------------------------------------
        # TỪ 15:15 TRỞ ĐI
        # Phiên hôm nay đã kết thúc
        # → cập nhật toàn bộ OHLCV hôm nay
        # -----------------------------------------------------

        return now.date()

    # =========================================================
    # KIỂM TRA CÓ ĐƯỢC CẬP NHẬT KHÔNG
    # =========================================================

    @classmethod
    def can_update_history(cls):

        now = cls.now_vietnam()

        # Thứ 7 / Chủ nhật
        if now.weekday() >= 5:
            return False

        # Trước 15:15
        if now.hour < 15:
            return False

        if now.hour == 15 and now.minute < 15:
            return False

        return True

    # =========================================================
    # BACKUP DATABASE
    # =========================================================

    def backup_database(self):

        source = Path(
            self.db_path
        )

        if not source.exists():

            print(
                f"[BACKUP] Không tìm thấy database: {source}",
                flush=True
            )

            print(
                "[BACKUP] Bỏ qua backup vì database chưa tồn tại.",
                flush=True
            )

            return False

        backup_dir = (
            Path("data")
            / "backups"
        )

        backup_dir.mkdir(
            parents=True,
            exist_ok=True
        )

        now = self.now_vietnam()

        timestamp = now.strftime(
            "%Y%m%d_%H%M%S"
        )

        backup_file = (
            backup_dir
            / f"market_data_backup_{timestamp}.db"
        )

        try:

            shutil.copy2(
                source,
                backup_file
            )

            self.backup_path = backup_file

            print(
                "[BACKUP] Đã backup database:",
                flush=True
            )

            print(
                f"[BACKUP] {backup_file}",
                flush=True
            )

            return True

        except Exception as e:

            print(
                f"[BACKUP ERROR] Không thể backup DB: {e}",
                flush=True
            )

            return False

    # =========================================================
    # XÓA BACKUP CŨ
    # =========================================================

    def cleanup_old_backups(
        self,
        keep=7
    ):

        backup_dir = (
            Path("data")
            / "backups"
        )

        if not backup_dir.exists():
            return

        backups = sorted(
            backup_dir.glob(
                "market_data_backup_*.db"
            ),
            key=lambda x: x.stat().st_mtime,
            reverse=True
        )

        old_backups = backups[keep:]

        for backup in old_backups:

            try:

                backup.unlink()

                print(
                    f"[BACKUP] Đã xóa backup cũ: "
                    f"{backup.name}",
                    flush=True
                )

            except Exception as e:

                print(
                    f"[BACKUP ERROR] "
                    f"Không xóa được {backup.name}: {e}",
                    flush=True
                )

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

            reader = csv.DictReader(
                file
            )

            for row in reader:

                symbol = row.get(
                    "symbol"
                )

                if not symbol:
                    continue

                symbol = (
                    symbol
                    .strip()
                    .upper()
                )

                if not symbol:
                    continue

                if symbol in self.INACTIVE_SYMBOLS:
                    continue

                symbols.append(
                    symbol
                )

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

        if not last_date:
            return True

        return (
            str(last_date)
            < target_date.isoformat()
        )

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
            # CHƯA CÓ DỮ LIỆU
            # -------------------------------------------------

            if not last_date:

                start = self.start_date

            # -------------------------------------------------
            # ĐÃ CÓ DỮ LIỆU
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
            # ĐÃ CẬP NHẬT ĐỦ
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

            # =================================================
            # GỌI API
            # =================================================

            df = None

            # =================================================
            # KBS ĐÃ BỊ RATE LIMIT
            # → ĐI THẲNG DNSE
            # =================================================

            if self.kbs_rate_limited:

                print(
                    f"[KBS PAUSED] {symbol}: "
                    f"KBS đang bị giới hạn → "
                    f"dùng DNSE.",
                    flush=True
                )

                try:

                    df = (
                        self.collector
                        .get_history_from_dnse(
                            symbol=symbol,
                            start=start,
                            end=end
                        )
                    )

                except AttributeError:

                    # Tương thích collector hiện tại
                    df = (
                        self.collector
                        ._get_history_from_dnse(
                            symbol=symbol,
                            start=start,
                            end=end
                        )
                    )

                except Exception as e:

                    print(
                        f"[DNSE ERROR] {symbol}: {e}",
                        flush=True
                    )

                    df = None

            # =================================================
            # KBS VẪN ĐANG HOẠT ĐỘNG
            # =================================================

            else:

                try:

                    print(
                        f"[API] {symbol}: "
                        f"Đang lấy dữ liệu từ KBS...",
                        flush=True
                    )

                    df = (
                        self.collector
                        .get_history(
                            symbol=symbol,
                            start=start,
                            end=end
                        )
                    )

                    # -----------------------------------------
                    # KIỂM TRA KBS RATE LIMIT
                    # -----------------------------------------

                    if getattr(
                        self.collector,
                        "kbs_rate_limited",
                        False
                    ):

                        self.kbs_rate_limited = True

                        print(
                            f"[KBS RATE LIMIT] {symbol}: "
                            f"KBS đã đạt giới hạn.",
                            flush=True
                        )

                    # -----------------------------------------
                    # LOG KẾT QUẢ
                    # -----------------------------------------

                    if (
                        df is not None
                        and not df.empty
                    ):

                        print(
                            f"[API] {symbol}: "
                            f"Đã nhận {len(df)} dòng.",
                            flush=True
                        )

                    else:

                        print(
                            f"[API] {symbol}: "
                            f"Không có dữ liệu trả về.",
                            flush=True
                        )

                # ---------------------------------------------
                # BẮT SYSTEM EXIT
                # ---------------------------------------------

                except SystemExit:

                    print(
                        f"[KBS SYSTEM EXIT] {symbol}: "
                        f"KBS bị giới hạn API.",
                        flush=True
                    )

                    self.kbs_rate_limited = True

                    try:

                        try:

                            df = (
                                self.collector
                                .get_history_from_dnse(
                                    symbol=symbol,
                                    start=start,
                                    end=end
                                )
                            )

                        except AttributeError:

                            df = (
                                self.collector
                                ._get_history_from_dnse(
                                    symbol=symbol,
                                    start=start,
                                    end=end
                                )
                            )

                    except Exception as e:

                        print(
                            f"[DNSE ERROR] {symbol}: {e}",
                            flush=True
                        )

                        df = None

                # ---------------------------------------------
                # BẮT LỖI THÔNG THƯỜNG
                # ---------------------------------------------

                except Exception as e:

                    print(
                        f"[ERROR] {symbol}: "
                        f"{type(e).__name__}: {e}",
                        flush=True
                    )

                    df = None

            # =================================================
            # KHÔNG CÓ DỮ LIỆU
            # =================================================

            if df is None or df.empty:

                print(
                    f"[NO NEW DATA] {symbol}",
                    flush=True
                )

                self.no_data_count += 1

                return "no_data"

            # =================================================
            # XÁC ĐỊNH NGUỒN
            # =================================================

            source_used = getattr(
                self.collector,
                "last_source",
                None
            )

            if (
                self.kbs_rate_limited
                and source_used is None
            ):

                source_used = "DNSE"

            if source_used == "KBS":

                self.kbs_count += 1

                print(
                    f"[SOURCE] {symbol}: KBS",
                    flush=True
                )

            elif source_used == "DNSE":

                self.dnse_fallback_count += 1

                print(
                    f"[SOURCE] {symbol}: "
                    f"DNSE FALLBACK",
                    flush=True
                )

            else:

                print(
                    f"[SOURCE] {symbol}: "
                    f"Không xác định "
                    f"({source_used})",
                    flush=True
                )

            # =================================================
            # LƯU SQLITE
            # =================================================

            print(
                f"[DB] {symbol}: "
                f"Đang lưu {len(df)} dòng...",
                flush=True
            )

            self.store.save(
                df
            )

            print(
                f"[UPDATED] {symbol}: "
                f"thêm {len(df)} dòng.",
                flush=True
            )

            self.updated_count += 1

            return "updated"

        except Exception as e:

            print(
                f"[FAILED] {symbol}: {e}",
                flush=True
            )

            self.failed_symbols.append(
                symbol
            )

            self.failed_count += 1

            return "failed"

    # =========================================================
    # KIỂM TRA SAU KHI CẬP NHẬT
    # =========================================================

    def verify_target_date(
        self,
        symbols,
        target_date
    ):

        target = target_date.isoformat()

        completed = 0
        missing = []

        print(
            "\n[VERIFY] Kiểm tra lại dữ liệu SQLite...",
            flush=True
        )

        for symbol in symbols:

            last_date = (
                self.store
                .get_last_date(symbol)
            )

            if (
                last_date
                and str(last_date) >= target
            ):

                completed += 1

            else:

                missing.append(
                    (
                        symbol,
                        last_date
                    )
                )

        print(
            f"[VERIFY] Đã có dữ liệu đến {target}: "
            f"{completed}/{len(symbols)} mã",
            flush=True
        )

        print(
            f"[VERIFY] Còn thiếu ngày {target}: "
            f"{len(missing)} mã",
            flush=True
        )

        if missing:

            preview = missing[:20]

            print(
                "[VERIFY] Một số mã còn thiếu:",
                flush=True
            )

            for symbol, last_date in preview:

                print(
                    f"    {symbol}: "
                    f"DB cuối = {last_date}",
                    flush=True
                )

        return completed, missing

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

        # =====================================================
        # XÁC ĐỊNH PHIÊN CUỐI CÙNG
        # =====================================================

        target_date = (
            self.get_last_completed_trading_date()
        )

        # =====================================================
        # THỨ 7 / CHỦ NHẬT
        # KHÔNG LÀM BẤT CỨ GÌ
        # =====================================================

        if target_date is None:

            print(
                "[HISTORY] Hôm nay là thứ 7/chủ nhật.",
                flush=True
            )

            print(
                "[HISTORY] Không có phiên giao dịch "
                "→ không chạy cập nhật lịch sử.",
                flush=True
            )

            return

        print(
            f"[HISTORY] Phiên cuối cần cập nhật: "
            f"{target_date}",
            flush=True
        )

        # =====================================================
        # TEST MODE
        # =====================================================

        print(
            "[HISTORY] TEST MODE: "
            "cập nhật lịch sử ngay lập tức.",
            flush=True
        )

        # =====================================================
        # BACKUP
        # =====================================================

        print(
            "\n[BACKUP] Bắt đầu backup database...",
            flush=True
        )

        backup_success = (
            self.backup_database()
        )

        if backup_success:

            print(
                "[BACKUP] Backup thành công.",
                flush=True
            )

            self.cleanup_old_backups(
                keep=7
            )

        else:

            print(
                "[BACKUP WARNING] "
                "Không tạo được backup.",
                flush=True
            )

        # =====================================================
        # ĐỌC DANH SÁCH MÃ
        # =====================================================

        symbols = self.load_symbols()

        if not symbols:

            print(
                "[HISTORY] Không có mã hoạt động.",
                flush=True
            )

            return

        total = len(symbols)

        print(
            f"[HISTORY] Bắt đầu kiểm tra "
            f"{total} mã...",
            flush=True
        )

        # =====================================================
        # DUYỆT DANH SÁCH
        # =====================================================

        for index, symbol in enumerate(
            symbols,
            start=1
        ):

            print(
                f"\n[{index}/{total}] {symbol}",
                flush=True
            )

            # -------------------------------------------------
            # KIỂM TRA DB
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

                self.skipped_count += 1

                continue

            # -------------------------------------------------
            # CẬP NHẬT
            # -------------------------------------------------

            result = self.update_symbol(
                symbol,
                target_date
            )

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

                writer = csv.writer(
                    file
                )

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
        # VERIFY
        # =====================================================

        completed_count, missing_symbols = (
            self.verify_target_date(
                symbols,
                target_date
            )
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
            f"Tổng mã hoạt động       : "
            f"{total}",
            flush=True
        )

        print(
            f"Đã cập nhật             : "
            f"{self.updated_count}",
            flush=True
        )

        print(
            f"  └─ KBS                 : "
            f"{self.kbs_count}",
            flush=True
        )

        print(
            f"  └─ DNSE fallback       : "
            f"{self.dnse_fallback_count}",
            flush=True
        )

        print(
            f"Đã đủ dữ liệu           : "
            f"{self.skipped_count}",
            flush=True
        )

        print(
            f"Không có dữ liệu        : "
            f"{self.no_data_count}",
            flush=True
        )

        print(
            f"Lỗi                     : "
            f"{self.failed_count}",
            flush=True
        )

        print(
            f"Đã có đến {target_date}   : "
            f"{completed_count}/{total}",
            flush=True
        )

        print(
            f"Còn thiếu {target_date}   : "
            f"{len(missing_symbols)} mã",
            flush=True
        )

        if self.backup_path:

            print(
                f"Backup                  : "
                f"{self.backup_path}",
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