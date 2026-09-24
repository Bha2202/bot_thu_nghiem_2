import os
import sys
import logging
import asyncio
from datetime import time

from dotenv import load_dotenv

from telegram.request import HTTPXRequest
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters
)

# =============================================================
# IMPORT HANDLER TELEGRAM
# =============================================================

from bot.handlers import (
    start_command,
    help_command,
    stock_command,
    portfolio_command,
    today_command,
    watchlist_command,
    watchlist_button_click,
    add_watchlist_cmd,
    del_watchlist_cmd,
    sector_command,
    alert_command,
    check_market_alerts_job,
    handle_button_click,
    handle_portfolio_buttons,
    handle_text_ticker,
)

# =============================================================
# IMPORT REALTIME PIPELINE
# =============================================================

from stock_bot.data_pipeline.main import (
    start_realtime_pipeline,
    stop_realtime_pipeline,
)

# =============================================================
# CẤU HÌNH LOGGING
# =============================================================

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

logger = logging.getLogger(__name__)

# =============================================================
# TẢI BIẾN MÔI TRƯỜNG
# =============================================================

load_dotenv()

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")


# =============================================================
# TỰ ĐỘNG CẬP NHẬT DỮ LIỆU LỊCH SỬ
# =============================================================

async def update_history_job(context):
    """
    Tự động cập nhật dữ liệu lịch sử.

    Chạy:
        python -m stock_bot.data_pipeline.update_history

    Output được đọc bằng UTF-8 và hiển thị
    trong log của Telegram Bot.
    """

    logger.info(
        "🔄 Bắt đầu cập nhật dữ liệu lịch sử..."
    )

    try:

        # -----------------------------------------------------
        # Chạy update_history.py dưới dạng subprocess
        # -----------------------------------------------------

        process = await asyncio.create_subprocess_exec(

            # Python hiện tại đang chạy bot
            sys.executable,

            # -u = unbuffered
            "-u",

            # Chạy module update_history
            "-m",
            "stock_bot.data_pipeline.update_history",

            # Đọc stdout
            stdout=asyncio.subprocess.PIPE,

            # Gộp stderr vào stdout
            stderr=asyncio.subprocess.STDOUT,

            # Ép Python subprocess dùng UTF-8
            env={
                **os.environ,
                "PYTHONIOENCODING": "utf-8"
            }
        )

        # -----------------------------------------------------
        # Đọc log realtime từng dòng
        # -----------------------------------------------------

        while True:

            line = await process.stdout.readline()

            if not line:
                break

            text = line.decode(
                "utf-8",
                errors="replace"
            ).rstrip()

            if text:
                logger.info(text)

        # -----------------------------------------------------
        # Chờ subprocess kết thúc
        # -----------------------------------------------------

        return_code = await process.wait()

        # -----------------------------------------------------
        # Kiểm tra kết quả
        # -----------------------------------------------------

        if return_code == 0:

            logger.info(
                "✅ Cập nhật dữ liệu lịch sử thành công!"
            )

        else:

            logger.error(
                "❌ Cập nhật dữ liệu lịch sử thất bại! "
                f"Mã lỗi: {return_code}"
            )

    except Exception as e:

        logger.exception(
            f"❌ Lỗi khi chạy update_history.py: {e}"
        )


# =============================================================
# KHỞI ĐỘNG REALTIME PIPELINE
# =============================================================

async def post_init_setup(application: Application):
    """
    Hàm khởi tạo tự động chạy sau khi Telegram Bot sẵn sàng.

    1. Khởi động Vietcap Realtime Pipeline.
    2. Thiết lập Menu Telegram.
    3. Quét cảnh báo giá mỗi 2 phút.
    4. Chạy cập nhật dữ liệu lịch sử sau 10 giây.
    """

    # =========================================================
    # 0. KHỞI ĐỘNG VIETCAP REALTIME
    # =========================================================

    try:

        logger.info(
            "⚡ Đang khởi động Vietcap Realtime Pipeline..."
        )

        start_realtime_pipeline()

        logger.info(
            "✅ Vietcap Realtime Pipeline đã khởi động!"
        )

    except Exception as e:

        logger.exception(
            f"❌ Không khởi động được Realtime Pipeline: {e}"
        )

    # =========================================================
    # 1. MENU TELEGRAM
    # =========================================================

    commands = [
        (
            "stock",
            "Tra cứu tín hiệu & phân tích 1 mã (VD: /stock FPT)"
        ),
        (
            "today",
            "Tín hiệu MUA/BÁN phát hiện trong ngày"
        ),
        (
            "watchlist",
            "Danh sách cổ phiếu đạt chuẩn FA (Lớp 1 & 2)"
        ),
        (
            "sector",
            "Phân tích sức mạnh & dòng tiền nhóm ngành"
        ),
        (
            "alert",
            "Đặt cảnh báo giá tự do (VD: /alert HPG > 28.5)"
        ),
        (
            "portfolio",
            "Danh mục tài khoản đang nắm giữ"
        ),
        (
            "help",
            "Hướng dẫn sử dụng Bot"
        )
    ]

    await application.bot.set_my_commands(
        commands
    )

    logger.info(
        "✅ Đã thiết lập Menu gợi ý lệnh thành công trên Telegram!"
    )

    # =========================================================
    # 2. JOBQUEUE
    # =========================================================

    if application.job_queue:

        # -----------------------------------------------------
        # Quét cảnh báo giá mỗi 2 phút
        # -----------------------------------------------------

        application.job_queue.run_repeating(
            check_market_alerts_job,
            interval=120,
            first=10
        )

        logger.info(
            "⏰ Đã kích hoạt JobQueue quét cảnh báo giá "
            "Realtime (2 phút/lần)!"
        )

        # -----------------------------------------------------
        # 3. CẬP NHẬT LỊCH SỬ - ĐANG TEST
        # -----------------------------------------------------

        application.job_queue.run_once(
            update_history_job,
            when=10
        )

        logger.info(
            "📊 Đã đặt lịch TEST cập nhật dữ liệu lịch sử "
            "sau 10 giây!"
        )


# =============================================================
# SHUTDOWN REALTIME PIPELINE
# =============================================================

async def post_shutdown_setup(application: Application):
    """
    Đóng Vietcap Realtime Pipeline khi Telegram Bot shutdown.
    """

    try:

        logger.info(
            "🛑 Đang đóng Vietcap Realtime Pipeline..."
        )

        stop_realtime_pipeline()

        logger.info(
            "✅ Vietcap Realtime Pipeline đã được đóng."
        )

    except Exception as e:

        logger.exception(
            f"❌ Lỗi khi đóng Realtime Pipeline: {e}"
        )


# =============================================================
# MAIN
# =============================================================

def main():

    # ---------------------------------------------------------
    # Kiểm tra TOKEN
    # ---------------------------------------------------------

    if not TOKEN:

        logger.error(
            "❌ LỖI: Chưa cài đặt TELEGRAM_BOT_TOKEN "
            "trong file .env!"
        )

        sys.exit(1)

    # ---------------------------------------------------------
    # Cấu hình HTTP
    # ---------------------------------------------------------

    request = HTTPXRequest(
        connect_timeout=30.0,
        read_timeout=30.0
    )

    # ---------------------------------------------------------
    # Tạo Application
    # ---------------------------------------------------------

    app = (
        Application.builder()
        .token(TOKEN)
        .request(request)
        .post_init(post_init_setup)
        .post_shutdown(post_shutdown_setup)
        .build()
    )

    # =========================================================
    # COMMAND HANDLER
    # =========================================================

    # /start
    app.add_handler(
        CommandHandler(
            "start",
            start_command
        )
    )

    # /help
    app.add_handler(
        CommandHandler(
            "help",
            help_command
        )
    )

    # =========================================================
    # WATCHLIST COMMAND
    # =========================================================

    # /wladd
    app.add_handler(
        CommandHandler(
            "wladd",
            add_watchlist_cmd
        )
    )

    # /wldel
    app.add_handler(
        CommandHandler(
            "wldel",
            del_watchlist_cmd
        )
    )

    # =========================================================
    # CALLBACK WATCHLIST
    # =========================================================

    app.add_handler(
        CallbackQueryHandler(
            watchlist_button_click,
            pattern="^wl_"
        )
    )

    # =========================================================
    # CALLBACK PORTFOLIO
    # =========================================================

    app.add_handler(
        CallbackQueryHandler(
            handle_portfolio_buttons,
            pattern="^btn_del_pos$"
        )
    )

    # =========================================================
    # COMMAND STOCK
    # =========================================================

    app.add_handler(
        CommandHandler(
            "stock",
            stock_command
        )
    )

    # =========================================================
    # COMMAND PORTFOLIO
    # =========================================================

    app.add_handler(
        CommandHandler(
            "portfolio",
            portfolio_command
        )
    )

    # =========================================================
    # COMMAND TODAY
    # =========================================================

    app.add_handler(
        CommandHandler(
            "today",
            today_command
        )
    )

    # =========================================================
    # COMMAND WATCHLIST
    # =========================================================

    app.add_handler(
        CommandHandler(
            "watchlist",
            watchlist_command
        )
    )

    # =========================================================
    # COMMAND SECTOR
    # =========================================================

    app.add_handler(
        CommandHandler(
            "sector",
            sector_command
        )
    )

    # =========================================================
    # COMMAND ALERT
    # =========================================================

    app.add_handler(
        CommandHandler(
            "alert",
            alert_command
        )
    )

    # =========================================================
    # CALLBACK QUERY CHUNG
    # =========================================================

    app.add_handler(
        CallbackQueryHandler(
            handle_button_click
        )
    )

    # =========================================================
    # MESSAGE HANDLER
    # =========================================================

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_text_ticker
        )
    )

    # =========================================================
    # CHẠY BOT
    # =========================================================

    logger.info(
        "🚀 Telegram Bot đang khởi chạy..."
    )

    logger.info(
        "⚡ Realtime: Vietcap → DNSE Failover"
    )

    logger.info(
        "📊 Historical: KBS → DNSE Fallback"
    )

    logger.info(
        "📡 Bot đang lắng nghe Telegram..."
    )

    app.run_polling(
        drop_pending_updates=True
    )


# =============================================================
# ENTRY POINT
# =============================================================

if __name__ == "__main__":
    main()