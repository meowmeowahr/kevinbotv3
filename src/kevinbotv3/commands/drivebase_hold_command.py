from kevinbotlib.logger import Logger
from kevinbotlib.scheduler import Command

from kevinbotv3.core import KevinbotDrivebase


class DrivebaseHoldCommand(Command):
    def __init__(self, drivebase: KevinbotDrivebase, hold: bool) -> None:
        super().__init__()

        self.drivebase = drivebase
        self.hold = hold

    def init(self) -> None:
        super().init()
        Logger().debug(f"Set drivebase hold: {self.hold}")
        self.drivebase.set_hold(self.hold)

    def execute(self) -> None:
        return super().execute()

    def end(self) -> None:
        return super().end()

    def finished(self) -> bool:
        return True
