import os
import sys
import logging
from dotenv import load_dotenv

from telegram.request import HTTPXRequest
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    filters
)

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
    start_add_position,
    receive_ticker,
    receive_price,
    receive_volume,
    receive_date,
    cancel_add_position,
    cmd_sell,
    handle_portfolio_buttons,
    WAITING_TICKER,
    WAITING_PRICE,
    WAITING_VOLUME,
    WAITING_DATE
)

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")


async def post_init_setup(application: Application):
    commands = [
        ("stock", "Tra cứu tín hiệu & phân tích 1 mã (VD: /stock FPT)"),
        ("today", "Tín hiệu MUA/BÁN phát hiện trong ngày"),
        ("watchlist", "Danh sách cổ phiếu đạt chuẩn FA"),
        ("sector", "Phân tích sức mạnh & dòng tiền nhóm ngành"),
        ("alert", "Đặt cảnh báo giá tự do (VD: /alert HPG > 28.5)"),
        ("portfolio", "Danh mục tài khoản đang nắm giữ"),
        ("add", "Thêm vị thế mới vào danh mục"),
        ("sell", "Xóa vị thế khỏi danh mục (VD: /sell HPG)"),
        ("help", "Hướng dẫn sử dụng Bot")
    ]
    await application.bot.set_my_commands(commands)
    logger.info("✅ Đã thiết lập Menu gợi ý lệnh thành công!")

    if application.job_queue:
        application.job_queue.run_repeating(
            check_market_alerts_job, 
            interval=120, 
            first=10
        )


def main():
    if not TOKEN:
        logger.error("❌ LỖI: Chưa cài đặt TELEGRAM_BOT_TOKEN trong file .env!")
        sys.exit(1)

    request = HTTPXRequest(connect_timeout=30.0, read_timeout=30.0)

    app = (
        Application.builder()
        .token(TOKEN)
        .request(request)
        .post_init(post_init_setup)
        .build()
    )

    # 1. Form nhập vị thế từng bước (ConversationHandler - 4 bước)
    add_conv_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(start_add_position, pattern="^btn_add_pos$"),
            CommandHandler("add", start_add_position)
        ],
        states={
            WAITING_TICKER: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_ticker)],
            WAITING_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_price)],
            WAITING_VOLUME: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_volume)],
            WAITING_DATE: [
                CallbackQueryHandler(receive_date, pattern="^date_today$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_date)
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_add_position)],
    )

    # 2. Đăng ký Handlers
    app.add_handler(add_conv_handler)

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("stock", stock_command))
    app.add_handler(CommandHandler("portfolio", portfolio_command))
    app.add_handler(CommandHandler("today", today_command))
    app.add_handler(CommandHandler("watchlist", watchlist_command))
    app.add_handler(CommandHandler("sector", sector_command))
    app.add_handler(CommandHandler("alert", alert_command))
    app.add_handler(CommandHandler("sell", cmd_sell))

    app.add_handler(CallbackQueryHandler(handle_portfolio_buttons, pattern="^btn_del_pos$"))
    app.add_handler(CallbackQueryHandler(handle_button_click))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_ticker))

    logger.info("🚀 Bot đang chạy...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()