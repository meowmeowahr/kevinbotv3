import abc
from collections.abc import Callable
from typing import Any

from kevinbotv3.kevinbot_mc.protocol import TransactionData, TransactionResult


class AbstractMotorConnection(abc.ABC):
    @abc.abstractmethod
    def start(self):
        pass

    @abc.abstractmethod
    def stop(self):
        pass

    @abc.abstractmethod
    def execute(self, control: int, data: TransactionData, retry: int = 3, timeout: float = 3.0) -> TransactionResult:
        pass

    @abc.abstractmethod
    def add_unsolicited_callback(self, callback: Callable[[int, TransactionData], Any]) -> None:
        pass

    @abc.abstractmethod
    def add_signal_callback(self, callback: Callable[[int, TransactionData], Any]) -> None:
        pass

    @property
    def is_open(self):
        return False

    @property
    def name(self):
        return "Connection"