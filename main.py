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


# Import các handler xử lý từ bot/handlers.py
from bot.handlers import (
    start_command,
    help_command,
    stock_command,
    portfolio_command,
    today_command,
    watchlist_command,
    sector_command,
    alert_command,
    check_market_alerts_job,
    handle_button_click,
    handle_text_ticker,
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


    Chạy file:
        python -m stock_bot.data_pipeline.update_history


    Output được đọc bằng UTF-8 và hiển thị realtime
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
            # giúp log xuất ra ngay
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


            # Ép UTF-8
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
# KHỞI TẠO BOT
# =============================================================


async def post_init_setup(application: Application):
    """
    Hàm khởi tạo tự động chạy sau khi Bot sẵn sàng:


    1. Thiết lập Menu Telegram.
    2. Quét giá và cảnh báo mỗi 2 phút.
    3. Chạy cập nhật dữ liệu lịch sử để test.
    """


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
        #
        # Chạy sau 60 giây kể từ lúc bot khởi động.
        #
        # SAU KHI TEST THÀNH CÔNG:
        # sẽ đổi phần này sang run_daily lúc 16:00 VN.
        # -----------------------------------------------------


        application.job_queue.run_once(
            update_history_job,
            when=10
        )


        logger.info(
            "📊 Đã đặt lịch TEST cập nhật dữ liệu lịch sử "
            "sau 60 giây!"
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
        .build()
    )


    # =========================================================
    # COMMAND HANDLER
    # =========================================================


    app.add_handler(
        CommandHandler(
            "start",
            start_command
        )
    )


    app.add_handler(
        CommandHandler(
            "help",
            help_command
        )
    )


    app.add_handler(
        CommandHandler(
            "stock",
            stock_command
        )
    )


    app.add_handler(
        CommandHandler(
            "portfolio",
            portfolio_command
        )
    )


    app.add_handler(
        CommandHandler(
            "today",
            today_command
        )
    )


    app.add_handler(
        CommandHandler(
            "watchlist",
            watchlist_command
        )
    )


    app.add_handler(
        CommandHandler(
            "sector",
            sector_command
        )
    )


    app.add_handler(
        CommandHandler(
            "alert",
            alert_command
        )
    )


    # =========================================================
    # CALLBACK QUERY
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
        "🚀 Telegram Bot đã khởi chạy thành công "
        "và đang lắng nghe..."
    )


    app.run_polling(
        drop_pending_updates=True
    )




# =============================================================
# ENTRY POINT
# =============================================================


if __name__ == "__main__":
    main()

