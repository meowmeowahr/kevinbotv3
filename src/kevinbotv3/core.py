# Kevinbot Core Implementation for KevinbotLib
import time
from threading import Thread

from kevinbotlib.hardware.controllers.keyvalue import RawKeyValueSerialController
from kevinbotlib.hardware.interfaces.serial import RawSerialInterface


class KevinbotCore:
    def __init__(self, interface: RawSerialInterface, heartbeat_interval: float = 1) -> None:
        self._controller = RawKeyValueSerialController(interface, b"=", b"\n")
        self.heartbeat_interval = heartbeat_interval

    def begin(self) -> None:
        """Begin a new connection to the Kevinbot Core (formerly Kevinbot Hardware Core)"""
        self._controller.write(b"connection.start")
        self._controller.write(b"core.errors.clear")
        self._controller.write(b"connection.ok")
        Thread(target=self.heartbeat_loop, daemon=True).start()

    def heartbeat_loop(self):
        while True:
            self._controller.write(b"core.tick")
            time.sleep(self.heartbeat_interval)

    @property
    def controller(self) -> RawKeyValueSerialController:
        return self._controller
