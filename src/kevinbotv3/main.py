import tomli
from kevinbotlib.hardware.interfaces.serial import RawSerialInterface
from kevinbotlib.joystick import LocalXboxController, XboxControllerButtons
from kevinbotlib.logger import Level
from kevinbotlib.metrics import Metric, MetricType
from kevinbotlib.robot import BaseRobot
from kevinbotlib.scheduler import CommandScheduler, Trigger
from kevinbotlib.vision import (
    CameraByIndex,
    EmptyPipeline,
    VisionCommUtils,
)

from kevinbotv3 import __about__
from kevinbotv3.commands.drivebase_hold_command import DrivebaseHoldCommand
from kevinbotv3.core import KevinbotCore
from kevinbotv3.settings.schema import SettingsSchema
from kevinbotv3.util import apply_deadband


class Kevinbot(BaseRobot):
    def __init__(self):
        super().__init__(["Teleoperated"], log_level=Level.DEBUG)

        # Read toml settings
        with open("deploy/options.toml", "rb") as f:
            settings = tomli.load(f)
        self.settings = SettingsSchema(**settings)

        BaseRobot.add_basic_metrics(self, 2)
        VisionCommUtils.init_comms_types(self.comm_client)
        self.metrics.add("kevinbot.version", Metric("Kevinbot Code Version", __about__.__version__))

        self.scheduler = CommandScheduler()

        self.core = KevinbotCore(
            RawSerialInterface(
                self.settings.kevinbot.core.port,
                self.settings.kevinbot.core.baud,
                timeout=self.settings.kevinbot.core.timeout,
            ),
            self.settings.kevinbot.core.tick,
        )
        self.metrics.add("kevinbot.core.linked", Metric("Core Linked", self.core.state.linked, kind=MetricType.BooleanType))
        self.metrics.add("kevinbot.core.enabled", Metric("Core Enabled", self.core.state.enabled, kind=MetricType.BooleanType))
        for batt in range(self.core.battery_count):
            self.metrics.add(f"kevinbot.battery.{batt}.voltage", Metric(f"Battery {batt} Voltage", 0.0))

        # self.joystick = RemoteXboxController(self.comm_client, "%ControlConsole/joystick/0")
        self.joystick = LocalXboxController(0)
        self.joystick.start_polling()

        self.camera = CameraByIndex(0)
        self.camera.set_resolution(1920, 1080)
        self.pipeline = EmptyPipeline(self.camera.get_frame)

    def robot_start(self) -> None:
        super().robot_start()

        self.telemetry.info(f"Welcome to Kevinbot v3 (Code version {__about__.__version__})")

        Trigger(lambda: XboxControllerButtons.LeftBumper in self.joystick.get_buttons(), self.scheduler).on_true(DrivebaseHoldCommand(self.core.drivebase, False))
        Trigger(lambda: XboxControllerButtons.RightBumper in self.joystick.get_buttons(), self.scheduler).on_true(DrivebaseHoldCommand(self.core.drivebase, True))

        self.core.begin()

    def robot_periodic(self, opmode: str, enabled: bool):  # noqa: FBT001
        super().robot_periodic(opmode, enabled)

        self.metrics.update("kevinbot.core.linked", self.core.state.linked)
        self.metrics.update("kevinbot.core.enabled", self.core.state.enabled)
        for batt in range(self.core.battery_count):
            self.metrics.update(f"kevinbot.battery.{batt}.voltage", self.core.bms.voltages[batt])

        self.core.request_state_update(enabled)

        self.core.drivebase.drive_direction(
            -apply_deadband(self.joystick.get_left_stick()[1], self.settings.kevinbot.controller.power_deadband),
            -apply_deadband(self.joystick.get_left_stick()[0], self.settings.kevinbot.controller.steer_deadband),
        )

        # ok, frame = self.pipeline.run()
        # if ok:
        #     encoded = FrameEncoders.encode_jpg(frame, 100)
        #     self.comm_client.send(
        #         "streams/camera0",
        #         MjpegStreamSendable(value=encoded, quality=100, resolution=frame.shape[:2]),
        #     )

        self.scheduler.iterate()

    def robot_end(self) -> None:
        super().robot_end()

        self.core.unlink()
