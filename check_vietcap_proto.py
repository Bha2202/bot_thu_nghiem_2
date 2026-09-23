from google.protobuf.internal.decoder import _DecodeVarint
from google.protobuf.internal.encoder import _VarintBytes


def read_varint(data, pos):
    """
    Đọc một số nguyên kiểu protobuf varint.
    """
    value, new_pos = _DecodeVarint(data, pos)
    return value, new_pos


def read_fixed64(data, pos):
    """
    Đọc 8 byte kiểu fixed64.
    """
    value = int.from_bytes(
        data[pos:pos + 8],
        byteorder="little",
        signed=False
    )

    return value, pos + 8


def read_double(data, pos):
    """
    Đọc 8 byte thành số thực double.
    """
    import struct

    value = struct.unpack(
        "<d",
        data[pos:pos + 8]
    )[0]

    return value, pos + 8


def read_field(data, pos):
    """
    Đọc một field protobuf.
    """

    start_pos = pos

    # Đọc key
    key, pos = read_varint(data, pos)

    field_number = key >> 3
    wire_type = key & 0x07

    # -----------------------------------------
    # Wire type 0: Varint
    # -----------------------------------------

    if wire_type == 0:

        value, pos = read_varint(
            data,
            pos
        )

        return (
            field_number,
            wire_type,
            value,
            pos
        )

    # -----------------------------------------
    # Wire type 1: 64-bit
    # -----------------------------------------

    elif wire_type == 1:

        value, pos = read_double(
            data,
            pos
        )

        return (
            field_number,
            wire_type,
            value,
            pos
        )

    # -----------------------------------------
    # Wire type 2: Length-delimited
    # -----------------------------------------

    elif wire_type == 2:

        length, pos = read_varint(
            data,
            pos
        )

        raw = data[
            pos:pos + length
        ]

        pos += length

        # Thử giải mã UTF-8
        try:

            value = raw.decode(
                "utf-8"
            )

        except UnicodeDecodeError:

            value = raw.hex()

        return (
            field_number,
            wire_type,
            value,
            pos
        )

    # -----------------------------------------
    # Wire type 5: 32-bit
    # -----------------------------------------

    elif wire_type == 5:

        value = int.from_bytes(
            data[pos:pos + 4],
            byteorder="little",
            signed=False
        )

        pos += 4

        return (
            field_number,
            wire_type,
            value,
            pos
        )

    # -----------------------------------------
    # Không hỗ trợ
    # -----------------------------------------

    else:

        raise ValueError(
            f"Wire type không hỗ trợ: {wire_type} "
            f"tại vị trí {start_pos}"
        )


def decode_protobuf(data):
    """
    Giải mã toàn bộ protobuf packet.
    """

    pos = 0
    fields = []

    while pos < len(data):

        try:

            field_number, wire_type, value, pos = read_field(
                data,
                pos
            )

            fields.append(
                (
                    field_number,
                    wire_type,
                    value
                )
            )

        except Exception as e:

            print(
                f"Lỗi tại vị trí {pos}: {e}"
            )

            break

    return fields


# =========================================================
# PACKET MẪU LẤY TỪ VIETCAP
# =========================================================

packet = (
    b'\x12\x0cVN000000MSR5'
    b'\x1a\x03MSR'
    b'!\x00\x00\x00\x00\x00\xed\xe7@'
    b')\x00\x00\x00\x00\x00@\x9f@'
    b'1\x00\x00\x00\x00\x80+\xe8@'
    b'9\x00\x00\x00\x00\x80\x18\xe7@'
    b'A\x00\x00\x00\x00\x00\x00\x00\x00'
    b'I\x00\x00\x00\x00\x00\xc0r@'
    b'Q\x00\x00\x00\x00\x00\x00\x00\x00'
    b'Y\x00\x00\x00\x00\xae5lA'
    b'b\nLO_MORNING'
    b'i\x00\x00\x00\x00\x80\xff\xe6@'
    b'q\x00\x00\x00\x00\x80j\xea@'
    b'y\x00\x00\x00\x00\x80\x94\xe3@'
    b'\x81\x01\x00\x00\x00\x00\xa0g+A'
    b'\x89\x01\xa9\xd8\x84\xd7\xe6\xe6\xe7@'
    b'\x92\x01\x182026-09-21T02:33:44.606Z'
    b'\x99\x01\x00\x00\x00\x00\x80\x18\xe7@'
    b'\xa1\x01\x00\x00\x00\x00\xb0\xad*A'
    b'\xa9\x01\x00\x00\x00\x00\xc0\xa0"A'
    b'\xb1\x01\x00\x00@\xf8\xf2T\xd0A'
    b'\xb9\x01\x00\x00\x00\x9b#w\xd0A'
    b'\xc1\x01H\xe1z\x14\xc6v\xe5@'
    b'\xca\x01\x01'
)


# =========================================================
# CHẠY GIẢI MÃ
# =========================================================

print()
print("=" * 80)
print("VIETCAP PROTOBUF DECODER")
print("=" * 80)

print(
    "Kích thước packet:",
    len(packet),
    "bytes"
)

print()


fields = decode_protobuf(packet)


for field_number, wire_type, value in fields:

    print(
        f"Field {field_number:<3} "
        f"| wire_type={wire_type} "
        f"| value={value}"
    )


print()
print("=" * 80)
print("HẾT")
print("=" * 80)