from pathlib import Path

import pandas as pd
from vnstock import Listing


class SymbolCollector:
    def __init__(self, source="KBS"):
        self.source = source
        self.exchanges = ["HOSE", "HNX", "UPCOM"]

    def get_symbols(self):
        try:
            listing = Listing(source=self.source)

            df = listing.symbols_by_exchange()

            if df is None or df.empty:
                print("[SYMBOL ERROR] Không lấy được danh sách mã.")
                return None

            # Chỉ giữ 3 sàn
            df = df[
                df["exchange"].isin(self.exchanges)
            ].copy()

            # Chỉ giữ cổ phiếu
            if "type" in df.columns:
                df = df[
                    df["type"].str.lower() == "stock"
                ].copy()

            # Chuẩn hóa mã
            df["symbol"] = (
                df["symbol"]
                .astype(str)
                .str.strip()
                .str.upper()
            )

            # Bỏ mã trùng
            df = df.drop_duplicates(
                subset=["symbol"]
            ).reset_index(drop=True)

            print(
                f"[SYMBOL] Đã lấy {len(df)} mã cổ phiếu"
            )

            print("\n[SYMBOL] Theo sàn:")
            print(
                df.groupby("exchange")
                .size()
            )

            return df

        except Exception as e:
            print(
                f"[SYMBOL ERROR] "
                f"Lỗi lấy danh sách mã: {e}"
            )
            return None


if __name__ == "__main__":

    collector = SymbolCollector()

    df = collector.get_symbols()

    if df is not None:

        # Thư mục data của dự án
        output_path = Path(
            "data/symbols.csv"
        )

        output_path.parent.mkdir(
            parents=True,
            exist_ok=True
        )

        # Chỉ lưu 3 cột cần thiết
        df[
            ["symbol", "exchange", "type"]
        ].to_csv(
            output_path,
            index=False,
            encoding="utf-8-sig"
        )

        print(
            f"\n[SYMBOL] Đã lưu danh sách vào:"
            f"\n{output_path}"
        )

        print(
            f"\n===== TỔNG SỐ MÃ: {len(df)} ====="
        )