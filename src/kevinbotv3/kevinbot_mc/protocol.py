import abc
import dataclasses
import enum
import struct

import cbor2
import modbus_crc
import semver

MAX_VERSION = semver.Version(2025, 11, 9999)

class TransactionStatusCodes(enum.IntEnum):
    OK = 0x00
    INVALID_COMMAND = 0x01
    QUEUE_FULL = 0x02
    INVALID_CHECKSUM = 0x03
    INVALID_LENGTH = 0x04
    INVALID_FORMAT = 0x05
    INVALID_PROCESSING_ERROR = 0x06
    TIMEOUT = 0x07
    BUFFER_OVERFLOW = 0x08
    INVALID_DATA = 0x09
    NOT_READY = 0x0A
    BUSY = 0x0B
    EXEC_FAILURE = 0x0C
    ESTOP = 0x0D
    INTERFACE_NOT_ACTIVE = 0x0E
    WATCHDOG_EXPIRED = 0x0F
    INVALID_CONFIG_KEY = 0x10
    NOT_IMPLEMENTED = 0x11

    def __str__(self):
        return TransactionStatusCodes(super().__int__()).name


class TransactionDataType(enum.IntEnum):
    NULL = 0xFF
    RESERVED = 0xFE
    FLOAT = 0xFC
    DOUBLE = 0xFB
    SIGNED_INT = 0xFA
    UNSIGNED_INT = 0xF9
    BOOLEAN = 0xF8
    STRING = 0xF7
    PACKED = 0xF6


class TransactionData(abc.ABC):
    @abc.abstractmethod
    def generate(self) -> tuple[int, bytes]:
        pass


@dataclasses.dataclass
class TransactionResult:
    controlWord: int
    data: TransactionData
    status: TransactionStatusCodes = TransactionStatusCodes.OK


class EmptyTransactionData(TransactionData):
    def generate(self) -> tuple[int, bytes]:
        return 0xFF, b""


class FloatTransactionData(TransactionData):
    def __init__(self, value: float) -> None:
        self.value = value

    def generate(self) -> tuple[int, bytes]:
        return 0xFC, bytearray(struct.pack(">f", self.value))


class UnsignedIntegerTransactionData(TransactionData):
    def __init__(self, value: int, size: int) -> None:
        self.value = value
        self.size = size

    def generate(self) -> tuple[int, bytes]:
        if self.size not in (1, 2, 4):
            # not uint8_t, uint16_t, or uint32_t
            raise ValueError(
                "Unsigned integer transaction data size must be 1, 2, or 4 (bytes)"
            )

        if self.value < 0:
            raise ValueError(
                "Unsigned integer transaction data value must be non-negative"
            )

        if self.size == 1 and self.value > 255:
            raise ValueError(
                "Unsigned integer transaction data value must be 255 when bytes=1"
            )

        if self.size == 2 and self.value > 65535:
            raise ValueError(
                "Unsigned integer transaction data value must be 65535 when bytes=2"
            )

        if self.size == 4 and self.value > 4294967295:
            raise ValueError(
                "Unsigned integer transaction data value must be 4294967295 when bytes=4"
            )

        # convert value into 0xF9, Big Endian
        return 0xF9, self.value.to_bytes(self.size, "big")

    def __str__(self):
        return f"<UnsignedIntegerTransactionData(value={self.value}, size={self.size})>"


class StringTransactionData(TransactionData):
    def __init__(self, value: str):
        self.value = value

    def generate(self) -> tuple[int, bytes]:
        return 0xF7, self.value.encode("utf-8")

    def __str__(self):
        return f"<StringTransactionData(value={self.value})>"


class BooleanTransactionData(TransactionData):
    def __init__(self, value: bool):
        self.value = value

    def generate(self) -> tuple[int, bytes]:
        return 0xF8, int(self.value).to_bytes(1, "big")

    def __str__(self):
        return f"<BooleanTransactionData(value={self.value})>"


class PackedTransactionData(TransactionData):
    def __init__(self, value: dict):
        self.value = value

    def generate(self) -> tuple[int, bytes]:
        b = cbor2.dumps(self.value, canonical=True)
        return 0xF6, b

    def __str__(self):
        return f"<PackedTransactionData: {self.value}>"


def make_response_data(data_type: TransactionDataType, data: bytes):
    match data_type:
        case TransactionDataType.UNSIGNED_INT:
            return UnsignedIntegerTransactionData(
                int.from_bytes(data, "big"), len(data)
            )
        case TransactionDataType.PACKED:
            return PackedTransactionData(cbor2.loads(data))
        case TransactionDataType.STRING:
            return StringTransactionData(data.decode("utf-8"))
        case TransactionDataType.BOOLEAN:
            return BooleanTransactionData(int.from_bytes(data, "big") == 1)
        case TransactionDataType.FLOAT:
            return FloatTransactionData(struct.unpack(">f", data)[0])
        case _:
            return EmptyTransactionData()


def make_transaction_data(control_word: int, data: TransactionData, uid: int) -> bytes:
    data = data.generate()
    data = (
        b"\x02"
        + data[0].to_bytes(1, "big")
        + control_word.to_bytes(2, "big")
        + len(data[1]).to_bytes(2, "big")
        + data[1]
        + uid.to_bytes(2, "big")
    )
    crc = bytearray(modbus_crc.crc16(data))
    crc.reverse()
    return data + crc
