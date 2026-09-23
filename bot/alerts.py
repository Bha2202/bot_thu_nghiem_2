import logging
import json
import os
from telegram.ext import Application
from bot.handlers import get_current_price, WATCH_LIST_PATH, POSITIONS_PATH

logger = logging.getLogger(__name__)

async def check_portfolio_stoploss(app: Application):
    """Job 1: Quét danh mục cá nhân, cảnh báo khi giá chạm vùng Cắt lỗ."""
    if not os.path.exists(POSITIONS_PATH):
        return

    try:
        with open(POSITIONS_PATH, "r", encoding="utf-8") as f:
            positions = json.load(f)

        for pos in positions:
            ticker = pos.get("ticker", "").upper()
            stop_loss = pos.get("stop_loss", 0)
            chat_id = pos.get("chat_id")  # Lưu ID người dùng sở hữu vị thế

            if not ticker or stop_loss <= 0 or not chat_id:
                continue

            current_price = get_current_price(ticker)
            if current_price <= 0:
                continue

            # Nếu giá hiện tại giảm xuống dưới hoặc bằng giá Stoploss
            if current_price <= stop_loss:
                alert_msg = (
                    f"🚨 <b>CẢNH BÁO CẮT LỖ (STOP-LOSS)!</b>\n"
                    f" Mã: <b>{ticker}</b>\n"
                    f"• Giá hiện tại: <code>{current_price:,.0f} đ</code>\n"
                    f"• Ngưỡng cắt lỗ: <code>{stop_loss:,.0f} đ</code>\n"
                    f"⚠️ Giá đã chạm vùng rủi ro, vui lòng xem xét hạ tỷ trọng!"
                )
                await app.bot.send_message(chat_id=chat_id, text=alert_msg, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Lỗi khi chạy Job Stoploss Alert: {e}")


async def check_volume_breakout(app: Application):
    """Job 2: Quét các mã trong Watchlist FA có bùng nổ khối lượng (Vol > 1.5x MA20)."""
    if not os.path.exists(WATCH_LIST_PATH):
        return

    try:
        with open(WATCH_LIST_PATH, "r", encoding="utf-8") as f:
            watch_data = json.load(f)

        # Lấy ADMIN_CHAT_ID hoặc chat_id đăng ký từ env
        admin_chat_id = os.getenv("ADMIN_CHAT_ID")
        if not admin_chat_id:
            return

        for item in watch_data:
            ticker = item.get("ticker") if isinstance(item, dict) else str(item)
            # Giả định gọi hàm tính TA lấy vol_ratio (Tỷ lệ Volume hiện tại / MA20 Volume)
            # Ở đây kết nối với module TA của bạn
            # vol_ratio, price_change = get_ta_volume_breakout(ticker)
            
            # Nếu vol_ratio > 1.5 và giá tăng > 2%
            # await app.bot.send_message(
            #     chat_id=admin_chat_id, 
            #     text=f"🔥 <b>TÍN HIỆU DÒNG TIỀN BÙNG NỔ!</b>\n Mã <b>{ticker}</b> Volume gấp {vol_ratio:.1f} lần trung bình 20 phiên!", 
            #     parse_mode="HTML"
            # )
            pass
    except Exception as e:
        logger.error(f"Lỗi khi chạy Job Volume Breakout: {e}")