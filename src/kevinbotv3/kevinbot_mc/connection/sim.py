from typing import Callable, Any, List

from kevinbotlib.robot import BaseRobot

from kevinbotv3.kevinbot_mc.connection.abstract import AbstractMotorConnection
from kevinbotv3.kevinbot_mc.protocol import (
    TransactionData,
    TransactionResult,
    EmptyTransactionData,
    TransactionStatusCodes,
    StringTransactionData,
    UnsignedIntegerTransactionData,
    BooleanTransactionData,
    FloatTransactionData,
    PackedTransactionData,
)


class SimulatorMotorConnection(AbstractMotorConnection):
    """
    A simple in-memory simulator backend for the motor connection used by the UI.
    This implements a subset of transaction words so the simulated motor can respond
    to the library's initialization and control calls instead of returning NOT_IMPLEMENTED.

    Supported control words (not exhaustive):
      - 0x7FF8 : return motor name (StringTransactionData)
      - 0x7FFC : return firmware version (StringTransactionData)
      - 0x4000 : return watchdog timeout (UnsignedIntegerTransactionData)
      - 0x0003 : watchdog feed (EmptyTransactionData, OK)
      - 0x0002 : e-stop (EmptyTransactionData, OK)
      - 0x0004 : enable/disable (BooleanTransactionData)
      - 0x0005 : set target (FloatTransactionData)
      - 0x0006 : set control mode (UnsignedIntegerTransactionData)
      - 0x0007 : apply (EmptyTransactionData)
      - 0x2002 : apply config (PackedTransactionData -> OK)
      - 0x2005 : flash save (EmptyTransactionData -> OK)
      - 0x3002 : enable signal (UnsignedIntegerTransactionData -> OK)
    """

    def __init__(self, name: str = "Simulated Motor"):
        self._name = name
        self._fw_version = "0.0.1"
        self._watchdog_interval = 1000  # milliseconds
        self._enabled = False
        self._control_index = 0
        self._target = 0.0

        # callbacks
        self._unsolicited: List[Callable[[int, TransactionData], Any]] = []
        self._signal_callbacks: List[Callable[[int, TransactionData], Any]] = []

    def start(self):
        # create the UI tab if a simulator UI is present
        if BaseRobot.instance and getattr(BaseRobot.instance, "simulator", None):
            try:
                BaseRobot.instance.simulator.send_to_window(
                    "kevinbotmc.motor", {"type": "create", "name": self._name}
                )
                # push an initial status update
                BaseRobot.instance.simulator.send_to_window(
                    "kevinbotmc.motor",
                    {
                        "type": "status",
                        "name": self._name,
                        "enabled": self._enabled,
                        "fw_version": self._fw_version,
                        "watchdog": self._watchdog_interval,
                        "mode": self._control_index,
                        "target": self._target,
                    },
                )
            except Exception:
                pass

    def stop(self):
        # nothing to do for the in-memory simulator
        pass

    def execute(
        self, control: int, data: TransactionData, retry: int = 3, timeout: float = 3.0
    ) -> TransactionResult:
        """
        Handle a selection of known control words and return the expected TransactionResult.
        Unknown words return NOT_IMPLEMENTED.
        """
        # Name query
        if control == 0x7FF8:
            return TransactionResult(
                control, StringTransactionData(self._name), TransactionStatusCodes.OK
            )

        # Firmware version query
        if control == 0x7FFC:
            return TransactionResult(
                control,
                StringTransactionData(self._fw_version),
                TransactionStatusCodes.OK,
            )

        # Watchdog timeout query
        if control == 0x4000:
            return TransactionResult(
                control,
                UnsignedIntegerTransactionData(self._watchdog_interval, 4),
                TransactionStatusCodes.OK,
            )

        # Watchdog feed
        if control == 0x0003:
            return TransactionResult(
                control, EmptyTransactionData(), TransactionStatusCodes.OK
            )

        # E-stop
        if control == 0x0002:
            # emulate e-stop by disabling motor
            self._enabled = False
            return TransactionResult(
                control, EmptyTransactionData(), TransactionStatusCodes.OK
            )

        # Enable / Disable
        if control == 0x0004:
            # expect BooleanTransactionData
            if isinstance(data, BooleanTransactionData):
                self._enabled = bool(data.value)
                # notify UI of state change
                try:
                    if BaseRobot.instance and getattr(
                        BaseRobot.instance, "simulator", None
                    ):
                        BaseRobot.instance.simulator.send_to_window(
                            "kevinbotmc.motor",
                            {
                                "type": "status",
                                "name": self._name,
                                "enabled": self._enabled,
                            },
                        )
                except Exception:
                    pass
                return TransactionResult(
                    control,
                    BooleanTransactionData(self._enabled),
                    TransactionStatusCodes.OK,
                )
            else:
                return TransactionResult(
                    control, EmptyTransactionData(), TransactionStatusCodes.INVALID_DATA
                )

        # Set target (float)
        if control == 0x0005:
            if isinstance(data, FloatTransactionData):
                self._target = float(data.value)
                try:
                    if BaseRobot.instance and getattr(
                        BaseRobot.instance, "simulator", None
                    ):
                        BaseRobot.instance.simulator.send_to_window(
                            "kevinbotmc.motor",
                            {
                                "type": "control",
                                "name": self._name,
                                "target": self._target,
                            },
                        )
                except Exception:
                    pass
                return TransactionResult(
                    control,
                    FloatTransactionData(self._target),
                    TransactionStatusCodes.OK,
                )
            else:
                return TransactionResult(
                    control, EmptyTransactionData(), TransactionStatusCodes.INVALID_DATA
                )

        # Set control mode (unsigned int)
        if control == 0x0006:
            if isinstance(data, UnsignedIntegerTransactionData):
                # store index and echo back with same size
                self._control_index = int(data.value)
                return TransactionResult(
                    control,
                    UnsignedIntegerTransactionData(self._control_index, data.size),
                    TransactionStatusCodes.OK,
                )
            else:
                return TransactionResult(
                    control, EmptyTransactionData(), TransactionStatusCodes.INVALID_DATA
                )

        # Apply control
        if control == 0x0007:
            # Nothing special to do in-sim; acknowledge
            try:
                if BaseRobot.instance and getattr(
                    BaseRobot.instance, "simulator", None
                ):
                    BaseRobot.instance.simulator.send_to_window(
                        "kevinbotmc.motor",
                        {
                            "type": "control",
                            "name": self._name,
                            "mode": self._control_index,
                            "target": self._target,
                        },
                    )
            except Exception:
                pass
            return TransactionResult(
                control, EmptyTransactionData(), TransactionStatusCodes.OK
            )

        # Apply packed config
        if control == 0x2002:
            if isinstance(data, PackedTransactionData):
                # pretend we applied config
                return TransactionResult(
                    control, EmptyTransactionData(), TransactionStatusCodes.OK
                )
            else:
                return TransactionResult(
                    control, EmptyTransactionData(), TransactionStatusCodes.INVALID_DATA
                )

        # Flash save
        if control == 0x2005:
            return TransactionResult(
                control, EmptyTransactionData(), TransactionStatusCodes.OK
            )

        # Enable signal (subscribe)
        if control == 0x3002:
            # accept unsigned int specifying signal id
            if isinstance(data, UnsignedIntegerTransactionData):
                # for this simple simulator we'll just acknowledge
                return TransactionResult(
                    control,
                    UnsignedIntegerTransactionData(int(data.value), data.size),
                    TransactionStatusCodes.OK,
                )
            return TransactionResult(
                control, EmptyTransactionData(), TransactionStatusCodes.INVALID_DATA
            )

        # Unknown command
        return TransactionResult(
            control, EmptyTransactionData(), TransactionStatusCodes.NOT_IMPLEMENTED
        )

    def add_unsolicited_callback(
        self, callback: Callable[[int, TransactionData], Any]
    ) -> None:
        if callback not in self._unsolicited:
            self._unsolicited.append(callback)

    def add_signal_callback(
        self, callback: Callable[[int, TransactionData], Any]
    ) -> None:
        if callback not in self._signal_callbacks:
            self._signal_callbacks.append(callback)

    @property
    def is_open(self):
        return True

    @property
    def name(self):
        return self._name
