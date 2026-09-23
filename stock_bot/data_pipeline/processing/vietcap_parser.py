import logging
import struct


logger = logging.getLogger(__name__)


class VietcapParser:

    @staticmethod
    def parse_match_price(data):
        """
        Chuẩn hóa dữ liệu giá khớp từ Vietcap.

        Hỗ trợ:
        - dict
        - list
        - protobuf bytes

        Kết quả chuẩn:

        {
            "symbol": "...",
            "price": ...,
            "volume": ...,
            "timestamp": ...,
            "symbol_id": ...
        }
        """

        try:

            # =================================================
            # TRƯỜNG HỢP 1: PROTOBUF BYTES
            # =================================================

            if isinstance(
                data,
                (bytes, bytearray)
            ):

                fields = (
                    VietcapParser._decode_protobuf(
                        data
                    )
                )

                if not fields:
                    return []

                symbol = None
                ticker = None
                price = None
                volume = None
                timestamp = None

                # ---------------------------------------------
                # ĐỌC CÁC FIELD VIETCAP
                # ---------------------------------------------

                for item in fields:

                    field = item["field"]
                    value = item["value"]

                    # Field 2 = Symbol ID
                    if field == 2:
                        symbol = value

                    # Field 3 = Ticker
                    elif field == 3:
                        ticker = value

                    # Field 16 = Volume
                    elif field == 16:
                        volume = value

                    # Field 18 = Timestamp
                    elif field == 18:
                        timestamp = value

                    # Field 19 = Match Price
                    elif field == 19:
                        price = value

                # ---------------------------------------------
                # KIỂM TRA TICKER
                # ---------------------------------------------

                if not ticker:

                    logger.warning(
                        "match_price protobuf "
                        "không có ticker."
                    )

                    return []

                # ---------------------------------------------
                # KIỂM TRA GIÁ
                # ---------------------------------------------

                if price is None:

                    logger.warning(
                        f"match_price không có giá: "
                        f"{ticker}"
                    )

                    return []

                # ---------------------------------------------
                # TRẢ VỀ DỮ LIỆU CHUẨN
                # ---------------------------------------------

                return [
                    {
                        "symbol": str(
                            ticker
                        ).upper(),

                        "price": price,

                        "volume": volume,

                        "timestamp": timestamp,

                        "symbol_id": symbol
                    }
                ]

            # =================================================
            # TRƯỜNG HỢP 2: LIST
            # =================================================

            if isinstance(
                data,
                list
            ):

                results = []

                for item in data:

                    parsed = (
                        VietcapParser._parse_one(
                            item
                        )
                    )

                    if parsed:

                        results.append(
                            parsed
                        )

                return results

            # =================================================
            # TRƯỜNG HỢP 3: DICT
            # =================================================

            if isinstance(
                data,
                dict
            ):

                parsed = (
                    VietcapParser._parse_one(
                        data
                    )
                )

                if parsed:

                    return [
                        parsed
                    ]

                return []

            # =================================================
            # KHÔNG NHẬN DIỆN
            # =================================================

            logger.warning(
                "Không nhận diện được "
                "cấu trúc match_price"
            )

            return []

        except Exception as e:

            logger.exception(
                f"Lỗi parse match_price: {e}"
            )

            return []

    # =========================================================
    # PARSE DICT
    # =========================================================

    @staticmethod
    def _parse_one(item):

        if not isinstance(
            item,
            dict
        ):

            return None

        # -----------------------------------------------------
        # SYMBOL
        # -----------------------------------------------------

        symbol = (
            item.get("symbol")
            or item.get("sym")
            or item.get("s")
            or item.get("ticker")
        )

        # -----------------------------------------------------
        # PRICE
        # -----------------------------------------------------

        price = None

        for key in (
            "price",
            "p",
            "lastPrice",
            "matchPrice"
        ):

            if key in item:

                price = item[key]
                break

        # -----------------------------------------------------
        # VOLUME
        # -----------------------------------------------------

        volume = None

        for key in (
            "volume",
            "v",
            "matchVolume"
        ):

            if key in item:

                volume = item[key]
                break

        # -----------------------------------------------------
        # TIMESTAMP
        # -----------------------------------------------------

        timestamp = None

        for key in (
            "timestamp",
            "time",
            "ts"
        ):

            if key in item:

                timestamp = item[key]
                break

        # -----------------------------------------------------
        # SYMBOL ID
        # -----------------------------------------------------

        symbol_id = (
            item.get("symbol_id")
            or item.get("symbolId")
            or item.get("id")
        )

        # -----------------------------------------------------
        # KIỂM TRA SYMBOL
        # -----------------------------------------------------

        if not symbol:

            return None

        # -----------------------------------------------------
        # TRẢ VỀ CHUẨN
        # -----------------------------------------------------

        return {
            "symbol": str(
                symbol
            ).upper(),

            "price": price,

            "volume": volume,

            "timestamp": timestamp,

            "symbol_id": symbol_id
        }

    # =========================================================
    # PROTOBUF VARINT
    # =========================================================

    @staticmethod
    def _read_varint(
        data,
        pos
    ):

        value = 0
        shift = 0

        while pos < len(data):

            byte = data[pos]

            pos += 1

            value |= (
                (byte & 0x7F)
                << shift
            )

            if not (
                byte & 0x80
            ):

                return (
                    value,
                    pos
                )

            shift += 7

            if shift > 70:

                raise ValueError(
                    "Varint quá dài"
                )

        raise ValueError(
            "Varint không hợp lệ"
        )

    # =========================================================
    # PROTOBUF DECODER
    # =========================================================

    @staticmethod
    def _decode_protobuf(
        data
    ):

        fields = []

        pos = 0

        try:

            while pos < len(data):

                key, pos = (
                    VietcapParser._read_varint(
                        data,
                        pos
                    )
                )

                field_number = (
                    key >> 3
                )

                wire_type = (
                    key & 0x07
                )

                # ---------------------------------------------
                # WIRE TYPE 0
                # ---------------------------------------------

                if wire_type == 0:

                    value, pos = (
                        VietcapParser._read_varint(
                            data,
                            pos
                        )
                    )

                # ---------------------------------------------
                # WIRE TYPE 1
                # ---------------------------------------------

                elif wire_type == 1:

                    if (
                        pos + 8
                        > len(data)
                    ):

                        raise ValueError(
                            "Thiếu dữ liệu "
                            "wire type 1"
                        )

                    value = struct.unpack(
                        "<d",
                        data[
                            pos:
                            pos + 8
                        ]
                    )[0]

                    pos += 8

                # ---------------------------------------------
                # WIRE TYPE 2
                # ---------------------------------------------

                elif wire_type == 2:

                    length, pos = (
                        VietcapParser._read_varint(
                            data,
                            pos
                        )
                    )

                    if (
                        pos + length
                        > len(data)
                    ):

                        raise ValueError(
                            "Thiếu dữ liệu "
                            "wire type 2"
                        )

                    raw = data[
                        pos:
                        pos + length
                    ]

                    pos += length

                    try:

                        value = raw.decode(
                            "utf-8"
                        )

                    except UnicodeDecodeError:

                        value = raw

                # ---------------------------------------------
                # WIRE TYPE 5
                # ---------------------------------------------

                elif wire_type == 5:

                    if (
                        pos + 4
                        > len(data)
                    ):

                        raise ValueError(
                            "Thiếu dữ liệu "
                            "wire type 5"
                        )

                    value = struct.unpack(
                        "<f",
                        data[
                            pos:
                            pos + 4
                        ]
                    )[0]

                    pos += 4

                # ---------------------------------------------
                # WIRE TYPE KHÔNG HỖ TRỢ
                # ---------------------------------------------

                else:

                    raise ValueError(
                        f"Wire type không hỗ trợ: "
                        f"{wire_type}"
                    )

                fields.append(
                    {
                        "field": field_number,

                        "wire_type": wire_type,

                        "value": value
                    }
                )

        except Exception as e:

            logger.warning(
                f"Lỗi decode protobuf: {e}"
            )

        return fields