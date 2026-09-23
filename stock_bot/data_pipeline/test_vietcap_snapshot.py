import requests
import json


URL = (
    "https://trading.vietcap.com.vn/"
    "api/price/v1/w/priceboard/tickers/price/group"
)


HEADERS = {
    "accept": "application/json, text/plain, */*",
    "content-type": "application/json",
    "origin": "https://trading.vietcap.com.vn",
    "referer": "https://trading.vietcap.com.vn/",
    "user-agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/153.0.0.0 Safari/537.36"
    )
}


def main():

    print("=" * 70)
    print("       TEST VIETCAP PRICEBOARD SNAPSHOT")
    print("=" * 70)

    exchanges = [
        "HOSE",
        "HNX",
        "UPCOM"
    ]

    for exchange in exchanges:

        print("\n" + "=" * 70)
        print(f"SÀN: {exchange}")
        print("=" * 70)

        payload = {
            "group": exchange
        }

        try:

            response = requests.post(
                URL,
                headers=HEADERS,
                json=payload,
                timeout=15
            )

            print(
                "HTTP status:",
                response.status_code
            )

            response.raise_for_status()

            data = response.json()

            print(
                "Kiểu dữ liệu:",
                type(data).__name__
            )

            # -------------------------------------------------
            # In cấu trúc tổng quát
            # -------------------------------------------------

            if isinstance(data, dict):

                print(
                    "Các key:",
                    list(data.keys())
                )

            elif isinstance(data, list):

                print(
                    "Số phần tử:",
                    len(data)
                )

            # -------------------------------------------------
            # In thử 3 phần tử đầu
            # -------------------------------------------------

            print("\nDỮ LIỆU MẪU:")

            if isinstance(data, list):

                for item in data[:3]:

                    print(
                        json.dumps(
                            item,
                            ensure_ascii=False,
                            indent=2
                        )
                    )

            elif isinstance(data, dict):

                print(
                    json.dumps(
                        data,
                        ensure_ascii=False,
                        indent=2
                    )[:5000]
                )

        except Exception as e:

            print(
                "❌ LỖI:",
                repr(e)
            )


if __name__ == "__main__":
    main()