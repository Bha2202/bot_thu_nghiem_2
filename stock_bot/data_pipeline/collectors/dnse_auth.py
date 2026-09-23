import os
import base64
import hashlib
import hmac
import uuid
from datetime import datetime, timezone
from email.utils import format_datetime
from urllib.parse import quote

import requests
from dotenv import load_dotenv


# ============================================================
# LOAD .ENV
# ============================================================

PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../../")
)

ENV_FILE = os.path.join(PROJECT_ROOT, ".env")

load_dotenv(ENV_FILE)

DNSE_API_KEY = os.getenv("DNSE_API_KEY")
DNSE_API_SECRET = os.getenv("DNSE_API_SECRET")


# ============================================================
# CONFIG
# ============================================================

BASE_URL = "https://openapi.dnse.com.vn"


# ============================================================
# CHECK CREDENTIALS
# ============================================================

def check_credentials():
    if not DNSE_API_KEY:
        raise RuntimeError("Thiếu DNSE_API_KEY trong file .env")

    if not DNSE_API_SECRET:
        raise RuntimeError("Thiếu DNSE_API_SECRET trong file .env")

    print("[DNSE AUTH] API Key: OK")
    print("[DNSE AUTH] API Secret: OK")


# ============================================================
# CREATE DNSE SIGNATURE
# ============================================================

def create_signature(method, path):
    """
    Tạo X-Signature theo chuẩn DNSE HTTP Signature.

    Signing String:

    (request-target): get /price/ACB/trades/latest
    date: ...
    nonce: ...

    Sau đó:
    HMAC-SHA256
    -> Base64
    -> URL encode + / =
    """

    if not DNSE_API_KEY:
        raise RuntimeError("Thiếu DNSE_API_KEY")

    if not DNSE_API_SECRET:
        raise RuntimeError("Thiếu DNSE_API_SECRET")

    # --------------------------------------------------------
    # 1. Tạo Date theo RFC1123, UTC
    # --------------------------------------------------------

    date_value = format_datetime(
        datetime.now(timezone.utc),
        usegmt=True
    )

    # --------------------------------------------------------
    # 2. Tạo nonce UUID4, bỏ dấu "-"
    # --------------------------------------------------------

    nonce = uuid.uuid4().hex

    # --------------------------------------------------------
    # 3. Method phải viết thường
    # --------------------------------------------------------

    method = method.lower()

    # --------------------------------------------------------
    # 4. Signing String
    # --------------------------------------------------------

    signing_string = (
        f"(request-target): {method} {path}\n"
        f"date: {date_value}\n"
        f"nonce: {nonce}"
    )

    # --------------------------------------------------------
    # 5. HMAC-SHA256
    # --------------------------------------------------------

    digest = hmac.new(
        DNSE_API_SECRET.encode("utf-8"),
        signing_string.encode("utf-8"),
        hashlib.sha256
    ).digest()

    # --------------------------------------------------------
    # 6. Base64
    # --------------------------------------------------------

    signature_base64 = base64.b64encode(digest).decode("ascii")

    # --------------------------------------------------------
    # 7. Chỉ URL-encode + / =
    # --------------------------------------------------------

    encoded_signature = quote(
        signature_base64,
        safe=""
    )

    # --------------------------------------------------------
    # 8. X-Signature
    # --------------------------------------------------------

    x_signature = (
        f'Signature '
        f'keyId="{DNSE_API_KEY}",'
        f'algorithm="hmac-sha256",'
        f'headers="(request-target) date",'
        f'signature="{encoded_signature}",'
        f'nonce="{nonce}"'
    )

    return {
        "date": date_value,
        "nonce": nonce,
        "signature": x_signature,
    }


# ============================================================
# TEST DNSE API
# ============================================================

def test_latest_trade(symbol="ACB"):
    """
    Test API lấy giao dịch khớp gần nhất.
    """

    symbol = symbol.upper().strip()

    path = f"/price/{symbol}/trades/latest"

    url = BASE_URL + path

    # Tạo signature mới cho request này
    auth = create_signature(
        method="GET",
        path=path
    )

    headers = {
        "X-API-Key": DNSE_API_KEY,
        "X-Signature": auth["signature"],
        "Date": auth["date"],
        "Accept": "application/json",
    }

    print()
    print("==========================================")
    print("       TEST DNSE LATEST TRADE")
    print("==========================================")
    print(f"[DNSE] Symbol : {symbol}")
    print(f"[DNSE] URL    : {url}")
    print("[DNSE] Đang gọi API...")

    response = requests.get(
        url,
        headers=headers,
        timeout=10
    )

    print(f"[DNSE] HTTP Status: {response.status_code}")

    # Không in API Secret / Signature ra màn hình
    if response.status_code == 200:
        print("[DNSE] ✅ API CALL SUCCESS")

        try:
            data = response.json()
            print("[DNSE] Response:")
            print(data)
        except Exception:
            print("[DNSE] Response không phải JSON:")
            print(response.text)

        return True

    print("[DNSE] ❌ API CALL FAILED")
    print("[DNSE] Response:")
    print(response.text)

    return False


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    check_credentials()

    test_latest_trade("ACB")