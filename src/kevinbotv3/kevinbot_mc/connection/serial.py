import struct
import threading
import time
from collections import deque
from collections.abc import Callable
from typing import Any, Final

import modbus_crc

from kevinbotlib.hardware.interfaces.serial import RawSerialInterface
from kevinbotlib.logger import Logger
from kevinbotlib.robot import BaseRobot

from kevinbotv3.kevinbot_mc.connection.abstract import AbstractMotorConnection
from kevinbotv3.kevinbot_mc.protocol import (
    TransactionData,
    TransactionStatusCodes,
    TransactionDataType,
    TransactionResult,
    make_response_data,
)


class SerialUidController:
    def __init__(self):
        self._uid = 0x0000
        self._lock = threading.Lock()

    def new(self):
        with self._lock:
            self._uid = (self._uid + 1) % 65536
            return self._uid


class SerialMotorConnection(AbstractMotorConnection):
    def __init__(self, port: str, baud: int):
        self.port = port
        self.baud = baud
        self.serial = RawSerialInterface(None, port, baud)

        self.signal_callbacks: list[Callable[[int, TransactionData], Any]] = []
        self.unsolicited_callbacks: list[Callable[[int, TransactionData], Any]] = []

        self.read_thread: threading.Thread | None = None
        self.running: bool = False
        self.running_lock = threading.Lock()

        # Thread-safe frame queues
        self.response_queue: deque = deque()
        self.unsolicited_queue: deque = deque()
        self.queue_lock = threading.Lock()

        # Pending response tracking
        self.waiting_responses: dict[int, threading.Event] = {}
        self.response_data: dict[int, dict] = {}
        self.response_lock = threading.Lock()

        self.uid_controller = SerialUidController()
        self.buffer = bytearray()
        self.buffer_lock = threading.Lock()

    def _is_running(self):
        with self.running_lock:
            return self.running

    def _set_running(self, value: bool):
        with self.running_lock:
            self.running = value

    def _parse_all_frames(self):
        """Parse all complete frames from buffer and queue them appropriately."""
        with self.buffer_lock:
            max_iterations = len(self.buffer)
            iterations = 0

            while len(self.buffer) >= 8 and iterations < max_iterations:
                iterations += 1
                parsed, frame_type, consumed = self._try_parse_next_frame()

                if consumed == 0:
                    break

                if parsed is None:
                    Logger().warning(
                        f"Frame parse error, dropping 1 byte and retrying. "
                        f"Buffer start: {self.buffer[:16].hex()}"
                    )
                    del self.buffer[0:1]
                    continue

                del self.buffer[0:consumed]

                with self.queue_lock:
                    if frame_type == 0x01:
                        self.response_queue.append(parsed)
                        Logger().trace(f"Queued response UID={parsed['uid']}, "
                                     f"queue size={len(self.response_queue)}")
                    elif frame_type == 0x02:
                        self.unsolicited_queue.append(parsed)
                        Logger().trace(f"Queued unsolicited frame, "
                                     f"queue size={len(self.unsolicited_queue)}")

    def _try_parse_next_frame(self):
        """Try to parse the next frame at the start of the buffer.

        Returns: (parsed_dict or None, frame_type or None, bytes_consumed)
        """
        buf = self.buffer

        if len(buf) < 8:
            return None, None, 0

        start_marker = buf[0]

        try:
            if start_marker == 0x01:
                # Response frame: [0x01][status][data_type][control_word][data_len][data...][uid][crc]
                HEADER_SIZE = 7
                TAIL_SIZE = 4

                if len(buf) < HEADER_SIZE:
                    return None, None, 0

                status = buf[1]
                data_type = buf[2]
                control_word = struct.unpack(">H", buf[3:5])[0]
                data_len = struct.unpack(">H", buf[5:7])[0]

                total_len = HEADER_SIZE + data_len + TAIL_SIZE

                if len(buf) < total_len:
                    return None, None, 0

                frame = buf[0:total_len]

                if not modbus_crc.check_crc(frame):
                    Logger().error(f"CRC mismatch in response frame. Start: {frame[:16].hex()}")
                    return None, None, 1

                data_payload = frame[7:7 + data_len]
                uid = struct.unpack(">H", frame[7 + data_len:9 + data_len])[0]

                FAILURE_CONTROL_WORD = 0x7FFF
                if control_word == FAILURE_CONTROL_WORD:
                    Logger().error(
                        f"Response has FAILURE control word ({hex(FAILURE_CONTROL_WORD)}). "
                        f"Status: {status}, Data Type: {data_type}, UID: {uid}"
                    )

                parsed = {
                    "frame_type": 0x01,
                    "status": TransactionStatusCodes(status),
                    "data_type": TransactionDataType(data_type),
                    "control_word": control_word,
                    "data": data_payload,
                    "uid": uid,
                }

                return parsed, 0x01, total_len

            elif start_marker == 0x02:
                # Unsolicited frame: [0x02][data_type][control_word][data_len][data...][crc]
                HEADER_SIZE = 6
                TAIL_SIZE = 2

                if len(buf) < HEADER_SIZE:
                    return None, None, 0

                data_type = buf[1]
                control_word = struct.unpack(">H", buf[2:4])[0]
                data_len = struct.unpack(">H", buf[4:6])[0]

                total_len = HEADER_SIZE + data_len + TAIL_SIZE

                if len(buf) < total_len:
                    return None, None, 0

                frame = buf[0:total_len]

                if not modbus_crc.check_crc(frame):
                    Logger().error(f"CRC mismatch in unsolicited frame. Start: {frame[:16].hex()}")
                    return None, None, 1

                data_payload = frame[6:6 + data_len]

                parsed = {
                    "frame_type": 0x02,
                    "data_type": TransactionDataType(data_type),
                    "control_word": control_word,
                    "data": data_payload,
                }

                return parsed, 0x02, total_len

            else:
                Logger().error(f"Unknown start marker: 0x{start_marker:02X}")
                return None, None, 1

        except Exception as e:
            Logger().error(f"Exception during frame parse: {e}")
            return None, None, 1

    def _dispatch_unsolicited(self):
        """Process and dispatch unsolicited frames to subscribers."""
        while self._is_running():
            with self.queue_lock:
                if self.unsolicited_queue:
                    parsed = self.unsolicited_queue.popleft()
                else:
                    parsed = None

            if parsed:
                for sub in self.unsolicited_callbacks:
                    try:
                        sub(
                            parsed["control_word"],
                            make_response_data(parsed["data_type"], parsed["data"]),
                        )
                    except Exception as e:
                        Logger().error(f"Error in unsolicited subscriber: {e}")
                if parsed["control_word"] <= 0x7FFF:
                    for sub in self.signal_callbacks:
                        try:
                            sub(
                                parsed["control_word"],
                                make_response_data(parsed["data_type"], parsed["data"]),
                            )
                        except Exception as e:
                            Logger().error(f"Error in unsolicited subscriber: {e}")
            else:
                time.sleep(0.001)

    def _find_response_for_uid(self, uid: int):
        """Search response queue for a matching UID and remove it.

        Returns: parsed response dict or None
        """
        with self.queue_lock:
            for i, response in enumerate(self.response_queue):
                if response["uid"] == uid:
                    del self.response_queue[i]
                    Logger().trace(f"Found response for UID={uid} at queue position {i}")
                    return response
        return None

    def _read_loop(self):
        """Main read loop that processes incoming serial data."""
        self._set_running(True)
        Logger().info(f"Serial read loop started for {self.port}")

        unsolicited_thread = threading.Thread(
            target=self._dispatch_unsolicited,
            daemon=True,
            name=f"SerialUnsolicitedDispatcher.{self.port}",
        )
        unsolicited_thread.start()

        while self._is_running():
            try:
                new_data = self.serial.read(1)
                if new_data:
                    with self.buffer_lock:
                        self.buffer.extend(new_data)
                    self._parse_all_frames()

                    # Process any responses and signal waiting threads
                    with self.queue_lock:
                        while self.response_queue:
                            response = self.response_queue.popleft()
                            uid = response["uid"]

                            with self.response_lock:
                                if uid in self.waiting_responses:
                                    self.response_data[uid] = response
                                    self.waiting_responses[uid].set()

            except TimeoutError:
                time.sleep(0.001)
            except Exception as e:
                Logger().error(
                    f"An error occurred while reading the motor serial port: {e!r} for {self.port}"
                )
                self._set_running(False)

    def start(self):
        """Open serial port and start read thread."""
        if not self.serial.is_open:
            self.serial.open()

        if not self.read_thread:
            self.read_thread = threading.Thread(
                target=self._read_loop,
                daemon=True,
                name=f"SerialMotorReader.{self.port}",
            )
            self.read_thread.start()

    def stop(self):
        """Stop read thread and close serial port."""
        self._set_running(False)
        if self.read_thread:
            self.read_thread.join(timeout=1.0)
            self.read_thread = None
        self.serial.close()

    def add_signal_callback(self, callback: Callable[[int, TransactionData], Any]) -> None:
        self.signal_callbacks.append(callback)

    def add_unsolicited_callback(self, callback: Callable[[int, TransactionData], Any]) -> None:
        self.unsolicited_callbacks.append(callback)

    def execute(
        self,
        control: int,
        data: TransactionData,
        retry: int = 3,
        timeout: float = 0.3,
    ) -> TransactionResult:
        """Execute a transaction and wait for response."""
        poll_interval: Final[float] = 0.001

        for attempt in range(retry + 1):
            uid = self.uid_controller.new()

            # Prepare transaction data
            gen = data.generate()
            frame = (
                b"\x02"
                + gen[0].to_bytes(1, "big")
                + control.to_bytes(2, "big")
                + len(gen[1]).to_bytes(2, "big")
                + gen[1]
                + uid.to_bytes(2, "big")
            )
            crc = bytearray(modbus_crc.crc16(frame))
            crc.reverse()
            frame = frame + crc

            Logger().trace(f"Sending UID={uid}: {frame.hex()}")

            # Register this UID as pending
            with self.response_lock:
                event = threading.Event()
                self.waiting_responses[uid] = event

            try:
                # Send transaction
                self.serial.write(frame)

                # Wait for response with timeout
                start_time = time.monotonic()
                while True:
                    elapsed = time.monotonic() - start_time
                    if elapsed >= timeout:
                        Logger().warning(
                            f"Timeout on UID={uid} attempt {attempt + 1} "
                            f"(queue size: {len(self.response_queue)})"
                        )
                        break

                    # Check if response arrived
                    with self.response_lock:
                        if uid in self.response_data:
                            response = self.response_data[uid]
                            del self.response_data[uid]
                            del self.waiting_responses[uid]

                            return TransactionResult(
                                response["control_word"],
                                make_response_data(response["data_type"], response["data"]),
                                response["status"],
                            )

                    time.sleep(poll_interval)

            finally:
                # Clean up
                with self.response_lock:
                    if uid in self.waiting_responses:
                        del self.waiting_responses[uid]
                    if uid in self.response_data:
                        del self.response_data[uid]

            # Retry if not the last attempt
            if attempt < retry:
                continue

        raise TimeoutError(f"No response after {retry + 1} retries")

    def is_open(self):
        return self.serial.is_open and self.read_thread.is_alive()

    def name(self):
        return self.port