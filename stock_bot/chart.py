import os
import matplotlib
matplotlib.use('Agg') # Đảm bảo chạy không cần giao diện đồ họa
import matplotlib.pyplot as plt
import mplfinance as mpf
import pandas as pd
import ta

def generate_candlestick_chart(df: pd.DataFrame, ticker: str) -> str:
    """Vẽ biểu đồ nến Candlestick + Khối lượng (Volume) + Đường EMA20/EMA50 chuẩn xác."""
    os.makedirs("temp", exist_ok=True)
    chart_path = f"temp/{ticker.upper()}_chart.png"
    
    chart_df = df.copy()

    # 1. Xử lý Index thời gian
    if 'date' in chart_df.columns:
        chart_df['date'] = pd.to_datetime(chart_df['date'])
        chart_df.set_index('date', inplace=True)
    
    # 2. Chuẩn hóa tên cột viết hoa cho mplfinance
    chart_df = chart_df.rename(columns={
        'open': 'Open',
        'high': 'High',
        'low': 'Low',
        'close': 'Close',
        'volume': 'Volume'
    })

    # Đảm bảo các cột bắt buộc có kiểu dữ liệu số (numeric)
    cols = ['Open', 'High', 'Low', 'Close', 'Volume']
    for col in cols:
        if col in chart_df.columns:
            chart_df[col] = pd.to_numeric(chart_df[col], errors='coerce')

    # Điền giá trị trống nếu có
    chart_df['Open'] = chart_df['Open'].fillna(chart_df['Close'])
    chart_df['High'] = chart_df['High'].fillna(chart_df['Close'])
    chart_df['Low'] = chart_df['Low'].fillna(chart_df['Close'])
    chart_df['Volume'] = chart_df['Volume'].fillna(0)

    # 3. Lấy 60 phiên gần nhất
    plot_df = chart_df.tail(60).copy()

    # 4. Tính toán chính xác đường EMA20 và EMA50
    plot_df['EMA20'] = ta.trend.ema_indicator(plot_df['Close'], window=20)
    plot_df['EMA50'] = ta.trend.ema_indicator(plot_df['Close'], window=50)

    # Tạo các đường vẽ đè (Addplot) cho EMA20 (Xanh dương) và EMA50 (Cam)
    add_plots = [
        mpf.make_addplot(plot_df['EMA20'], color='blue', width=1.2),
        mpf.make_addplot(plot_df['EMA50'], color='orange', width=1.2)
    ]

    # 5. Cấu hình màu sắc đồ thị
    market_colors = mpf.make_marketcolors(
        up='green', down='red',
        edge='inherit',
        wick='inherit',
        volume='in'
    )
    style = mpf.make_mpf_style(marketcolors=market_colors, gridstyle='--', y_on_right=False)

    # 6. Tiến hành vẽ biểu đồ
    mpf.plot(
        plot_df,
        type='candle',
        style=style,
        title=f"\nBiểu đồ nến {ticker.upper()} (EMA20: Xanh | EMA50: Cam)",
        addplot=add_plots,
        volume=True,
        savefig=dict(fname=chart_path, dpi=150, bbox_inches='tight'), # Tăng nét ảnh
        figratio=(12, 7),
        figscale=1.1
    )
    
    return chart_path