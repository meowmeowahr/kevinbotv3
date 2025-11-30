import abc
import dataclasses
import threading
import time
import uuid
from dataclasses import field

import cbor2
import numpy as np
import semver
from kevinbotlib.logger import Logger
from kevinbotlib.robot import BaseRobot

from kevinbotv3.kevinbot_mc._sim import MotorWindowView
from kevinbotv3.kevinbot_mc.config import MotorConfigurationKey
from kevinbotv3.kevinbot_mc.connection.abstract import AbstractMotorConnection
from kevinbotv3.kevinbot_mc.controls import UnknownControl, MotorControl
from kevinbotv3.kevinbot_mc.protocol import (
    EmptyTransactionData,
    StringTransactionData,
    UnsignedIntegerTransactionData,
    TransactionStatusCodes,
    BooleanTransactionData,
    FloatTransactionData,
    PackedTransactionData,
    TransactionData,
    MAX_VERSION,
)
from kevinbotv3.kevinbot_mc.signals import MotorSignals


class MotorInitializationFault(RuntimeError):
    pass

class MotorCommandFault(RuntimeError):
    pass


class KevinbotMC:
    def __init__(self, connection: AbstractMotorConnection, robot: BaseRobot):
        self.connection = connection
        self.robot = robot
        self.connection.add_signal_callback(self.signal_handler)

        self._name = "Unknown Motor"
        self._fw_version: semver.Version | None = None

        self._watchdog_interval: int | None = None
        self._watchdog_thread: threading.Thread | None = None

        self._enabled = False

        self._current_control = UnknownControl()

        self._signals = MotorSignals()

    def _watchdog_feeder(self):
        while self.connection.is_open:
            try:
                if self._watchdog_interval:
                    resp = self.connection.execute(0x0003, EmptyTransactionData())
                    if resp.status != TransactionStatusCodes.OK:
                        Logger().warning(f"Failed to feed watchdog, got {resp.status}")
                time.sleep(self._watchdog_interval / 2000)
            except TimeoutError as e:
                Logger().error(f"Failed to feed watchdog: {e!r}")

    def start(self):

        if self.robot.IS_SIM and self.robot.simulator:
            view = MotorWindowView
            if "kevinbotmc.motor" not in self.robot.simulator.windows:
                self.robot.simulator.add_window("kevinbotmc.motor", view)
            self.connection.start()
        else:
            self.connection.start()

            # name check
            name_transaction = self.connection.execute(0x7FF8, EmptyTransactionData())
            if not isinstance(name_transaction.data, StringTransactionData):
                raise MotorInitializationFault(f"User-defined name transaction didn't return the correct data, expected StringTransactionData, got {type(name_transaction.data)}")
            Logger().debug(f"Initializing new motor: {name_transaction.data.value}")
            self._name = name_transaction.data.value

            # fw check
            fw_transaction = self.connection.execute(0x7FFC, EmptyTransactionData())
            if not isinstance(fw_transaction.data, StringTransactionData):
                raise MotorInitializationFault(f"Firmware version transaction didn't return the correct data, expected StringTransactionData, got {type(fw_transaction.data)} with {fw_transaction.status}")
            Logger().debug(f"{self.name} : Firmware Version : {fw_transaction.data.value}")
            self._fw_version = semver.Version.parse(fw_transaction.data.value)

            # watchdog check
            watchdog_transaction = self.connection.execute(0x4000, EmptyTransactionData())
            if not isinstance(watchdog_transaction.data, UnsignedIntegerTransactionData):
                raise MotorInitializationFault(f"Watchdog timeout transaction didn't return the correct data, expected UnsignedIntegerTransactionData, got {fw_transaction.data.value} with {fw_transaction.status}")
            Logger().debug(f"{self.name} : Device Watchdog Timeout : {watchdog_transaction.data.value}")
            self._watchdog_interval = watchdog_transaction.data.value

            if MAX_VERSION < self._fw_version:
                self.stop()
                raise MotorInitializationFault(f"Motor firmware for {self.name} is higher than the maximum supported version for this library ({self._fw_version}). Either upgrade KevinbotMCLib, or downgrade this motor.")

            if not self._watchdog_thread or not self._watchdog_thread.is_alive():
                self._watchdog_thread = threading.Thread(target=self._watchdog_feeder, daemon=True, name=f"KevinbotMC.Watchdog.{self.connection.name}")
                self._watchdog_thread.start()

    def stop(self):
        self.connection.stop()

    def e_stop(self):
        return self.connection.execute(0x0002, EmptyTransactionData()).status == TransactionStatusCodes.OK

    def disable(self):
        resp = self.connection.execute(0x0004, BooleanTransactionData(False))
        if not isinstance(resp.data, BooleanTransactionData) or not resp.status == TransactionStatusCodes.OK:
            Logger().error(f"Failed to disable motor, got {resp}")
            return None
        self._enabled = resp.data.value
        return self._enabled

    def enable(self):
        resp = self.connection.execute(0x0004, BooleanTransactionData(True))
        if not isinstance(resp.data, BooleanTransactionData) or not resp.status == TransactionStatusCodes.OK:
            Logger().error(f"Failed to enable motor, got {resp}")
            return None
        self._enabled = resp.data.value
        return self._enabled

    def set(self, control: MotorControl):
        if not self.robot.IS_SIM:
            if not isinstance(control, type(self._current_control)):
                control_transaction = self.connection.execute(0x0006, UnsignedIntegerTransactionData(control.index, 1))
                if not isinstance(control_transaction.data, UnsignedIntegerTransactionData):
                    raise MotorCommandFault(f"Control mode transaction didn't return the correct data, expected UnsignedIntegerTransactionData, got {type(control_transaction.data)}")
                Logger().trace(f"{self.name} : New Control Mode : {control_transaction.data.value}")

            if not control.target == self._current_control.target:
                target_transaction = self.connection.execute(0x0005, FloatTransactionData(control.target))
                if not isinstance(target_transaction.data, FloatTransactionData):
                    raise MotorCommandFault(f"Control target transaction didn't return the correct data, expected FloatTransactionData, got {type(target_transaction.data)}")
                Logger().trace(f"{self.name} : New Target : {target_transaction.data.value}")

            if control != self._current_control:
                apply_transaction = self.connection.execute(0x0007, EmptyTransactionData())
                if not isinstance(apply_transaction.data, EmptyTransactionData):
                    raise MotorCommandFault(f"Control apply transaction didn't return the correct data, expected UnsignedIntegerTransactionData, got {type(apply_transaction.data)}")
        self._current_control = control
        self.signals.target = control.target

    def apply_config(self, key: MotorConfigurationKey, value: str | float | int):
        if isinstance(value, float):
            value = float(np.float32(value))
        if not self.robot.IS_SIM:
            transaction = self.connection.execute(0x2002, PackedTransactionData({key: value}))
            if not transaction.status == TransactionStatusCodes.OK:
                raise MotorCommandFault(f"Failed to apply configuration, got {transaction}. Your firmware may not support this setting.")

    def flash_save(self):
        transaction = self.connection.execute(0x2005, EmptyTransactionData())
        if not self.robot.IS_SIM:
            if not transaction.status == TransactionStatusCodes.OK:
                raise MotorCommandFault(f"Failed to save configuration, got {transaction}")

    def request_state_update(self, new_state: bool):
        if new_state != self._enabled:
            if new_state:
                self.enable()
            else:
                self.disable()

    def signal_handler(self, word: int, data: TransactionData):
        handlers = {
            0x0002: lambda v: setattr(self.signals.angle, "rads", v),
            0x0003: lambda v: setattr(self.signals.velocity, "rad_s", v),
            0x0004: lambda v: setattr(self.signals.currents, "i_q", v),
            0x0005: lambda v: setattr(self.signals.currents, "i_d", v),
            0x0006: lambda v: setattr(self.signals.voltages, "v_q", v),
            0x0007: lambda v: setattr(self.signals.voltages, "v_d", v),
            0x0008: lambda v: setattr(self.signals.voltages, "v_bemf", v),
            0x0009: lambda v: setattr(self.signals.voltages, "v_in", v),
            0x000A: lambda v: setattr(self.signals.phases, "u_a", v),
            0x000B: lambda v: setattr(self.signals.phases, "u_b", v),
            0x000C: lambda v: setattr(self.signals.phases, "u_c", v),
            0x000D: lambda v: setattr(self.signals.phases, "i_a", v),
            0x000E: lambda v: setattr(self.signals.phases, "i_b", v),
            0x000F: lambda v: setattr(self.signals.phases, "i_c", v),
        }

        if word not in handlers:
            Logger().error(f"Unknown signal word: {word}")
            return

        if not isinstance(data, FloatTransactionData):
            Logger().error(
                f"Got invalid data for signal {word}, got {type(data)}, expected FloatTransactionData"
            )
            return

        handlers[word](data.value)

    def enable_signal(self, signal_id: int):
        transaction = self.connection.execute(0x3002, UnsignedIntegerTransactionData(signal_id, 2))

        if not self.robot.IS_SIM:
            if not transaction.status == TransactionStatusCodes.OK:
                raise MotorCommandFault(f"Failed to enable signal, got {transaction}")

    @property
    def name(self):
        return self._name

    @property
    def enabled(self):
        return self._enabled

    @property
    def signals(self):
        return self._signals
