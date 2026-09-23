import os
import json
import logging
import html
import re
import sqlite3
from datetime import datetime, time
from pathlib import Path
import requests
import pandas as pd
from telegram import Update
from telegram.ext import ContextTypes

# Import DataService để tương tác với DB & Realtime Data
from stock_bot.data_pipeline.data_service import DataService

# Thiết lập logger cơ bản nếu chưa có
logger = logging.getLogger(__name__)

# Các đường dẫn file và cấu hình cố định
ALERTS_PATH = "data/price_alerts.json"
POSITIONS_PATH = "data/positions.json"
DB_PATH = "data/market_data.db"


# ----------------------------------------------------
# 0. HÀM LẤY LỊCH SỬ VÀ GIÁ REALTIME (ĐÃ CHUẨN HÓA KHUNG GIỜ)
# ----------------------------------------------------
def get_price_history(ticker: str, limit: int = 80) -> pd.DataFrame:
    """
    Kéo lịch sử giá từ CSDL SQLite.
    """
    ticker = ticker.upper().strip()
    db_file = Path(DB_PATH)
    
    if not db_file.exists():
        return pd.DataFrame()

    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = [row[0] for row in cursor.fetchall() if row[0] != 'sqlite_sequence']
        
        if not tables:
            conn.close()
            return pd.DataFrame()
            
        target_table = tables[0]
        df = pd.read_sql_query(f"SELECT * FROM {target_table} LIMIT {limit}", conn)
        conn.close()

        df.columns = [c.lower() for c in df.columns]
        return df

    except Exception:
        return pd.DataFrame()


def get_current_price(ticker: str) -> float:
    """
    Lấy giá chứng khoán chuẩn xác từ DataService / CSDL SQLite
    """
    ticker = ticker.upper().strip()
    now = datetime.now()
    
    # Kiểm tra ngày làm việc (Thứ 2 đến Thứ 6)
    is_weekday = now.weekday() < 5
    market_open = time(9, 0)
    market_close = time(15, 0)
    
    is_trading_hours = is_weekday and (market_open <= now.time() <= market_close)

    # 1. Trong giờ giao dịch: Lấy giá Realtime từ DataService
    if is_trading_hours:
        try:
            # Khởi tạo instance của DataService
            service = DataService()
            latest = service.get_latest(ticker)
            service.close() # Đóng kết nối DB sau khi dùng
            
            if latest and isinstance(latest, dict) and 'price' in latest:
                price = float(latest['price'])
                if price > 0:
                    return price
            elif latest and hasattr(latest, 'price'): # Nếu latest trả về object/dataclass
                price = float(latest.price)
                if price > 0:
                    return price
        except Exception as e:
            logger.warning(f"Không lấy được giá Realtime cho {ticker}, chuyển sang giá đóng cửa: {e}")

    # 2. Ngoài giờ giao dịch hoặc fallback: Lấy giá đóng cửa phiên gần nhất
    try:
        df = get_price_history(ticker, limit=5)
        if not df.empty and 'close' in df.columns:
            latest_close = df['close'].iloc[-1]
            return float(latest_close)
    except Exception as e:
        logger.error(f"Lỗi lấy giá đóng cửa gần nhất cho {ticker}: {e}")

    return 0.0

# ----------------------------------------------------
# 1. QUẢN LÝ DỮ LIỆU CẢNH BÁO GIÁ THỦ CÔNG
# ----------------------------------------------------
def load_price_alerts() -> list:
    if os.path.exists(ALERTS_PATH):
        try:
            with open(ALERTS_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []

def save_price_alerts(alerts: list):
    os.makedirs(os.path.dirname(ALERTS_PATH), exist_ok=True)
    with open(ALERTS_PATH, "w", encoding="utf-8") as f:
        json.dump(alerts, f, ensure_ascii=False, indent=2)


def _normalize_price(price) -> float:
    try:
        return float(price)
    except Exception:
        return 0.0


async def check_single_alert(bot, alert: dict) -> bool:
    """Hàm kiểm tra 1 cảnh báo đơn lẻ. Trả về True nếu đã phát cảnh báo."""
    chat_id = alert.get("chat_id")
    ticker = alert.get("ticker", "").upper()
    op = alert.get("operator")
    target_p = alert.get("target_price", 0)

    curr_p = _normalize_price(get_current_price(ticker))

    if curr_p > 0:
        triggered = False
        if op in [">", ">="] and curr_p >= target_p:
            triggered = True
        elif op in ["<", "<="] and curr_p <= target_p:
            triggered = True

        if triggered:
            safe_op = html.escape(str(op))
            msg = (
                f"🚨 <b>CẢNH BÁO GIÁ KÍCH HOẠT!</b>\n"
                f"=====================================\n"
                f"• Mã cổ phiếu: <b>{ticker}</b>\n"
                f"• Giá hiện tại: <b>{curr_p:,.0f} VNĐ</b>\n"
                f"• Mức cảnh báo đặt: Giá {safe_op} <b>{target_p:,.0f} VNĐ</b>\n\n"
                f"💡 <i>Gõ <code>/stock {ticker}</code> để xem phân tích chi tiết.</i>"
            )
            try:
                await bot.send_message(chat_id=chat_id, text=msg, parse_mode="HTML")
                return True
            except Exception as e:
                logger.error(f"Lỗi gửi tin nhắn alert cho {chat_id}: {e}")
    return False


async def alert_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Lệnh đặt cảnh báo giá thông minh:
    - /alert HPG > 28.5 hoặc /alert HPG < 23
    - /alert list (Xem danh sách)
    - /alert delete 1 3 4 (Xóa nhiều STT cùng lúc)
    """
    chat_id = update.effective_chat.id
    args = context.args

    if not args:
        await update.message.reply_text(
            "⚠️ <b>Cú pháp không hợp lệ!</b>\n\n"
            "👉 Vui lòng nhập theo dạng:\n"
            "• <code>/alert HPG &gt; 28.5</code> (Báo khi giá vượt 28.5)\n"
            "• <code>/alert FPT &lt; 120</code> (Báo khi giá giảm dưới 120)\n"
            "• <code>/alert list</code> (Xem danh sách cảnh báo)\n"
            "• <code>/alert delete 1 3 5</code> (Xóa các cảnh báo số 1, 3, 5)",
            parse_mode="HTML"
        )
        return

    # 1. Xử lý lệnh /alert list
    if args[0].lower() == "list":
        alerts = load_price_alerts()
        user_alerts = [a for a in alerts if a.get("chat_id") == chat_id]
        if not user_alerts:
            await update.message.reply_text("📭 Bạn chưa thiết lập cảnh báo giá nào.")
            return

        msg = "🔔 <b>DANH SÁCH CẢNH BÁO GIÁ CỦA BẠN:</b>\n" + "="*32 + "\n"
        for idx, a in enumerate(user_alerts, 1):
            safe_op = html.escape(str(a['operator']))
            msg += f"{idx}. <b>{a['ticker']}</b> {safe_op} {a['target_price']:,.0f} VNĐ\n"
        msg += "\n💡 <i>Gõ <code>/alert delete 1 2</code> để xóa các STT tương ứng.</i>"
        await update.message.reply_text(msg, parse_mode="HTML")
        return

    # 2. Xử lý xóa nhiều STT cùng lúc
    if args[0].lower() == "delete" and len(args) >= 2:
        alerts = load_price_alerts()
        user_alerts = [a for a in alerts if a.get("chat_id") == chat_id]

        if not user_alerts:
            await update.message.reply_text("📭 Bạn không có cảnh báo nào để xóa.")
            return

        raw_indices = re.findall(r'\d+', " ".join(args[1:]))
        if not raw_indices:
            await update.message.reply_text("⚠️ Vui lòng nhập STT hợp lệ. Ví dụ: <code>/alert delete 1 3 4</code>", parse_mode="HTML")
            return

        indices_to_delete = sorted(list(set(int(x) - 1 for x in raw_indices)), reverse=True)
        deleted_tickers = []

        for idx in indices_to_delete:
            if 0 <= idx < len(user_alerts):
                target = user_alerts[idx]
                if target in alerts:
                    alerts.remove(target)
                    deleted_tickers.append(f"{target['ticker']} ({html.escape(target['operator'])}{target['target_price']:,.0f})")

        if deleted_tickers:
            save_price_alerts(alerts)
            await update.message.reply_text(
                f"✅ <b>Đã xóa thành công {len(deleted_tickers)} cảnh báo:</b>\n• " + "\n• ".join(deleted_tickers),
                parse_mode="HTML"
            )
        else:
            await update.message.reply_text("⚠️ Không tìm thấy STT nào phù hợp!")
        return

    # 3. Tạo cảnh báo mới
    full_text = " ".join(args).strip()
    operator = None
    if ">=" in full_text: operator = ">="
    elif "<=" in full_text: operator = "<="
    elif ">" in full_text: operator = ">"
    elif "<" in full_text: operator = "<"

    if not operator:
        await update.message.reply_text("⚠️ Thiếu toán tử so sánh (phải có dấu <code>&gt;</code> hoặc <code>&lt;</code>)!", parse_mode="HTML")
        return

    parts = full_text.split(operator)
    ticker = parts[0].strip().upper()
    price_str = parts[1].strip()

    if not ticker or not price_str:
        await update.message.reply_text("⚠️ Cú pháp không hợp lệ! Ví dụ đúng: <code>/alert HPG &gt; 28.5</code>", parse_mode="HTML")
        return

    try:
        raw_price = float(price_str.replace(",", "."))
        target_price = raw_price * 1000.0 if raw_price < 1000 else raw_price
    except ValueError:
        await update.message.reply_text("⚠️ Mức giá nhập vào không đúng định dạng số!")
        return

    new_alert = {
        "chat_id": chat_id,
        "ticker": ticker,
        "operator": operator,
        "target_price": target_price,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M")
    }

    # Kiểm tra ngay lập tức xem giá hiện tại đã thỏa mãn điều kiện chưa
    is_triggered = await check_single_alert(context.bot, new_alert)
    if is_triggered:
        return  # Nếu đã chạm ngưỡng ngay lúc đặt thì báo động luôn, không cần lưu

    # Lưu vào file chờ JobQueue quét định kỳ
    alerts = load_price_alerts()
    alerts.append(new_alert)
    save_price_alerts(alerts)

    safe_op = html.escape(operator)
    await update.message.reply_text(
        f"✅ <b>Đã kích hoạt Cảnh báo giá!</b>\n\n"
        f"• Mã: <b>{ticker}</b>\n"
        f"• Điều kiện: Giá {safe_op} <b>{target_price:,.0f} VNĐ</b>\n"
        f"🤖 Bot sẽ nhắn tin cho bạn ngay khi chạm ngưỡng.",
        parse_mode="HTML"
    )

# ----------------------------------------------------
# 2. CRONJOB QUÉT GIÁ REALTIME & CẢNH BÁO VI PHẠM (JOB QUEUE)
# ----------------------------------------------------
async def check_market_alerts_job(context: ContextTypes.DEFAULT_TYPE):
    """
    Hàm định kỳ quét giá thị trường:
    1. Kiểm tra cảnh báo giá người dùng tự đặt (/alert).
    2. Kiểm tra vi phạm Stop-Loss / Take-Profit trong Portfolio.
    """
    # A. Quét Cảnh Báo Giá Tự Đặt (/alert)
    alerts = load_price_alerts()
    remaining_alerts = []

    for alert in alerts:
        triggered = await check_single_alert(context.bot, alert)
        if not triggered:
            remaining_alerts.append(alert)

    save_price_alerts(remaining_alerts)

    # B. Quét Vi Phạm Cắt Lỗ / Chốt Lời (Portfolio)
    if os.path.exists(POSITIONS_PATH):
        try:
            with open(POSITIONS_PATH, "r", encoding="utf-8") as f:
                positions = json.load(f)

            pos_items = positions if isinstance(positions, list) else list(positions.values())

            for pos in pos_items:
                if not isinstance(pos, dict):
                    continue

                ticker = pos.get("ticker", "").upper()
                chat_id = pos.get("chat_id")
                
                if not chat_id or not ticker:
                    continue

                sl_price = _normalize_price(pos.get("stop_loss", 0))
                tp_price = _normalize_price(pos.get("take_profit", 0))
                buy_price = _normalize_price(pos.get("buy_price", pos.get("entry_price", 0)))

                curr_p = _normalize_price(get_current_price(ticker))

                if curr_p <= 0:
                    continue

                # 1. Kiểm tra vi phạm Cắt lỗ (Stop Loss)
                if sl_price > 0 and curr_p <= sl_price:
                    pnl_pct = ((curr_p - buy_price) / buy_price) * 100 if buy_price > 0 else 0.0
                    msg = (
                        f"⚠️ <b>CẢNH BÁO VI PHẠM CẮT LỖ (STOP-LOSS)!</b>\n"
                        f"=====================================\n"
                        f"• Mã: <b>{ticker}</b>\n"
                        f"• Giá hiện tại: <b>{curr_p:,.0f} VNĐ</b> (Lỗ {pnl_pct:.1f}% 🔴)\n"
                        f"• Ngưỡng Cắt lỗ: <b>{sl_price:,.0f} VNĐ</b>\n\n"
                        f"🛑 <b>Hành động khuyến nghị:</b> Cân nhắc hạ tỷ trọng hoặc đóng vị thế!"
                    )
                    try:
                        await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode="HTML")
                    except Exception as e:
                        logger.error(f"Lỗi gửi tin Stop-loss cho {chat_id}: {e}")

                # 2. Kiểm tra cán mốc Chốt lời (Take Profit)
                elif tp_price > 0 and curr_p >= tp_price:
                    pnl_pct = ((curr_p - buy_price) / buy_price) * 100 if buy_price > 0 else 0.0
                    msg = (
                        f"🎯 <b>CẢNH BÁO ĐẠT MỐC CHỐT LỜI (TAKE-PROFIT)!</b>\n"
                        f"=====================================\n"
                        f"• Mã: <b>{ticker}</b>\n"
                        f"• Giá hiện tại: <b>{curr_p:,.0f} VNĐ</b> (Lãi +{pnl_pct:.1f}% 🟢)\n"
                        f"• Ngưỡng Chốt lời: <b>{tp_price:,.0f} VNĐ</b>\n\n"
                        f"💰 <b>Hành động khuyến nghị:</b> Cân nhắc chốt lời một phần!"
                    )
                    try:
                        await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode="HTML")
                    except Exception as e:
                        logger.error(f"Lỗi gửi tin Take-profit cho {chat_id}: {e}")

        except Exception as e:
            logger.error(f"Lỗi quét vị thế vi phạm: {e}")