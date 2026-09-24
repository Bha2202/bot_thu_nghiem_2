import os
import html
import json
import sqlite3
import logging
import concurrent.futures  
from datetime import datetime, timedelta, date
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
import asyncio

import os

# Khai báo đường dẫn lưu trữ file cảnh báo giá
ALERTS_PATH = os.path.join(os.path.dirname(__file__), "price_alerts.json")

import pandas as pd
import ta
import requests
from vnstock.api.quote import Quote

from stock_bot.chart import generate_candlestick_chart
from stock_bot.data_pipeline.storage.historical_store import HistoricalStore

# Import các hàm và hằng số chuẩn từ file strategies/ta_strategy.py
from strategies.ta_strategy import (
    ta_load_price_history_realtime,
    ta_compute_indicators,
    VOLUME_SPIKE_RATIO,
    RSI_BUY_MIN,
    RSI_BUY_MAX,
    DEFAULT_WATCH_LIST_PATH,
)

# Import hàm lấy giá real-time đã tối ưu
try:
    from data.fetcher_price import get_current_price
except ImportError:
    try:
        from fetcher_price import get_current_price
    except ImportError:
        get_current_price = None

logger = logging.getLogger(__name__)

# Đường dẫn lưu trữ dữ liệu
DATA_DIR = "data"
WATCH_LIST_PATH = os.path.join(DATA_DIR, "watch_list.json")
TRADE_HISTORY_PATH = os.path.join(DATA_DIR, "trade_history.json")
MARKET_DB_PATH = os.path.join(DATA_DIR, "market_data.db")
SIGNALS_PATH = os.path.join(DATA_DIR, "signals.json")
POSITIONS_PATH = os.path.join(DATA_DIR, "positions.json")

SSI_HEADERS = {"Accept": "application/json", "User-Agent": "Mozilla/5.0"}

# ----------------------------------------------------
# HELPER CHUẨN HÓA VÀ ÉP KIỂU AN TOÀN
# ----------------------------------------------------
def _safe_float(val, default=0.0):
    """Tránh crash khi dữ liệu FA/TA là 'N/A' hoặc None"""
    if val is None or val == 'N/A' or pd.isna(val):
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _normalize_price(price: float) -> float:
    """Đảm bảo giá luôn ở đơn vị VNĐ đầy đủ (VD: 20.9 -> 20900)"""
    p = _safe_float(price, 0.0)
    if 0 < p < 1000:
        return p * 1000.0
    return p


# ----------------------------------------------------
# 1. HÀM TRUY XUẤT DỮ LIỆU CƠ BẢN (FA & COMPANY)
# ----------------------------------------------------
def get_company_info(ticker: str, current_price: float = 0) -> dict:
    """Lấy thông tin DN và tự tính Vốn hóa nếu API trả về 0 hoặc N/A."""
    ticker_upper = ticker.upper()
    sector = "Khác"
    comp_name = ticker_upper
    market_cap = 0

    # 1. THỬ LẤY TỪ SSI IBOARD
    try:
        url = f"https://iboard-api.ssi.com.vn/statistics/company/ssmi/company-profile?symbol={ticker_upper}&language=vn"
        r = requests.get(url, headers=SSI_HEADERS, timeout=5)
        if r.status_code == 200:
            data = r.json().get('data', {})
            if data:
                sector = data.get('sector') or data.get('industryName') or data.get('icbName') or 'Khác'
                comp_name = data.get('companyName', ticker_upper)
                
                # Lấy số cổ phiếu lưu hành (shares) hoặc marketCap
                raw_cap = _safe_float(data.get('marketCap') or data.get('listedValue', 0))
                market_cap = raw_cap / 1e9 if raw_cap > 0 else 0
    except Exception:
        pass

    # 2. DỰ PHÒNG VNS/TCBS NẾU SSI THIẾU NGÀNH HOẶC VỐN HÓA
    if sector in ['Khác', 'Chưa xác định', '', None] or market_cap == 0:
        try:
            from vnstock import Vnstock
            stock = Vnstock().stock(symbol=ticker_upper, source='TCBS')
            
            # Lấy ngành
            if sector in ['Khác', 'Chưa xác định', '', None]:
                profile = stock.company.profile()
                if profile is not None and not profile.empty:
                    row = profile.iloc[0]
                    sector = row.get('icb_name') or row.get('industryName') or row.get('industry') or 'Khác'
                    comp_name = row.get('organ_short_name') or comp_name

            # 🛑 3. TỰ TÍNH VỐN HÓA NẾU MẤT DỮ LIỆU: (Số lượng CP lưu hành * Giá hiện tại)
            if market_cap == 0 and current_price > 0:
                overview = stock.company.overview()
                if overview is not None and not overview.empty:
                    issue_shares = _safe_float(overview.iloc[0].get('issue_share', 0))
                    if issue_shares > 0:
                        # Vốn hóa (Tỷ VNĐ) = (Giá VNĐ * Số lượng CP) / 1 Tỷ
                        market_cap = (current_price * issue_shares) / 1_000_000_000
        except Exception:
            pass

    # 4. CHUẨN HÓA CHUỖI HIỂN THỊ TRÁNH N/A
    if market_cap > 0:
        market_cap_str = f"{market_cap:,.0f} Tỷ"
    else:
        market_cap_str = "Đang cập nhật"

    return {
        'name': comp_name,
        'exchange': 'HOSE',
        'sector': str(sector).strip(),
        'sub_sector': str(sector).strip(),
        'market_cap': market_cap,
        'market_cap_str': market_cap_str  # <--- Dùng biến này gửi Telegram
    }

def get_fa_data(ticker: str) -> dict:
    ticker_upper = ticker.upper()
    fa_result = {
        'roe': 'N/A',
        'pe': 'N/A',
        'eps_growth_yoy': 'N/A',
        'period': 'N/A',
        'sector': 'Chưa xác định'
    }

    json_path = "data/financial_data.json"

    # -------------------------------------------------------------
    # TẦNG 1: Đọc và quét chi tiết từ file JSON local
    # -------------------------------------------------------------
    if os.path.exists(json_path):
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if ticker_upper in data:
                    item = data[ticker_upper]
                    fa_result['sector'] = item.get('sector', 'Chưa xác định')
                    history = item.get('history', [])
                    
                    if history:
                        # Lấy period của kỳ mới nhất trong history
                        fa_result['period'] = history[-1].get('period', 'N/A')

                        # Duyệt ngược từ kỳ mới nhất về cũ nhất để vét dữ liệu Valid
                        for row in reversed(history):
                            # Lấy ROE
                            if fa_result['roe'] == 'N/A' and row.get('roe') is not None:
                                val = float(row['roe'])
                                fa_result['roe'] = round(val * 100, 1) if 0 < abs(val) < 2 else round(val, 1)

                            # Lấy P/E
                            if fa_result['pe'] == 'N/A' and row.get('pe') is not None:
                                fa_result['pe'] = round(float(row['pe']), 1)

                            # Lấy EPS Growth (Ưu tiên YoY, nếu không có lấy QoQ)
                            if fa_result['eps_growth_yoy'] == 'N/A':
                                eps_val = row.get('eps_growth_yoy') or row.get('eps_growth_qoq') or row.get('eps_growth')
                                if eps_val is not None:
                                    v_eps = float(eps_val)
                                    fa_result['eps_growth_yoy'] = round(v_eps * 100, 1) if 0 < abs(v_eps) < 2 else round(v_eps, 1)

                            if fa_result['roe'] != 'N/A' and fa_result['pe'] != 'N/A' and fa_result['eps_growth_yoy'] != 'N/A':
                                break
        except Exception as e:
            print(f"Lỗi đọc file JSON cho {ticker_upper}: {e}")

    # -------------------------------------------------------------
    # TẦNG 2: Fallback API TCBS Realtime (Lấy bổ sung nếu còn thiếu)
    # -------------------------------------------------------------
    if fa_result['roe'] == 'N/A' or fa_result['pe'] == 'N/A' or fa_result['eps_growth_yoy'] == 'N/A':
        try:
            # API 1: Overview
            url_overview = f"https://apipub.tcbs.com.vn/tsci/v1/company/overview?ticker={ticker_upper}"
            r_ov = requests.get(url_overview, headers={"User-Agent": "Mozilla/5.0"}, timeout=3)
            
            if r_ov.status_code == 200:
                res_ov = r_ov.json()
                
                # Cập nhật Kỳ (Period) nếu chưa có
                if fa_result['period'] == 'N/A':
                    q = res_ov.get("quarter")
                    y = res_ov.get("year")
                    if q and y:
                        fa_result['period'] = f"{y}-Q{q}"
                    elif y:
                        fa_result['period'] = f"{y}-Năm"

                if fa_result['roe'] == 'N/A' and res_ov.get("roe") is not None:
                    v = float(res_ov["roe"])
                    fa_result['roe'] = round(v * 100, 1) if 0 < abs(v) < 2 else round(v, 1)

                if fa_result['pe'] == 'N/A' and res_ov.get("pe") is not None:
                    fa_result['pe'] = round(float(res_ov["pe"]), 1)

            # API 2: Indicators (Lấy chuyên biệt chỉ số Tăng trưởng EPS/ROE chuẩn YoY)
            url_ind = f"https://apipub.tcbs.com.vn/tsci/v1/financial-indicators?ticker={ticker_upper}&period=quarter"
            r_ind = requests.get(url_ind, headers={"User-Agent": "Mozilla/5.0"}, timeout=3)
            if r_ind.status_code == 200:
                res_ind = r_ind.json()
                if isinstance(res_ind, list) and len(res_ind) > 0:
                    latest = res_ind[0]
                    
                    if fa_result['period'] == 'N/A':
                        fa_result['period'] = f"{latest.get('year')}-Q{latest.get('quarter')}"
                    
                    if fa_result['eps_growth_yoy'] == 'N/A':
                        eps_growth = latest.get("epsGrowthYoY") or latest.get("epsGrowth")
                        if eps_growth is not None:
                            v = float(eps_growth)
                            fa_result['eps_growth_yoy'] = round(v * 100, 1) if 0 < abs(v) < 2 else round(v, 1)
        except Exception:
            pass

    return fa_result

# ----------------------------------------------------
# 2. HÀM QUẢN LÝ LỊCH SỬ GIAO DỊCH & VỊ THẾ
# ----------------------------------------------------
def load_trade_history() -> list:
    if os.path.exists(TRADE_HISTORY_PATH):
        try:
            with open(TRADE_HISTORY_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return []


def save_trade_history(history: list):
    os.makedirs(os.path.dirname(TRADE_HISTORY_PATH), exist_ok=True)
    with open(TRADE_HISTORY_PATH, 'w', encoding='utf-8') as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def get_active_trade(ticker: str) -> dict:
    history = load_trade_history()
    for t in history:
        if t.get('ticker') == ticker.upper() and t.get('status') == 'OPEN':
            return t
    return None


def open_trade(ticker: str, price: float, stop_loss: float, take_profit: float, rr_ratio: float, entry_date: str):
    history = load_trade_history()
    ticker = ticker.upper()

    existing_trade = next((t for t in history if t.get('ticker') == ticker and t.get('status') == 'OPEN'), None)
    if existing_trade:
        return

    history.append({
        'ticker': ticker,
        'entry_price': _normalize_price(price),
        'entry_date': entry_date,
        'stop_loss': _normalize_price(stop_loss),
        'take_profit': _normalize_price(take_profit),
        'rr_ratio': rr_ratio,
        'status': 'OPEN'
    })
    save_trade_history(history)


def calc_trade_stats(ticker: str, entry_date: str, entry_price: float, current_price: float):
    t_plus = 0
    if os.path.exists(MARKET_DB_PATH):
        try:
            conn = sqlite3.connect(MARKET_DB_PATH)
            df = pd.read_sql_query("""
                SELECT DISTINCT date FROM historical_ohlcv
                WHERE UPPER(symbol) = UPPER(?) AND date >= ?
                ORDER BY date ASC
            """, conn, params=(ticker.upper(), entry_date))
            conn.close()
            t_plus = max(0, len(df) - 1)
        except Exception:
            pass

    norm_entry = _normalize_price(entry_price)
    norm_curr = _normalize_price(current_price)
            
    pnl_pct = ((norm_curr - norm_entry) / norm_entry) * 100 if norm_entry > 0 else 0.0
    return t_plus, round(pnl_pct, 2)


def get_position_info(ticker: str) -> str:
    ticker_upper = ticker.upper()
    positions_path = os.path.join(DATA_DIR, "positions.json")
    
    if not os.path.exists(positions_path):
        return "\n\n📌 <b>VỊ THẾ TÀI KHOẢN:</b> Chưa sở hữu"
        
    try:
        with open(positions_path, "r", encoding="utf-8") as f:
            positions = json.load(f)
            
        pos_data = None
        if isinstance(positions, dict):
            pos_data = positions.get(ticker_upper)
        elif isinstance(positions, list):
            for p in positions:
                if isinstance(p, dict) and p.get("ticker", "").upper() == ticker_upper:
                    pos_data = p
                    break
                    
        if pos_data:
            qty = pos_data.get("quantity", pos_data.get("vol", 0))
            buy_price = _normalize_price(pos_data.get("buy_price", pos_data.get("entry_price", 0)))
            
            current_price = buy_price
            if get_current_price:
                try:
                    p = get_current_price(ticker_upper)
                    if p > 0:
                        current_price = _normalize_price(p)
                except Exception:
                    pass
            
            pnl_pct = ((current_price - buy_price) / buy_price) * 100 if buy_price > 0 else 0.0
            pnl_icon = "🟢" if pnl_pct >= 0 else "🔴"
            
            return (
                f"\n\n📌 <b>VỊ THẾ ĐANG NẮM GIỮ:</b>\n"
                f"• Khối lượng: <b>{qty:,}</b> CP\n"
                f"• Giá vốn: <b>{buy_price:,.0f}</b> VNĐ\n"
                f"• Giá hiện tại: <b>{current_price:,.0f}</b> VNĐ\n"
                f"• Lãi/Lỗ hiện tại: {pnl_icon} <b>{pnl_pct:+.2f}%</b>"
            )
    except Exception as e:
        logger.warning(f"Lỗi đọc vị thế cho {ticker_upper}: {e}")
        
    return "\n\n📌 <b>VỊ THẾ TÀI KHOẢN:</b> Chưa sở hữu"

# ----------------------------------------------------
# 3. LẤY DỮ LIỆU GIÁ & TÍNH TOÁN KĨ THUẬT
# ----------------------------------------------------
def get_stock_dataframe(ticker: str) -> pd.DataFrame:
    ticker = ticker.upper().strip()
    df = pd.DataFrame()

    try:
        store = HistoricalStore()
        raw_data = store.get_history(ticker)
        store.close()
        if raw_data:
            df = pd.DataFrame(raw_data, columns=["ticker", "date", "open", "high", "low", "close", "volume"])
            df['date'] = pd.to_datetime(df['date'])
            df = df.sort_values('date').reset_index(drop=True)
    except Exception:
        pass

    if df.empty or len(df) < 20:
        try:
            end_date = datetime.now().strftime('%Y-%m-%d')
            start_date = (datetime.now() - timedelta(days=150)).strftime('%Y-%m-%d')
            q = Quote(symbol=ticker, source='VCI')
            df_raw = q.history(start=start_date, end=end_date)
            
            if df_raw is not None and not df_raw.empty:
                df = df_raw.copy()
                date_col = 'time' if 'time' in df.columns else 'date'
                df['date'] = pd.to_datetime(df[date_col])
                df = df.sort_values('date').reset_index(drop=True)
        except Exception:
            return pd.DataFrame()

    if not df.empty and 'close' in df.columns:
        df['open'] = df['open'].apply(_normalize_price)
        df['high'] = df['high'].apply(_normalize_price)
        df['low'] = df['low'].apply(_normalize_price)
        df['close'] = df['close'].apply(_normalize_price)
        # ĐÃ BỎ GHI ĐÈ GIÁ REALTIME VÀO NẾN CUỐI CỦA DATAFRAME NÀY
        # (Chỉ dùng cho biểu đồ/chart, giữ nguyên giá đóng cửa đã chốt trong DB)

    return df


def calc_smartscore(df: pd.DataFrame, fa_data: dict) -> tuple:
    latest = df.iloc[-1]

    rsi_val = _safe_float(latest.get('rsi14'), 50.0)
    rsi_score = min(rsi_val, 100)
    
    ema20_val = _safe_float(latest.get('ema20'), 0)
    ema50_val = _safe_float(latest.get('ema50'), 0)
    ema_score = 100 if ema20_val > ema50_val else 30
    
    vol_ratio = _safe_float(latest.get('volume_ratio'), 1.0)
    vol_score = min(vol_ratio * 50, 100)
    dong_luong = int(rsi_score * 0.4 + ema_score * 0.4 + vol_score * 0.2)

    if fa_data:
        roe = _safe_float(fa_data.get('roe', fa_data.get('ROE', 0)))
        roe_score = min(roe * 2, 100)
        eps_growth = _safe_float(fa_data.get('eps_growth_yoy', fa_data.get('EPS_growth_yoy', 0)))
        eps_score = min(max(eps_growth, 0), 100)
        chat_luong = int(roe_score * 0.5 + eps_score * 0.5)

        pe = _safe_float(fa_data.get('pe', fa_data.get('PE', 15)), 15.0)
        dinh_gia = max(0, int(100 - pe * 2)) if pe > 0 else 50
    else:
        chat_luong = 50
        dinh_gia = 50

    tong = int(dinh_gia * 0.3 + chat_luong * 0.35 + dong_luong * 0.35)
    return dinh_gia, chat_luong, dong_luong, tong


import sqlite3

def analyze_stock_signal(ticker: str, total_capital: float = 100_000_000) -> dict:
    """Hàm phân tích tổng hợp: Đã tối ưu % NAV và lọc kèo thối R:R < 1.0"""
    try:
        ticker = ticker.upper()

        # -----------------------------------------------------------------
        # 0. TRUY VẤN TRỰC TIẾP GIÁ ĐÓNG CỬA & NGÀY MỚI NHẤT TRONG MARKET_DATA.DB
        # -----------------------------------------------------------------
        db_price = None
        db_latest_date = None
        try:
            with sqlite3.connect("data/market_data.db") as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT close, date FROM historical_ohlcv WHERE symbol = ? ORDER BY date DESC LIMIT 1",
                    (ticker,)
                )
                row = cursor.fetchone()
                if row:
                    raw_db_price, db_latest_date = row[0], row[1]
                    db_price = raw_db_price * 1000 if 0 < raw_db_price < 2000 else raw_db_price
        except Exception as db_err:
            print(f"[DB ERROR] Không đọc được giá từ market_data.db: {db_err}")

        # 1. TẢI DỮ LIỆU TỪ LỊCH SỬ
        df_ta = ta_load_price_history_realtime(ticker)
        if df_ta is None or df_ta.empty or len(df_ta) < 60:
            return {"error": f"Không đủ dữ liệu phân tích cho mã <b>{ticker}</b>."}

        # 2. TÍNH CHỈ BÁO TECHNICAL
        df_ta = ta_compute_indicators(df_ta)
        row_ta, prev_ta = df_ta.iloc[-1], df_ta.iloc[-2]

        if db_price is not None:
            price = db_price
        else:
            raw_p = float(row_ta["close"])
            price = raw_p * 1000 if 0 < raw_p < 2000 else raw_p

        vol_sma = row_ta.get("volume_sma20", row_ta.get("vol_ma20", 0))
        
        # 🛑 BỘ LỌC THANH KHOẢN: Loại bỏ mã rác có GTGD < 1 Tỷ/ngày
        avg_daily_value = vol_sma * price
        if avg_daily_value < 1_000_000_000:
            return {"error": f"Mã <b>{ticker}</b> không đủ thanh khoản (>1 tỷ VNĐ/phiên)."}

        rsi_val = float(row_ta.get("rsi14", row_ta.get("rsi", 50)))
        vol_ratio_val = float(row_ta["volume"] / vol_sma) if vol_sma else 0.0
        ema20_val = float(row_ta.get("ema20", price))

        trend_ok = price > ema20_val > float(prev_ta.get("ema20", price))
        vol_ok = vol_ratio_val >= VOLUME_SPIKE_RATIO
        rsi_ok = RSI_BUY_MIN <= rsi_val <= RSI_BUY_MAX

        if trend_ok and vol_ok and rsi_ok:
            signal_type = 'MUA'
            trend_str = 'TĂNG / TRÊN EMA20'
        else:
            signal_type = 'BÁN' if price < ema20_val else 'THEO DÕI'
            trend_str = 'GIẢM / TÍCH LŨY'

        # 3. LẤY DATAFRAME TÍNH SMARTSCORE & R:R THỰC TẾ
        df = get_stock_dataframe(ticker)
        if df.empty:
            df = df_ta
        else:
            df['ema20'] = ta.trend.ema_indicator(df['close'], window=20)
            df['ema50'] = ta.trend.ema_indicator(df['close'], window=50)
            df['rsi14'] = ta.momentum.rsi(df['close'], window=14)
            df['atr14'] = ta.volatility.average_true_range(df['high'], df['low'], df['close'], window=14)
            df['vol_ma20'] = df['volume'].rolling(20).mean()
            df['volume_ratio'] = df['volume'] / df['vol_ma20']
            df['resist_20'] = df['high'].rolling(20).max().shift(1)

        latest = df.iloc[-1]
        atr = _safe_float(latest.get('atr14'), price * 0.02)
        resist = _normalize_price(latest.get('resist_20')) if pd.notna(latest.get('resist_20')) else price * 1.12

        # CẮT LỖ VÀ MỤC TIÊU THEO CẢN THỰC TẾ
        stop_loss = max(price - (1.5 * atr), price * 0.90)
        risk = max(price - stop_loss, price * 0.01)
        reward = max(resist - price, price * 0.03)
        rr_ratio = reward / risk if risk > 0 else 0

        # 🛑 LỌC KÈO THỐI: Nếu Risk/Reward < 1.0 -> Tự động chặn tín hiệu MUA
        if rr_ratio < 1.0 and signal_type == 'MUA':
            signal_type = 'THEO DÕI'
            trend_str += ' (Bỏ qua: R:R < 1.0)'

        # LẤY ĐÚNG NGÀY CHỐT PHIÊN TỪ CSDL MARKET_DATA.DB
        if db_latest_date:
            last_row_date = pd.to_datetime(db_latest_date)
        else:
            last_row_date = pd.to_datetime(row_ta['date']) if 'date' in row_ta else pd.Timestamp.now()

        latest_date_str = last_row_date.strftime('%d/%m/%Y')
        latest_db_date_format = last_row_date.strftime('%Y-%m-%d')

        company = get_company_info(ticker, current_price=price)
        fa_data = get_fa_data(ticker)
        dinh_gia, chat_luong, dong_luong, score_tong = calc_smartscore(df, fa_data)

        # -----------------------------------------------------------------
        # 4. TÍNH VỊ THẾ KHUYẾN NGHỊ (CHUẨN HÓA % NAV - KHÔNG DÙNG CP LẺ)
        # -----------------------------------------------------------------
        sl_pct_val = abs((stop_loss / price - 1) * 100)
        
        if sl_pct_val > 0:
            raw_nav_pct = (2.0 / sl_pct_val) * 100
        else:
            raw_nav_pct = 0.0

        final_nav_pct = round(min(raw_nav_pct, 20.0), 1)

        if signal_type == 'MUA':
            position_recommendation = f"🟢 Tỷ trọng khuyến nghị: <b>{final_nav_pct}% NAV</b>"
        elif signal_type == 'THEO DÕI':
            if rr_ratio < 1.0:
                position_recommendation = f"⚪ Tỷ trọng dự kiến: <b>{final_nav_pct}% NAV</b> (Bỏ qua: R:R < 1.0)"
            else:
                position_recommendation = f"⚪ Tỷ trọng dự kiến: <b>{final_nav_pct}% NAV</b>"
        else:
            position_recommendation = "🔴 Bán chốt lời / Hạ tỷ trọng"

        # -----------------------------------------------------------------
        # 5. XỬ LÝ TRẠNG THÁI VỊ THẾ HIỆN TẠI
        # -----------------------------------------------------------------
        active_trade = get_active_trade(ticker)

        if signal_type == 'MUA' and not active_trade:
            open_trade(ticker, price, stop_loss, resist, rr_ratio, latest_db_date_format)
            active_trade = get_active_trade(ticker)

        t_plus, pnl_pct = (0, 0.0)
        entry_date_display = latest_date_str

        if active_trade:
            raw_entry = float(active_trade.get('entry_price', price))
            entry_price = raw_entry * 1000 if 0 < raw_entry < 2000 else raw_entry

            if entry_price > 0:
                pnl_pct = ((price - entry_price) / entry_price) * 100
            else:
                pnl_pct = 0.0

            active_trade['entry_price'] = entry_price
            active_trade['current_price'] = price
            active_trade['pnl_pct'] = pnl_pct

            entry_date_str = active_trade.get('entry_date', latest_db_date_format)
            entry_date_display = pd.to_datetime(entry_date_str).strftime('%d/%m/%Y')
            
            try:
                d_entry = pd.to_datetime(entry_date_str).date()
                d_current = pd.to_datetime(latest_db_date_format).date()
                t_plus = max(0, (d_current - d_entry).days)
            except Exception:
                t_plus = 0

        ema_status_str = "Giá > EMA20" if price > ema20_val else "Giá <= EMA20"

        return {
            "ticker": ticker,
            "company": company,
            "signal_type": signal_type,
            "trend_str": trend_str,
            "price": price,
            "latest_date": latest_date_str,
            "position_recommendation": position_recommendation,
            "entry_date": entry_date_display,
            "pnl_pct": round(pnl_pct, 2),
            "t_plus": t_plus,
            "active_trade": active_trade,
            "df": df,
            "smartscore": {
                "tong": score_tong,
                "dinh_gia": dinh_gia,
                "chat_luong": chat_luong,
                "dong_luong": dong_luong
            },
            "ta": {
                "rsi": round(rsi_val, 1),
                "vol_ratio": round(vol_ratio_val, 1),
                "ema_status": ema_status_str
            },
            "fa": fa_data,
            "stop_loss": round(stop_loss, 0),
            "take_profit": round(resist, 0),
            "rr_ratio": round(rr_ratio, 2)
        }
    except Exception as e:
        return {"error": f"Lỗi phân tích {ticker}: {str(e)}"}
# ----------------------------------------------------
# 4. BOT HANDLERS & TELEGRAM COMMANDS
# ----------------------------------------------------
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_msg = (
        "👋 Chào mừng đến với FinTech Stock Bot!\n\n"
        "Các lệnh hỗ trợ:\n"
        "/stock FPT — Tra cứu tín hiệu & phân tích 1 mã\n"
        "/today — Tín hiệu MUA/BÁN phát hiện hôm nay\n"
        "/watchlist — Danh sách cổ phiếu đạt chuẩn FA\n"
        "/portfolio — Danh mục tài khoản đang nắm giữ\n"
        "/help — Hướng dẫn sử dụng Bot"
    )
    await update.message.reply_text(welcome_msg)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start_command(update, context)


async def stock_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Xử lý lệnh /stock HPG -> Gửi giao diện Báo cáo đầy đủ như khi gõ HPG"""
    if context.args:
        ticker = context.args[0].upper().strip()
    else:
        await update.message.reply_text("⚠️ Vui lòng nhập mã. Ví dụ: <code>/stock HPG</code>", parse_mode="HTML")
        return

    await process_and_send_stock_signal(update, ticker)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Bắt tin nhắn tự do người dùng nhập (VD: gõ HPG hoặc hpg)"""
    text = update.message.text.strip().upper()
    if len(text) <= 5 and text.isalpha():
        await process_and_send_stock_signal(update, text)
    else:
        await update.message.reply_text("❓ Cú pháp không hợp lệ. Gõ mã cổ phiếu (VD: FPT) hoặc gõ /help.")


import html
import os
import re
import pandas as pd

from stock_bot.data_pipeline.main import get_realtime_market_store


async def process_and_send_stock_signal(update: Update, ticker: str):
    """Tạo BÁO CÁO HOÀN CHỈNH: Ảnh Chart + SmartScore + TA chuẩn + Quản trị 2x ATR + Vị thế"""

    msg = await update.message.reply_text(f"🔍 Đang tra cứu {ticker}...")
    res = analyze_stock_signal(ticker)

    if "error" in res:
        await msg.edit_text(res["error"], parse_mode="HTML")
        return

    if res["signal_type"] == "MUA":
        signal_emoji = "🟢 TÍN HIỆU MUA"
    elif res["signal_type"] == "BÁN":
        signal_emoji = "🔴 TÍN HIỆU BÁN"
    else:
        signal_emoji = "⚪ THEO DÕI"

    comp = res.get("company", {})
    score = res["smartscore"]
    ta_info = res["ta"]
    fa_info = res.get("fa", {})

    company_name = html.escape(str(comp.get("name", ticker)))

    # =========================================================
    # 1. XỬ LÝ NGÀNH
    # =========================================================

    sector_raw = (
        comp.get("sector")
        or fa_info.get("sector")
        or fa_info.get("industry")
        or "Khác"
    )

    if str(sector_raw).strip() in [
        "Chưa xác định",
        "nan",
        "None",
        ""
    ]:
        sector_raw = "Khác"

    sector_name = html.escape(str(sector_raw))

    # =========================================================
    # 2. XỬ LÝ VỐN HÓA
    # =========================================================

    cap_val = comp.get("market_cap", 0) or fa_info.get("market_cap", 0)

    if isinstance(cap_val, (int, float)) and cap_val > 0:
        cap_str = f"{cap_val:,.0f} tỷ"
    else:
        cap_str = html.escape(
            str(comp.get("market_cap_str", "Đang cập nhật"))
        )

    # =========================================================
    # 3. GIÁ ĐÓNG CỬA
    # =========================================================

    price_nghin = res["price"] / 1000

    # =========================================================
    # 3.1. LẤY GIÁ REALTIME - CHỈ ĐỂ HIỂN THỊ
    # KHÔNG ĐỤNG VÀO CÁC PHÉP TÍNH BÊN DƯỚI
    # =========================================================

    realtime_price = None
    realtime_time = None

    try:
        realtime_store = get_realtime_market_store()

        if realtime_store is not None:
            realtime_data = realtime_store.get_latest(ticker)

            if realtime_data:
                realtime_price = realtime_data.get("price")
                realtime_time = realtime_data.get("timestamp")
            print(
            f"[DEBUG TIMESTAMP] "
            f"price={realtime_price} | "
            f"timestamp={realtime_time} | "
            f"type={type(realtime_time)}"
)
    except Exception as e:
        logger.warning(
            f"⚠️ Không lấy được giá realtime {ticker}: {e}"
        )

    # Chuẩn hóa giá realtime chỉ để hiển thị

    if realtime_price is not None:
        try:
            realtime_price = float(realtime_price)

            if 0 < realtime_price < 2000:
                realtime_price_display = realtime_price * 1000
            else:
                realtime_price_display = realtime_price

        except Exception:
            realtime_price_display = None
    else:
        realtime_price_display = None

    # Format thời gian cập nhật
    realtime_time_display = None

    if realtime_time:
        try:

            dt = pd.to_datetime(realtime_time, utc=True)
            # Chuyển UTC -> giờ Việt Nam (UTC+7)
            dt = dt.tz_convert("Asia/Ho_Chi_Minh")

            realtime_time_display = dt.strftime(
                "%H:%M:%S %d/%m/%Y"
            )

        except Exception:
            realtime_time_display = str(realtime_time)

    if realtime_price_display is not None:
        realtime_price_text = (
            f"<b>{realtime_price_display:,.0f} đ</b>"
        )
    else:
        realtime_price_text = "<i>Chưa có dữ liệu</i>"

    if realtime_time_display:
        realtime_time_text = (
            f"<code>{html.escape(realtime_time_display)}</code>"
        )
    else:
        realtime_time_text = "<i>Chưa có dữ liệu</i>"

    # =========================================================
    # 4. HÀM XỬ LÝ DẤU < >
    # =========================================================

    def sanitize_tg_html(text):
        if not text:
            return ""

        text = str(text)

        text = text.replace(
            "<b>",
            "__B_OPEN__"
        ).replace(
            "</b>",
            "__B_CLOSE__"
        )

        text = text.replace(
            "<code>",
            "__CODE_OPEN__"
        ).replace(
            "</code>",
            "__CODE_CLOSE__"
        )

        text = html.escape(text)

        text = text.replace(
            "__B_OPEN__",
            "<b>"
        ).replace(
            "__B_CLOSE__",
            "</b>"
        )

        text = text.replace(
            "__CODE_OPEN__",
            "<code>"
        ).replace(
            "__CODE_CLOSE__",
            "</code>"
        )

        return text

    trend_clean = sanitize_tg_html(
        res.get("trend_str", "")
    )

    pos_rec_clean = sanitize_tg_html(
        res.get(
            "position_recommendation",
            "Theo dõi tích lũy"
        )
    )

    ema_status_clean = sanitize_tg_html(
        ta_info.get("ema_status", "")
    )

    # =========================================================
    # DỮ LIỆU ĐỊNH DẠNG CHUẨN GIAO DIỆN
    # =========================================================

    caption_text = (
        f"📊 <b>{res['ticker']} - {company_name} "
        f"({comp.get('exchange', 'HOSE')})</b>\n"

        f"📅 Chốt phiên ngày: "
        f"<code>{res['latest_date']}</code>\n"

        f"-----------------------------------\n"

        f"💰 Giá đóng cửa: "
        f"<b>{price_nghin:,.2f}</b> "
        f"(Tương đương <b>{res['price']:,.0f} đ</b>)\n"

        f"⚡ Giá hiện tại: "
        f"{realtime_price_text}\n"

        f"🕐 Cập nhật lúc: "
        f"{realtime_time_text}\n"

        f"Khuyến nghị: <b>{signal_emoji}</b>\n"

        f"• Xu hướng: {trend_clean}\n"

        f"• Vị thế khuyến nghị: "
        f"{pos_rec_clean}\n\n"

        f"🟣 <b>ĐIỂM SMARTSCORE: "
        f"{score.get('tong', 'N/A')}/100</b>\n"

        f"• Định giá: "
        f"{score.get('dinh_gia', 'N/A')} | "
        f"Chất lượng: "
        f"{score.get('chat_luong', 'N/A')} | "
        f"Động lượng: "
        f"{score.get('dong_luong', 'N/A')}\n"

        f"• Ngành: <code>{sector_name}</code> | "
        f"Vốn hóa: <code>{cap_str}</code>\n"
    )

    # =========================================================
    # 5. CHỈ SỐ TÀI CHÍNH
    # =========================================================

    roe = fa_info.get(
        "roe",
        fa_info.get("ROE", "N/A")
    )

    pe = fa_info.get(
        "pe",
        fa_info.get("PE", "N/A")
    )

    eps = fa_info.get(
        "eps_growth_yoy",
        fa_info.get("EPS_growth_yoy", "N/A")
    )

    period = fa_info.get(
        "period",
        fa_info.get("PERIOD", "")
    )

    period_str = (
        f" ({period})"
        if period and period != "N/A"
        else ""
    )

    caption_text += (
        f"• Chỉ số tài chính{period_str}: "
        f"ROE <code>{roe}%</code> | "
        f"P/E <code>{pe}</code> | "
        f"Tăng trưởng EPS <code>{eps}%</code>\n"
    )

    # =========================================================
    # 6. PHÂN TÍCH KỸ THUẬT & QUẢN TRỊ RỦI RO
    # =========================================================

    sl_pct = (
        (res["stop_loss"] / res["price"] - 1)
        * 100
    )

    tp_pct = (
        (res["take_profit"] / res["price"] - 1)
        * 100
    )

    caption_text += (
        f"\n📈 <b>Phân tích kỹ thuật (TA):</b>\n"

        f"• RSI(14): "
        f"<code>{ta_info['rsi']}</code> | "
        f"Khối lượng: "
        f"<code>{ta_info['vol_ratio']}x MA20</code>\n"

        f"• Trạng thái EMA: "
        f"{ema_status_clean}\n\n"

        f"🛡 <b>Quản trị vị thế (2x ATR):</b>\n"

        f"• Cắt lỗ động: "
        f"<code>{res['stop_loss']:,.0f} VNĐ</code> "
        f"({sl_pct:.1f}%)\n"

        f"• Chốt lời kỳ vọng: "
        f"<code>{res['take_profit']:,.0f} VNĐ</code> "
        f"(+{tp_pct:.1f}%)\n"

        f"• Tỷ lệ Risk/Reward: "
        f"<code>1 : {res['rr_ratio']}</code>\n"
    )

    # =========================================================
    # 7. VỊ THẾ TÀI KHOẢN
    # GIỮ NGUYÊN
    # =========================================================

    active_trade = res.get("active_trade")

    if active_trade:

        raw_entry = float(
            active_trade.get("entry_price", 0)
        )

        entry_price = (
            raw_entry * 1000
            if 0 < raw_entry < 2000
            else raw_entry
        )

        volume = active_trade.get("volume", 100)

        curr_price = res["price"]

        pnl_curr = (
            ((curr_price - entry_price) / entry_price) * 100
            if entry_price > 0
            else 0.0
        )

        pnl_icon = "🟢" if pnl_curr >= 0 else "🔴"
        pnl_sign = "+" if pnl_curr >= 0 else ""

        caption_text += (
            f"\n📌 <b>VỊ THẾ ĐANG NẮM GIỮ:</b>\n"

            f"• Khối lượng: "
            f"<b>{volume:,} CP</b>\n"

            f"• Giá vốn: "
            f"<b>{entry_price:,.0f} VNĐ</b>\n"

            f"• Giá hiện tại: "
            f"<b>{curr_price:,.0f} VNĐ</b>\n"

            f"• Lãi/Lỗ hiện tại: "
            f"{pnl_icon} "
            f"<b>{pnl_sign}{pnl_curr:.2f}%</b>"
        )

    else:
        caption_text += (
            f"\n📌 <b>VỊ THẾ TÀI KHOẢN:</b> "
            f"Chưa sở hữu"
        )

    # =========================================================
    # 8. GỬI ẢNH + CAPTION
    # =========================================================

    chart_file = None

    try:

        chart_file = generate_candlestick_chart(
            res["df"],
            ticker
        )

        with open(chart_file, "rb") as photo:

            await update.message.reply_photo(
                photo=photo,
                caption=caption_text,
                parse_mode="HTML"
            )

        await msg.delete()

    except Exception as e:

        logger.error(
            f"Lỗi gửi đồ thị mã {ticker}: {e}"
        )

        try:

            await msg.edit_text(
                caption_text,
                parse_mode="HTML"
            )

        except Exception:

            plain_text = re.sub(
                r"<[^>]+>",
                "",
                caption_text
            )

            await update.message.reply_text(
                plain_text
            )

            try:
                await msg.delete()
            except Exception:
                pass

    finally:

        if chart_file and os.path.exists(chart_file):

            try:
                os.remove(chart_file)
            except Exception:
                pass
async def handle_button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Bắt và xử lý sự kiện khi người dùng bấm các nút Inline Keyboard."""
    query = update.callback_query
    await query.answer()

    data = query.data
    chat_id = query.message.chat_id

    if data.startswith("chart_"):
        ticker = data.split("_")[1]
        await query.edit_message_text(
            f"📈 <b>ĐỒ THỊ KỸ THUẬT MÃ {ticker}</b>\n"
            f"• Khung thời gian: Daily (D1)\n"
            f"• MA20: <code>21.0</code> | MA50: <code>20.2</code>\n"
            f"• Kháng cự gần nhất: <code>23.5</code>\n"
            f"• Hỗ trợ cứng: <code>20.5</code>\n\n"
            f"<i>(Hệ thống đang xuất ảnh Chart nến...)</i>",
            parse_mode="HTML"
        )

    elif data.startswith("fa_"):
        ticker = data.split("_")[1]
        await query.edit_message_text(
            f"📊 <b>SỨC MẠNH TÀI CHÍNH (FA) - MÃ {ticker}</b>\n"
            f"=====================================\n"
            f"• ROE TTM: <code>18.5%</code> (Đạt chuẩn CANSLIM > 15%)\n"
            f"• P/E: <code>12.4</code> | P/B: <code>1.6</code>\n"
            f"• Tăng trưởng LN Ròng Q1 YoY: <code>+24.5%</code> 🚀\n"
            f"• Nợ/Vốn CSH (D/E): <code>0.65</code> (An toàn < 1.2)\n"
            f"• Dòng tiền HĐKD (CFO): <b>Dương mạnh</b>\n"
            f"=====================================\n"
            f"🎯 <i>Đánh giá Lớp 2 FA: ĐẠT CHUẨN TĂNG TRƯỞNG</i>",
            parse_mode="HTML"
        )

    elif data.startswith("add_port_"):
        ticker = data.split("_")[1]
        POSITIONS_PATH_LOCAL = "data/positions.json"
        positions = []
        if os.path.exists(POSITIONS_PATH_LOCAL):
            try:
                with open(POSITIONS_PATH_LOCAL, "r", encoding="utf-8") as f:
                    positions = json.load(f)
            except Exception:
                positions = []

        if any(p.get("ticker") == ticker for p in positions):
            await query.message.reply_text(f"⚠️ Mã <b>{ticker}</b> đã có sẵn trong Danh mục của bạn!", parse_mode="HTML")
            return

        new_position = {
            "ticker": ticker,
            "buy_date": datetime.now().strftime("%Y-%m-%d"),
            "buy_price": 21500,
            "stop_loss": 20400,
            "chat_id": chat_id
        }
        positions.append(new_position)

        with open(POSITIONS_PATH_LOCAL, "w", encoding="utf-8") as f:
            json.dump(positions, f, ensure_ascii=False, indent=2)

        await query.message.reply_text(
            f"✅ Đã thêm mã <b>{ticker}</b> vào Danh mục <code>/portfolio</code> của bạn!\n"
            f"• Giá mua ghi nhận: <code>21,500 đ</code>\n"
            f"• Tự động Cắt lỗ tại: <code>20,400 đ</code>",
            parse_mode="HTML"
        )
# ====================================================
# PHẦN 2: LỆNH TODAYS, PORTFOLIO, WATCHLIST & UTILS
# ====================================================

import re

async def today_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Báo cáo lọc TODAY: Tự động giải thích lý do vì sao chưa cho điểm MUA."""
    await update.message.reply_text("⏳ Đang kích hoạt BỘ LỌC TA...")

    if not os.path.exists(DEFAULT_WATCH_LIST_PATH):
        await update.message.reply_text("⚠️ Chưa tìm thấy file <code>data/watch_list.json</code>!", parse_mode="HTML")
        return

    try:
        with open(DEFAULT_WATCH_LIST_PATH, "r", encoding="utf-8") as f:
            watch_list = json.load(f)

        rows_text = ""
        buy_count = 0
        total = len(watch_list)

        for item in watch_list:
            ticker = item["ticker"] if isinstance(item, dict) else item
            
            res = analyze_stock_signal(ticker)
            
            if "error" in res:
                clean_err = re.sub(r'<[^>]+>', '', str(res['error']))
                rows_text += f"• {ticker}: ⚠️ {clean_err}\n"
                continue

            signal_type = res.get("signal_type", "THEO DÕI")
            ta_info = res.get("ta", {})
            score_info = res.get("smartscore", {})
            score_total = score_info.get("tong", 0)
            rr_ratio = res.get("rr_ratio", 0)
            
            rsi_val = ta_info.get("rsi", "N/A")
            vol_ratio = ta_info.get("vol_ratio", "N/A")

            # CHỈ KHI HÀM ANALYZE CHO TÍN HIỆU "MUA"
            if signal_type == "MUA":
                buy_count += 1
                rows_text += f"🟢 {ticker}: ĐẠT MUA (RSI:{rsi_val} | Vol:{vol_ratio}x)\n"
            else:
                # KIỂM TRA LÝ DO VÌ SAO CHƯA CHO MUA DÙ TA ĐẸP
                reason = ""
                if score_total < 60:
                    reason = f"SmartScore thấp ({score_total}/100)"
                elif float(rr_ratio) < 1.5 if str(rr_ratio).replace('.','').isdigit() else False:
                    reason = f"Tỷ lệ R:R kém (1:{rr_ratio})"
                else:
                    reason = "Đang tích lũy/Chờ bứt phá"

                t_ok = "📈" if ta_info.get("trend_ok", True) else "📉"
                
                try:
                    v_ok = "🔊" if float(vol_ratio) >= 1.2 else "❌"
                except (ValueError, TypeError):
                    v_ok = "❌"

                try:
                    m_ok = "⚡" if 45 <= float(rsi_val) <= 68 else "❌"
                except (ValueError, TypeError):
                    m_ok = "❌"

                # In thêm lý do vướng bộ lọc ở cuối dòng
                rows_text += f"• {ticker}: [Trend:{t_ok} Vol:{v_ok} RSI:{m_ok}] -> 💡 {reason}\n"

        report_text = f"Tổng số mã xét: {total}\n"
        report_text += f"🎯 Đạt CẢ 3 (MUA): {buy_count}/{total}\n\n"
        report_text += f"Chi tiết từng mã:\n{rows_text}"

        safe_report = html.escape(report_text)

        msg = (
            "📊 <b>BÁO CÁO BỘ LỌC TA (TODAY)</b>\n"
            "=====================================\n\n"
            f"<pre>{safe_report}</pre>\n\n"
            "💡 <i>Gõ <code>/stock &lt;Mã&gt;</code> hoặc nhập trực tiếp tên Mã để xem báo cáo chi tiết.</i>"
        )

        await update.message.reply_text(msg, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Lỗi khi chạy bộ lọc today: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Có lỗi khi lọc dữ liệu: <code>{str(e)}</code>", parse_mode="HTML")


def calculate_t_days(entry_date_str):
    """Tính số ngày nắm giữ (T+N)"""
    try:
        entry_date = datetime.strptime(str(entry_date_str).strip(), "%Y-%m-%d").date()
        today = datetime.now().date()
        delta = (today - entry_date).days
        return f"T+{delta}" if delta >= 0 else f"T{delta}"
    except Exception:
        return "N/A"


async def portfolio_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Quản lý danh mục tài khoản đang nắm giữ"""
    try:
        if not os.path.exists(POSITIONS_PATH):
            await update.message.reply_text("📭 Danh mục đầu tư hiện đang trống.")
            return

        with open(POSITIONS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)

        if not data:
            await update.message.reply_text("📭 Danh mục đầu tư hiện đang trống.")
            return

        items = []
        if isinstance(data, dict):
            for ticker, info in data.items():
                if isinstance(info, dict):
                    info["ticker"] = ticker
                    items.append(info)
        elif isinstance(data, list):
            items = data

        active_positions = [
            x for x in items 
            if str(x.get("status", "HOLD")).upper() in ["HOLD", "OPEN"]
        ]

        if not active_positions:
            await update.message.reply_text("📭 Hiện tại không có vị thế nào đang nắm giữ.")
            return

        msg = "💼 <b>DANH MỤC ĐANG NẮM GIỮ</b>\n" + "="*32 + "\n\n"

        for item in active_positions:
            ticker = str(item.get("ticker", "N/A")).upper()
            entry_date = item.get("entry_date", item.get("buy_date", "N/A"))
            volume = int(item.get("volume", 0))
            
            fmt_entry = _normalize_price(item.get("entry_price", item.get("buy_price", 0)))
            fmt_sl = _normalize_price(item.get("stop_loss", 0))
            fmt_tp = _normalize_price(item.get("take_profit", 0))

            # =========================================================
            # TRUY VẤN TRỰC TIẾP GIÁ ĐÓNG CỬA MỚI NHẤT TỪ MARKET_DATA.DB
            # =========================================================
            current_price = fmt_entry
            try:
                import sqlite3
                if os.path.exists("data/market_data.db"):
                    with sqlite3.connect("data/market_data.db") as conn:
                        cursor = conn.cursor()
                        cursor.execute(
                            "SELECT close FROM historical_ohlcv WHERE symbol = ? ORDER BY date DESC LIMIT 1",
                            (ticker,)
                        )
                        row = cursor.fetchone()
                        if row and row[0]:
                            raw_db_price = float(row[0])
                            # Ép đơn vị VNĐ giống hệt hàm analyze_stock_signal
                            current_price = raw_db_price * 1000 if 0 < raw_db_price < 2000 else raw_db_price
            except Exception as ex:
                logger.warning(f"Lỗi đọc DB cho {ticker}: {ex}")

            # Tính % Lãi/Lỗ
            pnl_pct = ((current_price - fmt_entry) / fmt_entry * 100) if fmt_entry > 0 else 0.0
            pnl_icon = "🟢" if pnl_pct >= 0 else "🔴"
            pnl_str = f"+{pnl_pct:.1f}%" if pnl_pct >= 0 else f"{pnl_pct:.1f}%"

            t_days = calculate_t_days(entry_date)

            msg += f"🟢 <b>{ticker}</b>\n"
            msg += f" • Ngày mua: {entry_date}\n"
            if volume > 0:
                msg += f" • Khối lượng: <b>{volume:,} CP</b>\n"
            msg += f" • Giá vào: <b>{fmt_entry:,.0f} đ</b>\n"
            msg += f" • Giá hiện tại: <b>{current_price:,.0f} đ</b>\n"
            msg += f" • Lãi/Lỗ: <b>{pnl_str}</b> {pnl_icon}\n"
            msg += f" • Số phiên: <code>T+{t_days}</code>\n"
            if fmt_sl > 0:
                msg += f" • Cắt lỗ: <code>{fmt_sl:,.0f} đ</code>\n"
            if fmt_tp > 0:
                msg += f" • Chốt lời: <code>{fmt_tp:,.0f} đ</code>\n"
            msg += "\n" + "-"*30 + "\n\n"

        keyboard = [
            [
                InlineKeyboardButton("➕ Thêm mã mới", callback_data="btn_add_pos"),
                InlineKeyboardButton("🗑 Xóa mã", callback_data="btn_del_pos")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(msg, parse_mode="HTML", reply_markup=reply_markup)

    except Exception as e:
        logger.error(f"Lỗi khi đọc portfolio: {e}", exc_info=True)
        await update.message.reply_text(f"⚠️ Có lỗi xảy ra: <code>{str(e)}</code>", parse_mode="HTML")
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

async def watchlist_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Xem danh sách Watchlist FA kèm Tên Ngành tự động và nút Thêm/Xóa mã."""
    if not os.path.exists(WATCH_LIST_PATH):
        await update.message.reply_text("⚠️ Chưa có file <code>data/watch_list.json</code>.", parse_mode="HTML")
        return
    try:
        with open(WATCH_LIST_PATH, "r", encoding="utf-8") as f:
            watch_data = json.load(f)

        # 🟢 NÚT BẤM KÉP ĐÃ ĐỔI CALLBACK DATA ĐỂ TRÁNH TRÙNG LỆNH
        keyboard = [
            [
                InlineKeyboardButton("➕ Thêm mã", callback_data="wl_add"),
                InlineKeyboardButton("🗑 Xóa mã", callback_data="wl_del")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        if not watch_data:
            await update.message.reply_text(
                "📭 Danh sách Watchlist hiện đang trống.\n\n💡 <i>Bấm nút bên dưới để thêm mã mới.</i>", 
                parse_mode="HTML",
                reply_markup=reply_markup
            )
            return

        reply = "📋 <b>DANH SÁCH CỔ PHIẾU ĐẠT CHUẨN CƠ BẢN (FA)</b>\n" + "="*30 + "\n"
        
        if isinstance(watch_data, list):
            reply += f"Tổng cộng: <b>{len(watch_data)}</b> mã chọn lọc.\n\n"
            
            # Hiển thị tối đa 15 mã đầu tiên
            for item in watch_data[:15]:
                if isinstance(item, str):
                    ticker = item.upper()
                    comp_info = get_company_info(ticker)
                    sector = comp_info.get('sector', 'Chưa xác định')
                    reply += f"• <b>{ticker}</b> | Ngành: <code>{html.escape(str(sector))}</code>\n"
                    
                elif isinstance(item, dict):
                    ticker = item.get('ticker', 'N/A').upper()
                    sector = item.get('sector')
                    
                    # Tự động gọi API bổ sung nếu ngành bị trống
                    if not sector or sector in ['Chưa rõ', 'Chưa xác định', 'Chưa phân ngành', '']:
                        comp_info = get_company_info(ticker)
                        sector = comp_info.get('sector', 'Chưa xác định')
                        
                    roe_val = item.get('roe', item.get('ROE', 'N/A'))
                    pe_val = item.get('pe', item.get('PE', 'N/A'))
                    
                    reply += f"• <b>{ticker}</b> | Ngành: <code>{html.escape(str(sector))}</code> | ROE: <code>{roe_val}%</code> | P/E: <code>{pe_val}</code>\n"

            if len(watch_data) > 15:
                reply += f"\n<i>...và {len(watch_data) - 15} mã khác.</i>"

            reply += "\n\n💡 <i>Bấm nút bên dưới để thêm hoặc xóa mã nhanh.</i>"

        await update.message.reply_text(reply, parse_mode="HTML", reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"Lỗi đọc Watchlist: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Lỗi đọc Watchlist: {e}", parse_mode="HTML")


# 🟢 1. Hàm xử lý sự kiện khi bấm nút ➕ Thêm mã hoặc 🗑 Xóa mã trên Watchlist
async def watchlist_button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Xử lý khi người dùng ấn nút ➕ Thêm mã hoặc 🗑 Xóa mã."""
    query = update.callback_query
    await query.answer()

    if query.data == "wl_add":
        msg = (
            "➕ <b>CÚ PHÁP THÊM MÃ VÀO WATCHLIST:</b>\n\n"
            "Hãy gõ lệnh: <code>/wladd &lt;Mã_Cổ_Phiếu&gt;</code>\n"
            "<i>Ví dụ:</i> <code>/wladd FPT</code> hoặc <code>/wladd SSI, VND, MWG</code>"
        )
        await query.message.reply_text(msg, parse_mode="HTML")

    elif query.data == "wl_del":
        msg = (
            "🗑 <b>CÚ PHÁP XÓA MÃ KHỎI WATCHLIST:</b>\n\n"
            "Hãy gõ lệnh: <code>/wldel &lt;Mã_Cổ_Phiếu&gt;</code>\n"
            "<i>Ví dụ:</i> <code>/wldel CAP</code> hoặc <code>/wldel MHC, SGH</code>"
        )
        await query.message.reply_text(msg, parse_mode="HTML")


# 🟢 2. Hàm xử lý lệnh /wladd (Thêm mã)
async def add_watchlist_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("⚠️ Cú pháp: <code>/wladd &lt;Mã&gt;</code> (Ví dụ: <code>/wladd FPT</code>)", parse_mode="HTML")
        return

    input_text = " ".join(context.args)
    raw_tickers = [t.strip().upper() for t in input_text.replace(',', ' ').split() if t.strip()]

    os.makedirs(os.path.dirname(WATCH_LIST_PATH), exist_ok=True)
    watch_data = []
    if os.path.exists(WATCH_LIST_PATH):
        try:
            with open(WATCH_LIST_PATH, "r", encoding="utf-8") as f:
                watch_data = json.load(f)
        except Exception:
            watch_data = []

    existing = set()
    for item in watch_data:
        t = item["ticker"].upper() if isinstance(item, dict) and "ticker" in item else str(item).upper()
        existing.add(t)

    added, exist_list = [], []
    for ticker in raw_tickers:
        if ticker in existing:
            exist_list.append(ticker)
        else:
            watch_data.append({"ticker": ticker})
            existing.add(ticker)
            added.append(ticker)

    with open(WATCH_LIST_PATH, "w", encoding="utf-8") as f:
        json.dump(watch_data, f, ensure_ascii=False, indent=2)

    msg = "✅ <b>CẬP NHẬT WATCHLIST SUCCESSFUL</b>\n\n"
    if added:
        msg += f"➕ Đã thêm: <code>{', '.join(added)}</code>\n"
    if exist_list:
        msg += f"ℹ️ Đã có sẵn: <code>{', '.join(exist_list)}</code>\n"
    msg += f"\n📋 Tổng số mã hiện tại: <b>{len(watch_data)}</b>"
    
    await update.message.reply_text(msg, parse_mode="HTML")


# 🟢 3. Hàm xử lý lệnh /wldel (Xóa mã)
async def del_watchlist_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("⚠️ Cú pháp: <code>/wldel &lt;Mã&gt;</code> (Ví dụ: <code>/wldel CAP</code>)", parse_mode="HTML")
        return

    input_text = " ".join(context.args)
    targets = [t.strip().upper() for t in input_text.replace(',', ' ').split() if t.strip()]

    if not os.path.exists(WATCH_LIST_PATH):
        await update.message.reply_text("⚠️ Watchlist trống!", parse_mode="HTML")
        return

    with open(WATCH_LIST_PATH, "r", encoding="utf-8") as f:
        watch_data = json.load(f)

    new_data, removed = [], []
    for item in watch_data:
        t = item["ticker"].upper() if isinstance(item, dict) and "ticker" in item else str(item).upper()
        if t in targets:
            removed.append(t)
        else:
            new_data.append(item)

    with open(WATCH_LIST_PATH, "w", encoding="utf-8") as f:
        json.dump(new_data, f, ensure_ascii=False, indent=2)

    msg = "🗑 <b>CẬP NHẬT XÓA WATCHLIST</b>\n\n"
    if removed:
        msg += f"➖ Đã xóa: <code>{', '.join(removed)}</code>\n"
    msg += f"\n📋 Tổng số mã còn lại: <b>{len(new_data)}</b>"
    
    await update.message.reply_text(msg, parse_mode="HTML")

async def sector_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Xử lý lệnh /sector — Phân tích sóng ngành chi tiết từng mã (Đa luồng)."""
    msg = await update.message.reply_text("⚡ Đang quét dữ liệu sóng ngành...")
    
    if not os.path.exists(DEFAULT_WATCH_LIST_PATH):
        await msg.edit_text("⚠️ Chưa tìm thấy file <code>data/watch_list.json</code>!", parse_mode="HTML")
        return

    try:
        with open(DEFAULT_WATCH_LIST_PATH, "r", encoding="utf-8") as f:
            watch_list = json.load(f)

        if not watch_list:
            await msg.edit_text("📭 Danh sách mã theo dõi trống.")
            return

        # 1. Lấy danh sách tất cả các mã cổ phiếu
        tickers = []
        for item in watch_list:
            if isinstance(item, str):
                tickers.append(item.upper())
            elif isinstance(item, dict) and item.get('ticker'):
                tickers.append(item.get('ticker').upper())

        tickers = list(set(tickers)) # Lọc trùng

        # 2. Hàm xử lý dữ liệu từng mã
        def process_single_stock(ticker):
            try:
                info = get_company_info(ticker)
                sec = info.get('sector', 'Khác')
                
                df = ta_load_price_history_realtime(ticker)
                if df.empty or len(df) < 20:
                    return None

                df = ta_compute_indicators(df)
                row, prev = df.iloc[-1], df.iloc[-2]

                p_curr = float(row['close'])
                p_prev = float(prev['close'])
                pct_change = ((p_curr - p_prev) / p_prev) * 100 if p_prev > 0 else 0.0

                rsi = float(row['rsi14'])
                vol_r = float(row['volume'] / row['volume_sma20']) if row['volume_sma20'] else 0.0
                ema20 = float(row['ema20'])

                is_buy = (p_curr > ema20 > float(prev['ema20'])) and (vol_r >= VOLUME_SPIKE_RATIO) and (RSI_BUY_MIN <= rsi <= RSI_BUY_MAX)

                return {
                    'ticker': ticker,
                    'sector': sec,
                    'pct_change': pct_change,
                    'is_buy': is_buy
                }
            except Exception:
                return None

        # 3. Chạy đa luồng song song
        loop = asyncio.get_running_loop()
        with concurrent.futures.ThreadPoolExecutor(max_workers=15) as executor:
            tasks = [loop.run_in_executor(executor, process_single_stock, t) for t in tickers]
            results = await asyncio.gather(*tasks)

        valid_results = [r for r in results if r is not None]

        # 4. Gom nhóm theo Ngành
        sector_groups = {}
        for r in valid_results:
            sec = r['sector']
            sector_groups.setdefault(sec, []).append(r)

        # 5. Tổng hợp dữ liệu từng Ngành
        sector_summary = []
        for sec, items in sector_groups.items():
            buy_signals = sum(1 for i in items if i['is_buy'])
            avg_change = sum(i['pct_change'] for i in items) / len(items) if items else 0.0
            
            sector_summary.append({
                'sector': sec,
                'total': len(items),
                'buy_signals': buy_signals,
                'avg_change': avg_change,
                'items': items
            })

        # Sắp xếp ngành ưu tiên: Số tín hiệu MUA > % Tăng giá TB
        sector_summary.sort(key=lambda x: (x['buy_signals'], x['avg_change']), reverse=True)

        # 6. Xuất báo cáo Telegram có liệt kê mã chi tiết
        report = "🌊 <b>PHÂN TÍCH SÓNG NGÀNH REALTIME</b>\n"
        report += f"📅 Cập nhật: <code>{datetime.now().strftime('%H:%M - %d/%m/%Y')}</code>\n"
        report += "="*32 + "\n\n"

        for s in sector_summary:
            chg_icon = "🟢" if s['avg_change'] >= 0 else "🔴"
            hot_icon = "🔥 " if s['buy_signals'] > 0 else "• "
            
            report += f"{hot_icon}<b>{html.escape(s['sector'])}</b> ({s['avg_change']:+.2f}% {chg_icon})\n"
            report += f" - Tín hiệu MUA: <b>{s['buy_signals']}/{s['total']}</b> mã\n"
            
            # Liệt kê chi tiết từng mã
            stock_list_str = []
            for item in s['items']:
                status_icon = "🟢" if item['is_buy'] else "⚪"
                stock_list_str.append(f"{status_icon} <b>{item['ticker']}</b> ({item['pct_change']:+.1f}%)")
            
            report += " - Danh sách: " + ", ".join(stock_list_str) + "\n\n"

        report += "💡 <i>Ghi chú: 🟢 Tín hiệu MUA | ⚪ Theo dõi/Chưa đạt</i>"
        await msg.edit_text(report, parse_mode="HTML")

    except Exception as e:
        logger.error(f"Lỗi lệnh /sector: {e}", exc_info=True)
        await msg.edit_text(f"❌ Có lỗi khi phân tích ngành: <code>{str(e)}</code>", parse_mode="HTML")


async def handle_text_ticker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Xử lý tin nhắn khi người dùng gõ trực tiếp mã cổ phiếu (VD: hpg, d2d, fpt)"""
    text = update.message.text.strip().upper()
    
    # ĐỔI .isalpha() THÀNH .isalnum() ĐỂ NHẬN CẢ CHỮ VÀ SỐ (NHƯ D2D, C32)
    if 3 <= len(text) <= 5 and text.isalnum():
        # Gọi trực tiếp quy trình tạo báo cáo đầy đủ (SmartScore + Chart + TA + FA)
        await process_and_send_stock_signal(update, text)
    else:
        await update.message.reply_text("❓ Lệnh không hợp lệ. Hãy gõ mã cổ phiếu (VD: FPT) hoặc gõ /help.")

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

async def check_single_alert(bot, alert: dict) -> bool:
    """Hàm kiểm tra 1 cảnh báo đơn lẻ. Trả về True nếu đã phát cảnh báo."""
    chat_id = alert.get("chat_id")
    ticker = alert.get("ticker", "").upper()
    op = alert.get("operator")
    target_p = alert.get("target_price", 0)

    curr_p = 0
    if get_current_price:
        try:
            curr_p = _normalize_price(get_current_price(ticker))
        except Exception:
            pass

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

    # Kiểm tra ngay lập tức xem giá hiện tại đã thỏa mãn chưa
    is_triggered = await check_single_alert(context.bot, new_alert)
    if is_triggered:
        return  # Nếu giá đã thỏa mãn ngay lập tức thì gửi tin nhắn báo động luôn và KHÔNG lưu nữa

    # Nếu chưa thỏa mãn thì lưu vào file để chờ JobQueue quét
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

                curr_p = 0
                if get_current_price:
                    try:
                        curr_p = _normalize_price(get_current_price(ticker))
                    except Exception:
                        pass

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

import json
import os
import pandas as pd
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CommandHandler, CallbackQueryHandler, ContextTypes

import os
import json
import logging
import pandas as pd
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler

logger = logging.getLogger(__name__)

POSITION_FILE = "data/positions.json"

# Tìm dòng này trong bot/handlers.py và sửa lại cho đủ 4 biến:
WAITING_TICKER, WAITING_PRICE, WAITING_VOLUME, WAITING_DATE = range(4)


# ==========================================
# ==========================================
# HÀM XỬ LÝ LƯU VÀ CẬP NHẬT FILE POSITIONS
# ==========================================
def save_position_to_file(ticker: str, new_price: float, new_volume: int, entry_date: str):
    """
    Lưu hoặc MUA THÊM vị thế:
    - Đã có mã: Cộng dồn Khối lượng + Tính Giá vốn trung bình trọng số (VWAP).
    - Chưa có mã: Tạo mới vị thế.
    """
    data = {}
    if os.path.exists(POSITION_FILE):
        try:
            with open(POSITION_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception:
            data = {}

    ticker = ticker.upper()

    if ticker in data:
        old_vol = int(data[ticker].get('volume', 0))
        raw_old_price = float(data[ticker].get('entry_price', 0))
        old_price = raw_old_price * 1000 if 0 < raw_old_price < 2000 else raw_old_price

        total_vol = old_vol + new_volume

        # Tính giá vốn trung bình trọng số (VWAP)
        if total_vol > 0:
            avg_price = ((old_vol * old_price) + (new_volume * new_price)) / total_vol
        else:
            avg_price = new_price

        data[ticker]['entry_price'] = round(avg_price, 2)
        data[ticker]['volume'] = total_vol
        data[ticker]['latest_add_date'] = entry_date
    else:
        data[ticker] = {
            "ticker": ticker,
            "entry_price": new_price,
            "volume": new_volume,
            "entry_date": entry_date,
            "status": "OPEN"
        }

    os.makedirs(os.path.dirname(POSITION_FILE), exist_ok=True)
    with open(POSITION_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)


def get_active_trade(ticker: str) -> dict:
    """Hàm bổ trợ lấy vị thế hiện tại (được gọi trong /stock)"""
    if not os.path.exists(POSITION_FILE):
        return None
    try:
        with open(POSITION_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        ticker = ticker.upper()
        if ticker in data:
            pos = data[ticker]
            raw_entry = float(pos.get('entry_price', 0))
            entry_price = raw_entry * 1000 if 0 < raw_entry < 2000 else raw_entry
            return {
                "ticker": ticker,
                "entry_price": entry_price,
                "volume": int(pos.get('volume', 0)),
                "entry_date": pos.get('entry_date', '')
            }
    except Exception as e:
        logger.error(f"Lỗi đọc vị thế {ticker}: {e}")
    return None


# ==========================================
# LỆNH /portfolio (CÓ NÚT TƯƠNG TÁC BÊN DƯỚI)
# ==========================================
async def portfolio_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Hiển thị danh mục tài khoản kèm 2 nút bấm thao tác ngay dưới tin nhắn"""
    if not os.path.exists(POSITION_FILE):
        report_text = "💼 <b>DANH MỤC ĐANG NẮM GIỮ</b>\n===================================\n\n<i>Chưa có vị thế nào trong danh mục.</i>"
    else:
        try:
            with open(POSITION_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception:
            data = {}

        if not data:
            report_text = "💼 <b>DANH MỤC ĐANG NẮM GIỮ</b>\n===================================\n\n<i>Chưa có vị thế nào trong danh mục.</i>"
        else:
            report_text = "💼 <b>DANH MỤC ĐANG NẮM GIỮ</b>\n===================================\n\n"
            for ticker, pos in data.items():
                raw_entry = float(pos.get('entry_price', 0))
                entry_price = raw_entry * 1000 if 0 < raw_entry < 2000 else raw_entry
                volume = int(pos.get('volume', 0))
                entry_date = pos.get('entry_date', 'N/A')

                # Lấy Giá hiện tại Realtime từ hàm phân tích (Đồng bộ 100% với lệnh /stock)
                curr_price = entry_price
                try:
                    res_stock = analyze_stock_signal(ticker)
                    if res_stock and "price" in res_stock and res_stock["price"] > 0:
                        curr_price = float(res_stock["price"])
                except Exception as ex:
                    logger.warning(f"Lỗi lấy giá realtime cho {ticker}: {ex}")
                pnl_pct = ((curr_price - entry_price) / entry_price * 100) if entry_price > 0 else 0.0
                pnl_icon = "🟢" if pnl_pct >= 0 else "🔴"

                report_text += (
                    f"🟢 <b>{ticker}</b>\n"
                    f"• Ngày mua: {entry_date}\n"
                    f"• Khối lượng: <b>{volume:,} CP</b>\n"
                    f"• Giá vào (Trung bình): <b>{entry_price:,.0f} đ</b>\n"
                    f"• Giá hiện tại: <b>{curr_price:,.0f} đ</b>\n"
                    f"• Lãi/Lỗ: <b>{pnl_pct:+.1f}%</b> {pnl_icon}\n"
                    f"-----------------------------------\n"
                )

    # Bàn phím đính kèm trực tiếp dưới tin nhắn
    keyboard = [
        [
            InlineKeyboardButton("➕ Thêm mã mới", callback_data="btn_add_pos"),
            InlineKeyboardButton("🗑 Xóa mã", callback_data="btn_del_pos")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(report_text, parse_mode="HTML", reply_markup=reply_markup)


# ==========================================
# FORM NHẬP THÊM VỊ THẾ 4 BƯỚC (CÓ NGÀY MUA)
# ==========================================
async def start_add_position(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    msg = "🔤 <b>Bước 1/4:</b> Nhập <b>Mã cổ phiếu</b> (VD: <code>HPG</code>):"
    if query:
        await query.answer()
        await query.message.reply_text(msg, parse_mode="HTML")
    else:
        await update.message.reply_text(msg, parse_mode="HTML")
    return WAITING_TICKER


async def receive_ticker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ticker = update.message.text.strip().upper()
    context.user_data['buy_ticker'] = ticker
    await update.message.reply_text(
        f"💵 <b>Bước 2/4:</b> Nhập <b>Giá mua</b> cho <b>{ticker}</b> (Đơn vị nghìn đồng, VD: <code>21.55</code>):",
        parse_mode="HTML"
    )
    return WAITING_PRICE


async def receive_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        price_val = float(update.message.text.strip().replace(',', '.'))
        context.user_data['buy_price'] = price_val * 1000 if price_val < 2000 else price_val
        await update.message.reply_text("📊 <b>Bước 3/4:</b> Nhập <b>Khối lượng (Số CP)</b> (VD: <code>1000</code>):", parse_mode="HTML")
        return WAITING_VOLUME
    except ValueError:
        await update.message.reply_text("⚠️ Giá mua không hợp lệ! Nhập lại (VD: <code>21.55</code>):", parse_mode="HTML")
        return WAITING_PRICE


async def receive_volume(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        volume = int(update.message.text.strip())
        context.user_data['buy_volume'] = volume

        # Tùy chọn chọn nhanh ngày hôm nay
        keyboard = [[InlineKeyboardButton("📅 Chọn Hôm nay", callback_data="date_today")]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            "📅 <b>Bước 4/4:</b> Nhập <b>Ngày mua</b> (Định dạng: <code>YYYY-MM-DD</code>, VD: <code>2026-09-20</code>):\n\n"
            "<i>Nhấn nút bên dưới nếu là giao dịch Hôm nay:</i>",
            parse_mode="HTML",
            reply_markup=reply_markup
        )
        return WAITING_DATE
    except ValueError:
        await update.message.reply_text("⚠️ Số lượng phải là số nguyên! Nhập lại (VD: <code>1000</code>):", parse_mode="HTML")
        return WAITING_VOLUME


async def receive_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
        entry_date = pd.Timestamp.now().strftime('%Y-%m-%d')
        msg_obj = query.message
    else:
        date_str = update.message.text.strip()
        if date_str.lower() in ['today', 'hom nay', 'hôm nay']:
            entry_date = pd.Timestamp.now().strftime('%Y-%m-%d')
        else:
            try:
                entry_date = pd.to_datetime(date_str).strftime('%Y-%m-%d')
            except Exception:
                await update.message.reply_text(
                    "⚠️ Ngày không hợp lệ! Vui lòng nhập định dạng <code>YYYY-MM-DD</code> (VD: <code>2026-09-20</code>):",
                    parse_mode="HTML"
                )
                return WAITING_DATE
        msg_obj = update.message

    ticker = context.user_data['buy_ticker']
    entry_price = context.user_data['buy_price']
    volume = context.user_data['buy_volume']

    save_position_to_file(ticker, entry_price, volume, entry_date)

    await msg_obj.reply_text(
        f"✅ <b>ĐÃ CẬP NHẬT VỊ THẾ {ticker}!</b>\n\n"
        f"• Mã: <b>{ticker}</b>\n"
        f"• Khối lượng: <b>{volume:,} CP</b>\n"
        f"• Giá mua: <b>{entry_price:,.0f} đ</b>\n"
        f"• Ngày mua: <b>{entry_date}</b>\n\n"
        f"Gõ <code>/portfolio</code> để xem chi tiết danh mục.",
        parse_mode="HTML"
    )
    context.user_data.clear()
    return ConversationHandler.END


async def cancel_add_position(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("❌ Đã hủy thao tác thêm vị thế.")
    return ConversationHandler.END


# ==========================================
# LỆNH /sell (HỖ TRỢ BÁN 1 PHẦN / BÁN HẾT)
# ==========================================
async def cmd_sell(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        await update.message.reply_text(
            "⚠️ <b>Cú pháp chưa đúng!</b>\n"
            "• Bán hết: <code>/sell HPG</code>\n"
            "• Bán 1 phần: <code>/sell HPG 10</code> (VD: Bán 10 CP)",
            parse_mode="HTML"
        )
        return

    ticker = args[0].upper()
    sell_vol = int(args[1]) if len(args) >= 2 and args[1].isdigit() else None

    if os.path.exists(POSITION_FILE):
        with open(POSITION_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)

        if ticker in data:
            current_vol = int(data[ticker].get('volume', 0))

            if sell_vol and 0 < sell_vol < current_vol:
                remaining_vol = current_vol - sell_vol
                data[ticker]['volume'] = remaining_vol
                with open(POSITION_FILE, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=4)

                await update.message.reply_text(
                    f"✂️ <b>ĐÃ BÁN BỚT {sell_vol:,} CP {ticker}!</b>\n"
                    f"• Khối lượng còn lại: <b>{remaining_vol:,} CP</b>",
                    parse_mode="HTML"
                )
            else:
                del data[ticker]
                with open(POSITION_FILE, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=4)

                await update.message.reply_text(f"✅ Đã xóa toàn bộ mã <b>{ticker}</b> khỏi danh mục!", parse_mode="HTML")
            return

    await update.message.reply_text(f"❌ Không tìm thấy mã <b>{ticker}</b> trong danh mục.", parse_mode="HTML")


async def handle_portfolio_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "btn_del_pos":
        await query.message.reply_text(
            "🗑 <b>XÓA MÃ KHỎI DANH MỤC:</b>\n"
            "Gõ lệnh: <code>/sell [MÃ]</code> (VD: <code>/sell HPG</code>)\n"
            "Hoặc bán bớt: <code>/sell [MÃ] [SL]</code> (VD: <code>/sell HPG 10</code>)",
            parse_mode="HTML"
        )


