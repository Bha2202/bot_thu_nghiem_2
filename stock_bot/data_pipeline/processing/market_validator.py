import logging
import math


logger = logging.getLogger(__name__)


class MarketValidator:

    # =========================================================
    # KIỂM TRA MỘT BẢN GHI DỮ LIỆU
    # =========================================================

    @staticmethod
    def validate(record):

        # =====================================================
        # 1. KIỂM TRA KIỂU DỮ LIỆU
        # =====================================================

        if not isinstance(record, dict):

            logger.warning(
                "Dữ liệu không phải dictionary."
            )

            return False

        # =====================================================
        # 2. KIỂM TRA MÃ CỔ PHIẾU
        # =====================================================

        symbol = record.get("symbol")

        if not symbol:

            logger.warning(
                "Dữ liệu thiếu mã cổ phiếu."
            )

            return False

        if not isinstance(
            symbol,
            str
        ):

            logger.warning(
                f"Mã cổ phiếu không hợp lệ: "
                f"{symbol}"
            )

            return False

        # Chuẩn hóa mã
        symbol = (
            symbol
            .strip()
            .upper()
        )

        if not symbol:

            logger.warning(
                "Mã cổ phiếu rỗng."
            )

            return False

        # Giới hạn độ dài mã
        if not (
            2 <= len(symbol) <= 10
        ):

            logger.warning(
                f"{symbol}: độ dài mã "
                "không hợp lệ."
            )

            return False

        # Mã cổ phiếu chỉ chứa chữ/số
        if not symbol.isalnum():

            logger.warning(
                f"{symbol}: mã cổ phiếu "
                "chứa ký tự không hợp lệ."
            )

            return False

        # Ghi lại mã đã chuẩn hóa
        record["symbol"] = symbol

        # =====================================================
        # 3. KIỂM TRA GIÁ
        # =====================================================

        price = record.get("price")

        if price is not None:

            if not MarketValidator._is_valid_number(
                price
            ):

                logger.warning(
                    f"{symbol}: giá không hợp lệ: "
                    f"{price}"
                )

                return False

            price = float(price)

            if price <= 0:

                logger.warning(
                    f"{symbol}: giá phải "
                    f"lớn hơn 0: {price}"
                )

                return False

            # Chuẩn hóa giá
            record["price"] = price

        # =====================================================
        # 4. KIỂM TRA KHỐI LƯỢNG
        # =====================================================

        volume = record.get("volume")

        if volume is not None:

            if not MarketValidator._is_valid_number(
                volume
            ):

                logger.warning(
                    f"{symbol}: khối lượng "
                    f"không hợp lệ: {volume}"
                )

                return False

            volume = float(volume)

            if volume < 0:

                logger.warning(
                    f"{symbol}: khối lượng "
                    f"không được âm: {volume}"
                )

                return False

            # Chuẩn hóa volume
            record["volume"] = volume

        # =====================================================
        # 5. KIỂM TRA BID
        # =====================================================

        bid = record.get("bid")

        if bid is not None:

            if not MarketValidator._is_valid_number(
                bid
            ):

                logger.warning(
                    f"{symbol}: bid không hợp lệ: "
                    f"{bid}"
                )

                return False

            bid = float(bid)

            if bid < 0:

                logger.warning(
                    f"{symbol}: bid không được âm: "
                    f"{bid}"
                )

                return False

            record["bid"] = bid

        # =====================================================
        # 6. KIỂM TRA ASK
        # =====================================================

        ask = record.get("ask")

        if ask is not None:

            if not MarketValidator._is_valid_number(
                ask
            ):

                logger.warning(
                    f"{symbol}: ask không hợp lệ: "
                    f"{ask}"
                )

                return False

            ask = float(ask)

            if ask < 0:

                logger.warning(
                    f"{symbol}: ask không được âm: "
                    f"{ask}"
                )

                return False

            record["ask"] = ask

        # =====================================================
        # 7. KIỂM TRA QUAN HỆ BID / ASK
        # =====================================================

        if (
            bid is not None
            and ask is not None
            and bid > ask
        ):

            logger.warning(
                f"{symbol}: bid ({bid}) "
                f"lớn hơn ask ({ask})."
            )

            return False

        # =====================================================
        # 8. KIỂM TRA TIMESTAMP
        # =====================================================

        timestamp = record.get(
            "timestamp"
        )

        if timestamp is not None:

            # Timestamp từ Vietcap có thể là
            # số hoặc chuỗi nên không ép kiểu.
            #
            # Chỉ loại trường hợp rỗng.

            if isinstance(
                timestamp,
                str
            ):

                timestamp = timestamp.strip()

                if not timestamp:

                    logger.warning(
                        f"{symbol}: timestamp "
                        "rỗng."
                    )

                    return False

                record["timestamp"] = timestamp

        # =====================================================
        # 9. DỮ LIỆU HỢP LỆ
        # =====================================================

        return True

    # =========================================================
    # KIỂM TRA SỐ
    # =========================================================

    @staticmethod
    def _is_valid_number(value):

        try:

            number = float(value)

            return math.isfinite(
                number
            )

        except (
            TypeError,
            ValueError
        ):

            return False