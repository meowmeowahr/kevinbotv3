from kevinbotlib.robot import BaseRobot
from kevinbotlib.logger import Level
from kevinbotlib.metrics import Metric

from kevinbotv3 import __about__


class Kevinbot(BaseRobot):
    def __init__(self):
        super().__init__(["Teleoperated"], log_level=Level.DEBUG)

        BaseRobot.add_basic_metrics(self, 2)

        self.metrics.add("kevinbot.version", Metric("Kevinbot Code Version", __about__.__version__))

    def robot_start(self) -> None:
        super().robot_start()

        self.telemetry.info(f"Welcome to Kevinbot v3 (Code version {__about__.__version__})")