# Kevinbot Core Implementation for KevinbotLib
import time
import traceback
from enum import IntEnum
from threading import Thread

from kevinbotlib.hardware.controllers.keyvalue import RawKeyValueSerialController
from kevinbotlib.hardware.interfaces.serial import RawSerialInterface
from kevinbotlib.logger import Logger
from kevinbotlib.robot import BaseRobot
from pydantic import BaseModel


class MotorDriveStatus(IntEnum):
    """
    The status of each motor in the drivebase
    """

    UNKNOWN = 10
    """Motor status is unknown"""
    MOVING = 11
    """Motor is rotating"""
    HOLDING = 12
    """Motor is holding at position"""
    OFF = 13
    """Motor is off"""


class CoreStatus(BaseModel):
    linked: bool = False
    enabled: bool = False


class KevinbotDrivebase:
    def __init__(self, core: "KevinbotCore") -> None:
        self._core = core
        self._powers = [0.0, 0.0]
        self._watts = [0, 0]
        self._amps = [0, 0]
        self._states = [MotorDriveStatus.UNKNOWN, MotorDriveStatus.UNKNOWN]

    def drive_at_power(self, left: float, right: float):
        self._core.controller.write(b"\x08\x01", f"{int(left*100)},{int(right*100)}".encode())

    def drive_direction(self, power: float, direction: float):
        self._core.controller.write(b"\x08\x02", f"{int(power*100)},{int(direction*100)}".encode())

    def set_hold(self, hold: bool):
        self._core.controller.write(b"\x08\x03", f"{int(hold)}".encode())

class KevinbotBms(BaseModel):
    voltages: list[float] = []

class KevinbotCore:
    def __init__(self, interface: RawSerialInterface, heartbeat_interval: float = 1, battery_count: int = 2) -> None:
        self._controller = RawKeyValueSerialController(interface, b"\xFA", b"\xFE")
        BaseRobot.register_estop_hook(lambda: self.estop())
        self.heartbeat_interval = heartbeat_interval

        self.battery_count = battery_count
        self._status = CoreStatus()
        self._bms = KevinbotBms()
        self._bms.voltages = [0.0] * self.battery_count

    def begin(self) -> None:
        """Begin a new connection to the Kevinbot Core (formerly Kevinbot Hardware Core)"""
        self._controller.write(b"\x02\x04")
        self._controller.write(b"\x02\x02")
        self._controller.write(b"\x04\x01", b"0")
        self._controller.write(b"\x03\x05")
        self._status.linked = True
        Thread(target=self.heartbeat_loop, daemon=True).start()
        Thread(target=self._rx_loop, daemon=True).start()

    def unlink(self):
        self._controller.write(b"\x02\x03")
        self._status.linked = False

    def estop(self):
        self._controller.write(b"\x04\x02")
        self._controller.interface.flush()
        Logger().warning("Sent core emergency stop command")

    def request_state_update(self, enabled: bool):  # noqa: FBT001
        if enabled == self._status.enabled:
            return
        self._controller.write(b"\x04\x01", str(int(enabled)).encode())

    def heartbeat_loop(self):
        while True:
            if not self._status.linked:
                return
            self._controller.write(b"\x02\x01")
            time.sleep(self.heartbeat_interval)

    def _rx_loop(self):
        while True:
            try:
                if not self._status.linked:
                    return

                data = self._controller.read()

                if not data:
                    continue
                key, value = data
                match key:
                    case b"core.enabled":
                        self._status.enabled = value == b"true"
                    case b"connection.requesthandshake":
                        Logger().warning("Received handshake request from core")
                        self._controller.write(b"\x02\x04")
                        self._controller.write(b"\x02\x02")
                        self._controller.write(b"\x04\x01", b"0")
                        self._controller.write(b"\x03\x05")
                    case b"bms.voltages":
                        voltages = [float(v.decode()) / 100 for v in value.split(b",")]
                        if len(voltages) != self.battery_count:
                            Logger().error(f"Received {len(voltages)} voltages, expected {self.battery_count}")
                        else:
                            for i in range(self.battery_count):
                                Logger().info(f"Battery {i} voltage: {voltages[i]}V")
                            self._bms.voltages = voltages
            except ValueError as e:
                Logger().error(f"Failed to parse data from core: {e!r}")
                traceback.print_exc()


    @property
    def controller(self) -> RawKeyValueSerialController:
        return self._controller

    @property
    def state(self) -> CoreStatus:
        return self._status

    @property
    def drivebase(self) -> KevinbotDrivebase:
        return KevinbotDrivebase(self)

    @property
    def bms(self) -> KevinbotBms:
        return self._bms
