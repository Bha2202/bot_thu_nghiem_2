# 📈 Fintech Stock Signal Bot - ANA

**Telegram Bot tín hiệu đầu tư chứng khoán Việt Nam** — theo dõi giá, phân tích kỹ thuật/cơ bản và cảnh báo mua/bán tự động ngay trên Telegram.

> ⚠️ Đây là dự án cá nhân/học tập  **không phải lời khuyên đầu tư**. Vui lòng tự chịu trách nhiệm với các quyết định giao dịch của mình.

---

## ✨ Tính năng chính

Bot hỗ trợ các lệnh sau trên Telegram:

| Lệnh | Chức năng |
|---|---|
| `/start` | Khởi động bot, hiện hướng dẫn ban đầu |
| `/stock <mã>` | Tra cứu tín hiệu & phân tích một mã cổ phiếu (VD: `/stock FPT`) |
| `/today` | Danh sách tín hiệu MUA/BÁN phát hiện trong ngày |
| `/watchlist` | Danh sách cổ phiếu đạt chuẩn phân tích cơ bản (Lớp 1 & 2) |
| `/sector` | Phân tích sức mạnh & dòng tiền theo nhóm ngành |
| `/alert <mã> > /< <giá>` | Đặt cảnh báo giá tự do (VD: `/alert HPG > 28.5`) |
| `/portfolio` | Xem danh mục tài khoản đang nắm giữ |
| `/help` | Hướng dẫn sử dụng bot |

Ngoài ra bot còn có:
- **Job quét giá tự động** mỗi 2 phút để kiểm tra cảnh báo giá và vi phạm ngưỡng Cắt lỗ / Chốt lời (Stop Loss / Take Profit).
- Cho phép gõ trực tiếp **mã cổ phiếu** vào khung chat (không cần lệnh) để tra cứu nhanh.
- Menu gợi ý lệnh được thiết lập tự động trên giao diện Telegram khi bot khởi động.

---

## 🏗️ Cấu trúc thư mục

```
fintech-stock-signal-bot/
├── .github/workflows/     # CI/CD, tự động hoá (GitHub Actions)
├── bot/                   # Xử lý logic Telegram (handlers, commands)
├── config/                # Cấu hình dự án
├── data/                  # Dữ liệu lưu trữ (watchlist, alert, portfolio...)
├── stock_bot/data_pipeline/  # Pipeline lấy & xử lý dữ liệu chứng khoán
├── strategies/            # Các chiến lược/công thức tạo tín hiệu mua-bán
├── main.py                # Điểm khởi chạy chính của bot
├── requirements.txt       # Danh sách thư viện phụ thuộc
├── .env.example           # Mẫu file biến môi trường
└── AGENTS.md              # Hướng dẫn onboarding môi trường vnstock cho AI coding agent
```

---

## 🛠️ Công nghệ sử dụng

- **Python 3.10+**
- [`python-telegram-bot`](https://github.com/python-telegram-bot/python-telegram-bot) — giao tiếp với Telegram Bot API
- [`vnstock`](https://github.com/thinh-vu/vnstock) / `vnstock3` — lấy dữ liệu chứng khoán Việt Nam
- `pandas` — xử lý & phân tích dữ liệu
- `python-dotenv` — quản lý biến môi trường
- `aiohttp`, `websockets`, `requests`, `python-socketio` — giao tiếp mạng/dữ liệu realtime

---

## 🚀 Cài đặt & chạy bot

### 1. Clone dự án

```bash
git clone https://github.com/thaitran3936-hub/fintech-stock-signal-bot.git
cd fintech-stock-signal-bot
```

### 2. Tạo môi trường ảo (khuyến khích)

```bash
python -m venv .venv
source .venv/bin/activate      # macOS/Linux
.venv\Scripts\activate         # Windows
```

### 3. Cài đặt thư viện

```bash
pip install -r requirements.txt
```

### 4. Cấu hình biến môi trường

Sao chép file mẫu và điền thông tin:

```bash
cp .env.example .env
```

Thêm vào file `.env`:

```env
TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here
```

> Lấy token bot bằng cách chat với [@BotFather](https://t.me/BotFather) trên Telegram và tạo bot mới bằng lệnh `/newbot`.

### 5. Chạy bot

```bash
python main.py
```

Nếu chạy thành công, terminal sẽ hiện log:

```
🚀 Telegram Bot đã khởi chạy thành công và đang lắng nghe...
```

Sau đó mở Telegram, tìm bot của bạn và gõ `/start` để bắt đầu.

---

## ⚙️ Ghi chú

- File `AGENTS.md` trong repo là tài liệu hướng dẫn dành cho các **AI coding assistant** (Cursor, Claude Code, ChatGPT, v.v.) khi cần tự động thiết lập môi trường `vnstock`. Đây **không phải** hướng dẫn dành cho người dùng cuối chạy bot — hãy làm theo mục *Cài đặt & chạy bot* ở trên là đủ.
- Nếu dùng gói `vnstock` có yêu cầu API key riêng, hãy tham khảo tài liệu chính thức tại [vnstocks.com](https://vnstocks.com) và **không chia sẻ API key trong log hoặc mã nguồn công khai**.

---

## 🗺️ Định hướng phát triển (Roadmap gợi ý)

- [ ] Thêm backtest chiến lược trên dữ liệu lịch sử
- [ ] Hỗ trợ đa tài khoản / đa người dùng
- [ ] Dashboard web đi kèm bot
- [ ] Thông báo qua nhiều kênh (Zalo, Discord, Email)

---

## 🤝 Đóng góp

Mọi ý kiến đóng góp, báo lỗi hoặc pull request đều được hoan nghênh. Hãy tạo issue trước khi gửi PR lớn để cùng thảo luận hướng triển khai.

## ⚠️ Miễn trừ trách nhiệm

Bot này được xây dựng cho mục đích học tập và tham khảo. Các tín hiệu, cảnh báo hay phân tích từ bot **không cấu thành lời khuyên đầu tư**. Nhà đầu tư cần tự nghiên cứu và chịu trách nhiệm với quyết định của mình.

## 📄 License

Chưa có license cụ thể — vui lòng liên hệ tác giả nếu muốn sử dụng lại mã nguồn cho mục đích khác ngoài tham khảo cá nhân.


