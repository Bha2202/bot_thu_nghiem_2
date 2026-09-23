"""
strategies/signal_generator.py — Bộ điều phối & Định dạng Tín hiệu
Nhiệm vụ:
  1. Nhận danh sách sự kiện (BUY / WATCH / SELL) từ ta_strategy.py.
  2. Lọc trùng lặp (Deduplication / Chống Spam): Không gửi lại cùng 1 loại tín hiệu
     cho cùng 1 mã trong khoảng thời gian cấu hình (VD: 4 tiếng).
  3. Format tin nhắn Telegram HTML đẹp mắt, phân biệt rõ BUY (🟢), WATCH (🟡), SELL (🔴).
  4. An toàn dữ liệu: Xử lý chuỗi 'N/A', None, và lệch đơn vị tính Lãi/Lỗ.
  5. Lưu lịch sử các tín hiệu đã phát vào data/signal_history.json.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

DEFAULT_SIGNAL_HISTORY_PATH = "data/signal_history.json"
DEDUP_COOLDOWN_HOURS = 4  # Tránh spam: Cùng 1 mã + cùng signal_type thì cách nhau ít nhất 4 tiếng mới báo lại


# ----------------------------------------------------------------------------
# Helper: Ép kiểu số an toàn (Tránh crash khi dữ liệu là 'N/A' hoặc None)
# ----------------------------------------------------------------------------
def _safe_float(val, default=None):
    if val is None or val == "N/A":
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _format_num(val, fmt="{:,.1f}", suffix=""):
    num = _safe_float(val)
    if num is None:
        return "N/A"
    return f"{fmt.format(num)}{suffix}"


# ----------------------------------------------------------------------------
# 1. Quản lý Lịch sử & Anti-Spam (Deduplication)
# ----------------------------------------------------------------------------
def load_signal_history(path: str | Path = DEFAULT_SIGNAL_HISTORY_PATH) -> list[dict]:
    path = Path(path)
    if not path.exists():
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def save_signal_history(history: list[dict], path: str | Path = DEFAULT_SIGNAL_HISTORY_PATH) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
        os.replace(tmp_name, path)
    except Exception:
        if os.path.exists(tmp_name):
            os.remove(tmp_name)
        raise


def is_duplicate_signal(event: dict, history: list[dict], cooldown_hours: int = DEDUP_COOLDOWN_HOURS) -> bool:
    """Kiểm tra xem tín hiệu này vừa mới gửi cách đây không lâu hay chưa."""
    ticker = event.get("ticker")
    signal_type = event.get("signal_type")
    event_time_str = event.get("time")

    if not ticker or not signal_type or not event_time_str:
        return False

    try:
        current_time = datetime.strptime(event_time_str, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        current_time = datetime.now()

    for item in reversed(history):
        if item.get("ticker") == ticker and item.get("signal_type") == signal_type:
            try:
                prev_time = datetime.strptime(str(item.get("time")), "%Y-%m-%d %H:%M:%S")
                if current_time - prev_time < timedelta(hours=cooldown_hours):
                    return True  # Bị trùng trong khoảng thời gian cooldown -> Bỏ qua
            except ValueError:
                continue
    return False


# ----------------------------------------------------------------------------
# 2. Template Định dạng Tin nhắn Telegram (HTML Format)
# ----------------------------------------------------------------------------
def format_telegram_message(event: dict) -> str:
    """Biến đổi dict event thành mẫu tin nhắn Telegram trực quan & an toàn."""
    ticker = event.get("ticker", "N/A")
    signal_type = event.get("signal_type", "INFO")
    time_str = event.get("time", "")
    
    price_val = _safe_float(event.get("price"), 0.0)
    price_str = _format_num(price_val, "{:,.1f}")

    ta = event.get("ta_criteria", {})
    fa = event.get("fa_criteria", {})

    # Chuẩn hóa P/E, ROE, EPS Growth không lo 'N/A' crash
    roe_val = fa.get("ROE") or fa.get("roe")
    pe_val = fa.get("PE") or fa.get("pe") or fa.get("P/E")
    eps_val = fa.get("EPS_Growth") or fa.get("eps_growth_qoq") or fa.get("eps_growth_yoy")

    roe_str = _format_num(roe_val, "{:.1f}", "%")
    pe_str = _format_num(pe_val, "{:.1f}")
    eps_str = _format_num(eps_val, "{:+.1f}", "%")

    if signal_type == "BUY":
        stop_loss_val = _safe_float(event.get("stop_loss"), 0.0)
        stop_loss_str = _format_num(stop_loss_val, "{:,.1f}")
        
        return f"""🟢 <b>[TÍN HIỆU MUA CHÍNH THỨC] #{ticker}</b>
⏰ <i>Thời gian: {time_str}</i>

💰 <b>Giá Mua:</b> {price_str} VNĐ
🛑 <b>Cắt lỗ (Stoploss 2xATR):</b> {stop_loss_str} VNĐ

⚙️ <b>Chỉ báo Kỹ thuật (TA):</b>
  • EMA20: {ta.get('EMA20_Status', 'N/A')}
  • RSI(14): {ta.get('RSI', 'N/A')} (Chuẩn tích lũy)
  • Vol Ratio: {ta.get('Volume_Ratio', 'N/A')}x SMA20 (Bùng nổ)

📊 <b>Nền tảng Doanh nghiệp (FA):</b>
  • ROE: {roe_str} | P/E: {pe_str} | Tăng trưởng EPS: {eps_str}

🎯 <b>Khuyến nghị:</b> Đạt đủ điều kiện. Xuống tiền giải ngân theo tỷ trọng quản trị rủi ro."""

    elif signal_type == "WATCH":
        return f"""🟡 <b>[CẢNH BÁO SỚM - RÌNH LỆNH] #{ticker}</b>
⏰ <i>Thời gian: {time_str}</i>

💰 <b>Giá Hiện tại:</b> {price_str} VNĐ

⚙️ <b>Trạng thái Kỹ thuật (TA):</b>
  • EMA20: {ta.get('EMA20_Status', 'N/A')} (Xu hướng tốt)
  • RSI(14): {ta.get('RSI', 'N/A')} (Động lượng khỏe)
  • Vol Ratio: {ta.get('Volume_Ratio', 'N/A')}x SMA20 <i>(Cần >= 1.2x)</i>

📊 <b>Nền tảng Doanh nghiệp (FA):</b>
  • ROE: {roe_str} | P/E: {pe_str} | EPS: {eps_str}

💡 <b>Ghi chú:</b> {event.get('note', 'Mã tích lũy đẹp, chờ dòng tiền xác nhận để MUA.')}
🎯 <b>Khuyến nghị:</b> Đưa vào Watchlist rình lệnh. Mua ngay khi Vol bùng nổ trong phiên."""

    elif signal_type == "SELL":
        pnl_raw = _safe_float(event.get("pnl_pct"), 0.0)
        
        # Xử lý an toàn đơn vị % PnL (tránh nhảy +97563.6%)
        if abs(pnl_raw) > 500:
            pnl_val = pnl_raw / 1000.0  # Chuẩn hóa nếu lệch đơn vị nghìn đồng
        else:
            pnl_val = pnl_raw

        pnl_icon = "🚀 +" if pnl_val >= 0 else "🔻 "
        entry_price_str = _format_num(event.get("entry_price"), "{:,.1f}")

        return f"""🔴 <b>[TÍN HIỆU BÁN / ĐÓNG VỊ THẾ] #{ticker}</b>
⏰ <i>Thời gian: {time_str}</i>

💰 <b>Giá Bán:</b> {price_str} VNĐ (Giá mua: {entry_price_str})
📈 <b>Hiệu suất (P&L):</b> {pnl_icon}{pnl_val:.1f}%

⚠️ <b>Lý do Bán:</b> {event.get('sell_reason', 'Chốt lời/Cắt lỗ theo kỷ luật')}

🎯 <b>Khuyến nghị:</b> Thực hiện bán chốt lời hoặc cắt lỗ theo đúng nguyên tắc quản trị."""

    return f"ℹ️ <b>[{signal_type}] #{ticker}</b> - Giá: {price_str}"


# ----------------------------------------------------------------------------
# 3. Hàm Xử lý Chính (Main Processing)
# ----------------------------------------------------------------------------
def process_signals(raw_events: list[dict], history_path: str | Path = DEFAULT_SIGNAL_HISTORY_PATH) -> list[dict]:
    """Lọc danh sách sự kiện từ TA, trả về danh sách tín hiệu hợp lệ sẵn sàng gửi Telegram."""
    history = load_signal_history(history_path)
    valid_signals = []

    for event in raw_events:
        # Kiểm tra chống trùng lặp
        if is_duplicate_signal(event, history):
            print(f"[SignalGen] Bỏ qua tín hiệu trùng: {event.get('ticker')} ({event.get('signal_type')})")
            continue

        # Tạo nội dung tin nhắn Telegram
        event["formatted_message"] = format_telegram_message(event)
        valid_signals.append(event)
        history.append(event)

    if valid_signals:
        save_signal_history(history, history_path)
        print(f"[SignalGen] Đã xử lý & lưu {len(valid_signals)} tín hiệu mới.")

    return valid_signals