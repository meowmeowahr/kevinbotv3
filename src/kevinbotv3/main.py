import datetime
import math
import threading
from functools import partial

import tomli
from kevinbotlib.comm.pipeline import PipelinedCommSetter
from kevinbotlib.comm.request import SetRequest
from kevinbotlib.comm.sendables import (
    FloatSendable,
    IntegerSendable,
    StringSendable,
    Coord2dSendable,
    Coord2dListSendable,
    Coord3dSendable,
    Pose2dSendable,
)
from kevinbotlib.coord import Coord2d, Coord3d, Pose2d, Angle2d
from kevinbotlib.deployment import ManifestParser
from kevinbotlib.hardware.interfaces.serial import RawSerialInterface
from kevinbotlib.joystick import (
    NamedControllerButtons,
    RemoteNamedController,
    LocalNamedController,
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
from line_profiler import profile

from kevinbotv3 import __about__
from kevinbotv3.commands.drivebase_hold_command import DrivebaseHoldCommand
from kevinbotv3.commands.lighting_commands import (
    FireCommand,
    OffCommand,
    RainbowCommand,
    SpeechLightingCommand,
    WhiteCommand,
)
from kevinbotv3.commands.speech_command import SpeechCommand
from kevinbotv3.core import KevinbotCore, LightingZone
from kevinbotv3.piper import (
    ManagedSpeaker,
    PiperTTSEngine,
)
from kevinbotv3.runtime import Runtime
from kevinbotv3.settings.schema import SettingsSchema
from kevinbotv3.tools.autoinstall import install as autoinstall_tools
from kevinbotv3.util import apply_deadband


class Kevinbot(BaseRobot):
    def __init__(self):
        super().__init__(["Teleoperated", "Sine"], log_level=Level.TRACE, enable_stderr_logger=True, cycle_time=20)

        # Read toml settings
        with open("deploy/options.toml", "rb") as f:
            settings = tomli.load(f)
        self.settings = SettingsSchema(**settings)

        BaseRobot.add_basic_metrics(self, 2)
        VisionCommUtils.init_comms_types(self.comm_client)
        self.metrics.add("kevinbot.version", Metric("Kevinbot Code Version", __about__.__version__))

        self.manifest = ManifestParser().manifest
        if self.manifest:
            self.metrics.add("kevinbot.deploy.tool-version", Metric("DeployTool Version", self.manifest.deploytool))
            self.metrics.add("kevinbot.deploy.robotname", Metric("Robot Name", self.manifest.robot))
            time = datetime.datetime.fromtimestamp(self.manifest.timestamp, datetime.UTC).strftime(
                "%Y-%m-%d %H:%M:%S %Z"
            )
            self.metrics.add("kevinbot.deploy.timestamp", Metric("Deploy Time", time))
            self.metrics.add("kevinbot.deploy.git.branch", Metric("Git Branch", self.manifest.git["branch"]))
            self.metrics.add("kevinbot.deploy.git.commit", Metric("Git Commit", self.manifest.git["commit"]))
            self.metrics.add("kevinbot.deploy.git.tag", Metric("Git Tag", self.manifest.git["tag"]))

        self.scheduler = CommandScheduler()

        self.core = KevinbotCore(
            RawSerialInterface(
                self,
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

        self.joystick = RemoteNamedController(self.comm_client, "%ControlConsole/joystick/0")
        # self.joystick = LocalNamedController(0)
        self.joystick.start_polling()

        self.camera = CameraByIndex(self, 0)
        self.camera.set_resolution(1280, 720)
        self.pipeline = EmptyPipeline(self.camera.get_frame)
        self.pipeline_thread = threading.Thread(target=self.vision_loop, daemon=True, name="KevinbotV3.VisionLoop")

        self.tts_engine = PiperTTSEngine(self.settings.kevinbot.tts.model, self.settings.kevinbot.tts.executable)
        self.tts = ManagedSpeaker(self.tts_engine)

        self.pipelined_setter = PipelinedCommSetter(self.comm_client)

        self.sine_period = 0

    def robot_start(self) -> None:
        super().robot_start()

        self.telemetry.info(f"Welcome to Kevinbot v3 (Code version {__about__.__version__})")

        if not BaseRobot.IS_SIM:
            autoinstall_tools()

        Trigger(lambda: NamedControllerButtons.LeftBumper in self.joystick.get_buttons(), self.scheduler).on_true(
            DrivebaseHoldCommand(self.core.drivebase, False)
        )
        Trigger(lambda: NamedControllerButtons.RightBumper in self.joystick.get_buttons(), self.scheduler).on_true(
            DrivebaseHoldCommand(self.core.drivebase, True)
        )

        Trigger(lambda: NamedControllerButtons.A in self.joystick.get_buttons(), self.scheduler).on_true(
            WhiteCommand(self.core.lighting, LightingZone.Base, lambda: Runtime.Leds.brightness)
        )

        Trigger(lambda: NamedControllerButtons.B in self.joystick.get_buttons(), self.scheduler).on_true(
            FireCommand(self.core.lighting, LightingZone.Base, lambda: Runtime.Leds.brightness)
        )

        Trigger(lambda: NamedControllerButtons.X in self.joystick.get_buttons(), self.scheduler).on_true(
            RainbowCommand(self.core.lighting, LightingZone.Base, lambda: Runtime.Leds.brightness)
        )

        Trigger(lambda: NamedControllerButtons.Y in self.joystick.get_buttons(), self.scheduler).on_true(
            OffCommand(self.core.lighting, LightingZone.Base)
        )

        Trigger(lambda: NamedControllerButtons.Back in self.joystick.get_buttons(), self.scheduler).on_true(
            SpeechCommand(self.tts_engine, "This is a test of local on-board Kevinbot AI speech synthesis.")
        )

        Trigger(lambda: self.tts.running(), self.scheduler).while_true(
            SpeechLightingCommand(self.core.lighting, LightingZone.Base, lambda: Runtime.Leds.brightness)
        )

        self.core.begin()

        self.pipeline_thread.start()

        self.comm_client.set("dashboard/LedBrightness", IntegerSendable(value=Runtime.Leds.brightness))

    def vision_loop(self):
        while True:
            ok, frame = self.pipeline.run()
            if ok:
                encoded = FrameEncoders.encode_jpg(frame, 50)
                self.comm_client.multi_set(
                    [
                        SetRequest(
                            "streams/camera0",
                            MjpegStreamSendable(value=encoded, quality=50, resolution=frame.shape[:2]),
                        ),
                    ]
                )

    @profile
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
        elif opmode == "Sine":
            self.sine_period += 0.001
            self.core.drivebase.drive_at_power(
                math.sin(self.sine_period),
                math.sin(self.sine_period),
            )

        self.pipelined_setter.extend([
            SetRequest(
                "dashboard/DriveStateLeft",
                StringSendable(value=self.core.drivebase.states[0].name),
            ),
            SetRequest(
                "dashboard/DriveStateRight",
                StringSendable(value=self.core.drivebase.states[1].name),
            ),
            SetRequest(
                "dashboard/DriveSpeedLeft",
                FloatSendable(value=self.core.drivebase.powers[0]),
            ),
            SetRequest(
                "dashboard/DriveSpeedRight",
                FloatSendable(value=self.core.drivebase.powers[1]),
            ),
            SetRequest(
                "dashboard/DriveAmpLeft",
                FloatSendable(value=self.core.drivebase.amps[0]),
            ),
            SetRequest(
                "dashboard/DriveAmpRight",
                FloatSendable(value=self.core.drivebase.amps[1]),
            ),
            SetRequest(
                "dashboard/DriveWattLeft",
                FloatSendable(value=self.core.drivebase.watts[0]),
            ),
            SetRequest(
                "dashboard/DriveWattRight",
                FloatSendable(value=self.core.drivebase.watts[1]),
            ),
            SetRequest(
                "dashboard/Battery",
                FloatSendable(value=self.core.bms.voltages[0]),
            ),
            SetRequest(
                "dashboard/Pose/Coord2d",
                Coord2dSendable(value=Coord2d(1, 1))
            ),
            SetRequest(
                "dashboard/Pose/Coord3d",
                Coord3dSendable(value=Coord3d(1, 1, 1))
            ),
            SetRequest(
                "dashboard/Pose/Pose2d",
                Pose2dSendable(value=Pose2d(Coord2d(1, 1), Angle2d(1)))
            ),
            SetRequest(
                "dashboard/Pose/Coord2dList",
                Coord2dListSendable(
                    value=[
                        Coord2d(
                            1 + math.sin(self.sine_period * 10 + i * math.pi / 4),
                            1 + math.sin(self.sine_period * 10  + i * math.pi / 2)
                        )
                        for i in range(6)
                    ]
                )
            ),
        ]
        )
        # self.comm_client.set("dashboard/Cpu", FloatSendable(value=SystemPerformanceData.cpu().total_usage_percent))

        match Runtime.Leds.effect:
            case "white":
                self.pipelined_setter.add(SetRequest("dashboard/LedState", StringSendable(value="#ffffff")))
            case "off":
                self.pipelined_setter.add(SetRequest("dashboard/LedState", StringSendable(value="#000000")))
            case "fire":
                self.pipelined_setter.add(SetRequest("dashboard/LedState", StringSendable(value="#ef8f11")))
            case "rainbow":
                self.pipelined_setter.add(SetRequest("dashboard/LedState", StringSendable(value="#118fef")))

        brightness = self.comm_client.get("dashboard/LedBrightness", IntegerSendable)
        if brightness:
            Runtime.Leds.brightness = brightness.value

        self.pipelined_setter.send()
        self.scheduler.iterate()

    def robot_end(self) -> None:
        super().robot_end()

        self.core.unlink()
