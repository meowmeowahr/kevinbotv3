import math
from functools import partial

import tomli
from kevinbotlib.comm import FloatSendable, StringSendable
from kevinbotlib.hardware.interfaces.serial import RawSerialInterface
from kevinbotlib.joystick import (
    RemoteXboxController,
    XboxControllerButtons,
)
from kevinbotlib.logger import Level
from kevinbotlib.metrics import Metric, MetricType
from kevinbotlib.robot import BaseRobot
from kevinbotlib.scheduler import CommandScheduler, Trigger
from kevinbotlib.vision import (
    CameraByIndex,
    EmptyPipeline,
    FrameEncoders,
    MjpegStreamSendable,
    VisionCommUtils,
)

from kevinbotv3 import __about__
from kevinbotv3.commands.drivebase_hold_command import DrivebaseHoldCommand
from kevinbotv3.commands.lighting_commands import (
    FireCommand,
    OffCommand,
    RainbowCommand,
    WhiteCommand,
)
from kevinbotv3.core import KevinbotCore, LightingZone
from kevinbotv3.runtime import Runtime
from kevinbotv3.settings.schema import SettingsSchema
from kevinbotv3.util import apply_deadband


class Kevinbot(BaseRobot):
    def __init__(self):
        super().__init__(["Teleoperated", "Sine"], log_level=Level.DEBUG)

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
        BaseRobot.register_estop_hook(self.core.estop)
        self.metrics.add(
            "kevinbot.core.linked", Metric("Core Linked", self.core.state.linked, kind=MetricType.BooleanType)
        )
        self.metrics.add(
            "kevinbot.core.enabled", Metric("Core Enabled", self.core.state.enabled, kind=MetricType.BooleanType)
        )
        for batt in range(self.core.battery_count):
            self.metrics.add(f"kevinbot.battery.{batt}.voltage", Metric(f"Battery {batt} Voltage", 0.0))
            BaseRobot.add_battery(
                self,
                10,
                21,
                partial(
                    lambda batt: self.core.bms.voltages[batt] if len(self.core.bms.voltages) > batt - 1 else 0.0, batt
                ),
            )

        self.joystick = RemoteXboxController(self.comm_client, "%ControlConsole/joystick/0")
        # self.joystick = LocalXboxController(0)
        self.joystick.start_polling()

        self.camera = CameraByIndex(0)
        self.camera.set_resolution(1280, 720)
        self.pipeline = EmptyPipeline(self.camera.get_frame)

        self.sine_period = 0

    def robot_start(self) -> None:
        super().robot_start()

        self.telemetry.info(f"Welcome to Kevinbot v3 (Code version {__about__.__version__})")

        Trigger(lambda: XboxControllerButtons.LeftBumper in self.joystick.get_buttons(), self.scheduler).on_true(
            DrivebaseHoldCommand(self.core.drivebase, False)
        )
        Trigger(lambda: XboxControllerButtons.RightBumper in self.joystick.get_buttons(), self.scheduler).on_true(
            DrivebaseHoldCommand(self.core.drivebase, True)
        )

        Trigger(lambda: XboxControllerButtons.A in self.joystick.get_buttons(), self.scheduler).on_true(
            WhiteCommand(self.core.lighting, LightingZone.Base, 255)
        )

        Trigger(lambda: XboxControllerButtons.B in self.joystick.get_buttons(), self.scheduler).on_true(
            FireCommand(self.core.lighting, LightingZone.Base, 255)
        )

        Trigger(lambda: XboxControllerButtons.X in self.joystick.get_buttons(), self.scheduler).on_true(
            RainbowCommand(self.core.lighting, LightingZone.Base, 255)
        )

        Trigger(lambda: XboxControllerButtons.Y in self.joystick.get_buttons(), self.scheduler).on_true(
            OffCommand(self.core.lighting, LightingZone.Base)
        )

        self.core.begin()

    def robot_periodic(self, opmode: str, enabled: bool):  # noqa: FBT001
        super().robot_periodic(opmode, enabled)

        self.metrics.update("kevinbot.core.linked", self.core.state.linked)
        self.metrics.update("kevinbot.core.enabled", self.core.state.enabled)
        for batt in range(self.core.battery_count):
            self.metrics.update(f"kevinbot.battery.{batt}.voltage", self.core.bms.voltages[batt])

        self.core.request_state_update(enabled)

        if opmode == "Teleoperated":
            self.core.drivebase.drive_direction(
                -apply_deadband(self.joystick.get_left_stick()[1], self.settings.kevinbot.controller.power_deadband),
                -apply_deadband(self.joystick.get_left_stick()[0], self.settings.kevinbot.controller.steer_deadband),
            )
            # self.core.drivebase.drive_direction(
            #     -apply_deadband(self.joystick.get_triggers()[0]-self.joystick.get_triggers()[1], self.settings.kevinbot.controller.power_deadband),
            #     -apply_deadband(self.joystick.get_left_stick()[0], self.settings.kevinbot.controller.steer_deadband),
            # )

            ok, frame = self.pipeline.run()
            if ok:
                encoded = FrameEncoders.encode_jpg(frame, 75)
                self.comm_client.set(
                    "streams/camera0",
                    MjpegStreamSendable(value=encoded, quality=50, resolution=frame.shape[:2]),
                )
        elif opmode == "Sine":
            self.sine_period += 0.001
            self.core.drivebase.drive_at_power(
                math.sin(self.sine_period),
                math.sin(self.sine_period),
            )

        self.comm_client.set("dashboard/DriveStateLeft", StringSendable(value=self.core.drivebase.states[0].name))
        self.comm_client.set("dashboard/DriveStateRight", StringSendable(value=self.core.drivebase.states[1].name))

        self.comm_client.set("dashboard/DriveSpeedLeft", FloatSendable(value=self.core.drivebase.powers[0]))
        self.comm_client.set("dashboard/DriveSpeedRight", FloatSendable(value=self.core.drivebase.powers[1]))

        self.comm_client.set("dashboard/Battery", FloatSendable(value=self.core.bms.voltages[0]))

        match Runtime.Leds.effect:
            case "white":
                self.comm_client.set("dashboard/LedState", StringSendable(value="#ffffff"))
            case "off":
                self.comm_client.set("dashboard/LedState", StringSendable(value="#000000"))
            case "fire":
                self.comm_client.set("dashboard/LedState", StringSendable(value="#ef8f11"))
            case "rainbow":
                self.comm_client.set("dashboard/LedState", StringSendable(value="#118fef"))

        self.scheduler.iterate()

    def robot_end(self) -> None:
        super().robot_end()

        self.core.unlink()
