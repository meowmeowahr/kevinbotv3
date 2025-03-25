import tomli
from kevinbotlib.hardware.interfaces.serial import RawSerialInterface
from kevinbotlib.logger import Level
from kevinbotlib.metrics import Metric
from kevinbotlib.robot import BaseRobot

from kevinbotv3 import __about__
from kevinbotv3.core import KevinbotCore
from kevinbotv3.settings.schema import SettingsSchema


class Kevinbot(BaseRobot):
    def __init__(self):
        super().__init__(["Teleoperated"], log_level=Level.DEBUG)

        # Read toml settings
        with open("deploy/options.toml", "rb") as f:
            settings = tomli.load(f)
        self.settings = SettingsSchema(**settings)

        BaseRobot.add_basic_metrics(self, 2)
        self.metrics.add("kevinbot.version", Metric("Kevinbot Code Version", __about__.__version__))

        self.core = KevinbotCore(
            RawSerialInterface(
                self.settings.kevinbot.core.port,
                self.settings.kevinbot.core.baud,
                timeout=self.settings.kevinbot.core.timeout,
            ),
            self.settings.kevinbot.core.tick,
        )

    def robot_start(self) -> None:
        super().robot_start()

        self.telemetry.info(f"Welcome to Kevinbot v3 (Code version {__about__.__version__})")

        self.core.begin()
