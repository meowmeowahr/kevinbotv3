import datetime
import threading
from functools import partial

import tomli
from kevinbotlib.comm.pipeline import PipelinedCommSetter
from kevinbotlib.comm.request import SetRequest
from kevinbotlib.comm.sendables import (
    FloatSendable,
    IntegerSendable,
    StringSendable,
)
from kevinbotlib.deployment import ManifestParser
from kevinbotlib.hardware.interfaces.serial import RawSerialInterface
from kevinbotlib.joystick import (
    NamedControllerButtons,
    RemoteNamedController,
    LocalNamedController,
    NamedControllerAxis,
    CommandBasedJoystick,
)
from kevinbotlib.logger import Level
from kevinbotlib.metrics import Metric, MetricType
from kevinbotlib.robot import BaseRobot
from kevinbotlib.scheduler import CommandScheduler, Trigger, Command
from kevinbotlib.system import SystemPerformanceData
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
from kevinbotv3.kevinbot_mc.config import MotorConfigurationKey
from kevinbotv3.kevinbot_mc.connection.serial import SerialMotorConnection
from kevinbotv3.kevinbot_mc.connection.sim import SimulatorMotorConnection
from kevinbotv3.kevinbot_mc.controls import (
    MotorControl,
    NeutralControl,
    BrakeControl,
    CoastControl,
    VelocityControl,
)
from kevinbotv3.kevinbot_mc.motor import (
    KevinbotMC,
)
from kevinbotv3.piper import (
    ManagedSpeaker,
    PiperTTSEngine,
)
from kevinbotv3.runtime import Runtime
from kevinbotv3.settings.schema import SettingsSchema
from kevinbotv3.tools.autoinstall import install as autoinstall_tools
from kevinbotv3.util import apply_deadband

class RobotStateChangeCommand(Command):
    def __init__(self, state: bool, robot: BaseRobot):
        self.new = state
        self.robot = robot

    def init(self) -> None:
        self.robot.enabled = self.new

    def execute(self) -> None:
        pass

    def end(self) -> None:
        pass

    def finished(self) -> bool:
        return True

class Kevinbot(BaseRobot):
    def __init__(self):
        super().__init__(["AccelMode", "Teleoperated"], log_level=Level.DEBUG, enable_stderr_logger=True, cycle_time=20, allow_enable_without_console=True, default_opmode="AccelMode")

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

        if not self.IS_SIM:
            self.left_drive = KevinbotMC(SerialMotorConnection(self.settings.kevinbot.drive.left.port, self.settings.kevinbot.drive.left.baud), self)
        else:
            self.left_drive = KevinbotMC(
                SimulatorMotorConnection(
                    "left"
                ),
                self,
            )

        self.left_drive.start()
        self.estop_hooks.append(self.left_drive.e_stop)
        self.left_drive.apply_config(MotorConfigurationKey.STATUS_LED_BRIGHTNESS, self.settings.kevinbot.drive.led_brightness)
        self.left_drive.apply_config(MotorConfigurationKey.DRIVE_MAX_VOLTAGE, self.settings.kevinbot.drive.max_volts)
        self.left_drive.apply_config(MotorConfigurationKey.FOC_MODULATION, self.settings.kevinbot.drive.modulation)
        self.left_drive.apply_config(MotorConfigurationKey.VELOCITY_PID_P, self.settings.kevinbot.drive.kp)
        self.left_drive.apply_config(MotorConfigurationKey.VELOCITY_PID_I, self.settings.kevinbot.drive.ki)
        self.left_drive.apply_config(MotorConfigurationKey.VELOCITY_PID_D, self.settings.kevinbot.drive.kd)
        self.left_drive.apply_config(MotorConfigurationKey.VELOCITY_PID_RAMP, self.settings.kevinbot.drive.kr)
        self.left_drive.flash_save()

        self.left_drive.enable_signal(0x0003)
        self.left_drive.enable_signal(0x0002)

        if not self.IS_SIM:
            self.right_drive = KevinbotMC(SerialMotorConnection(self.settings.kevinbot.drive.right.port, self.settings.kevinbot.drive.right.baud), self)
        else:
            self.right_drive = KevinbotMC(SimulatorMotorConnection("right"), self)

        self.right_drive.start()
        self.estop_hooks.append(self.right_drive.e_stop)
        self.right_drive.apply_config(MotorConfigurationKey.STATUS_LED_BRIGHTNESS, self.settings.kevinbot.drive.led_brightness)
        self.right_drive.apply_config(MotorConfigurationKey.DRIVE_MAX_VOLTAGE, self.settings.kevinbot.drive.max_volts)
        self.right_drive.apply_config(MotorConfigurationKey.FOC_MODULATION, self.settings.kevinbot.drive.modulation)
        self.right_drive.apply_config(MotorConfigurationKey.VELOCITY_PID_P, self.settings.kevinbot.drive.kp)
        self.right_drive.apply_config(MotorConfigurationKey.VELOCITY_PID_I, self.settings.kevinbot.drive.ki)
        self.right_drive.apply_config(MotorConfigurationKey.VELOCITY_PID_D, self.settings.kevinbot.drive.kd)
        self.right_drive.apply_config(MotorConfigurationKey.VELOCITY_PID_RAMP, self.settings.kevinbot.drive.kr)
        self.right_drive.flash_save()

        self.right_drive.enable_signal(0x0003)
        self.right_drive.enable_signal(0x0002)

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

        # self.joystick = RemoteNamedController(self.comm_client, "%ControlConsole/joystick/0")
        self.joystick = LocalNamedController(0)
        self.joystick.start_polling()

        self.command_joystick = CommandBasedJoystick(self.scheduler, self.joystick)

        self.camera = CameraByIndex(self, 0)
        self.camera.set_resolution(1280, 720)
        self.pipeline = EmptyPipeline(self.camera.get_frame)
        self.pipeline_thread = threading.Thread(target=self.vision_loop, daemon=True, name="KevinbotV3.VisionLoop")

        # self.tts_engine = PiperTTSEngine(self.settings.kevinbot.tts.model, self.settings.kevinbot.tts.executable)
        # self.tts = ManagedSpeaker(self.tts_engine)

        self.pipelined_setter = PipelinedCommSetter(self.comm_client)

        self.accel_vel = 0.0

        self.left_control: MotorControl = NeutralControl()
        self.right_control: MotorControl = NeutralControl()

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

        # Trigger(lambda: NamedControllerButtons.Back in self.joystick.get_buttons(), self.scheduler).on_true(
        #     SpeechCommand(self.tts_engine, "This is a test of local on-board Kevinbot AI speech synthesis.")
        # )
        #
        # Trigger(lambda: self.tts.running(), self.scheduler).while_true(
        #     SpeechLightingCommand(self.core.lighting, LightingZone.Base, lambda: Runtime.Leds.brightness)
        # )

        self.command_joystick.start().on_true(
            RobotStateChangeCommand(True, self)
        )

        self.command_joystick.back().on_true(
            RobotStateChangeCommand(False, self)
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
        self.left_drive.request_state_update(enabled)
        self.right_drive.request_state_update(enabled)

        if opmode == "Teleoperated":
            # self.core.drivebase.drive_direction(
            #     -apply_deadband(self.joystick.get_left_stick()[1], self.settings.kevinbot.controller.power_deadband),
            #     -apply_deadband(self.joystick.get_left_stick()[0], self.settings.kevinbot.controller.steer_deadband),
            # )
            # self.core.drivebase.drive_direction(
            #     -apply_deadband(self.joystick.get_triggers()[0]-self.joystick.get_triggers()[1], self.settings.kevinbot.controller.power_deadband),
            #     -apply_deadband(self.joystick.get_left_stick()[0], self.settings.kevinbot.controller.steer_deadband),
            # )
            # Triggers override everything
            if self.joystick.get_trigger_value(NamedControllerAxis.LeftTrigger) > 0.5:
                self.left_control = CoastControl()
                self.right_control = CoastControl()

            elif (
                self.joystick.get_trigger_value(NamedControllerAxis.RightTrigger) > 0.5
            ):
                self.left_control = BrakeControl()
                self.right_control = BrakeControl()

            else:
                # Read single stick
                raw_stick = self.joystick.get_left_stick()

                throttle = apply_deadband(
                    raw_stick[1], self.settings.kevinbot.controller.power_deadband
                )
                turn = -apply_deadband(
                    raw_stick[0], self.settings.kevinbot.controller.steer_deadband
                ) * 0.2

                # Mix for single-stick (arcade) drive
                left_cmd = throttle + turn
                right_cmd = throttle - turn

                # Scale to velocity
                max_vel = self.settings.kevinbot.drive.max_vel
                self.left_control = VelocityControl(left_cmd * max_vel)
                self.right_control = VelocityControl(-(right_cmd * max_vel))

            # Send to hardware
            self.left_drive.set(self.left_control)
            self.right_drive.set(self.right_control)

        elif opmode == "AccelMode":
            # --- CONFIG ---

            accel_rate = self.settings.kevinbot.controller.accel_p

            brake_rate = accel_rate * 3.5

            coast_rate = self.settings.kevinbot.controller.coast_p

            max_vel = self.settings.kevinbot.drive.max_vel

            # --- INPUTS ---

            lt = self.joystick.get_trigger_value(NamedControllerAxis.LeftTrigger)

            rt = self.joystick.get_trigger_value(NamedControllerAxis.RightTrigger)

            reverse_mode = self.joystick.get_button_state(NamedControllerButtons.LeftBumper)

            # Current velocity convention:

            #   forward = negative (e.g., -4.0 m/s)

            #   reverse = positive (e.g., +4.0 m/s)

            # --- ACCELERATION ---

            if lt > 0:
                if reverse_mode:
                    # Accelerate in reverse (positive)

                    self.accel_vel += lt * accel_rate

                else:
                    # Accelerate forward (negative)

                    self.accel_vel -= lt * accel_rate

            # --- BRAKE ONLY (never changes sign past zero) ---

            if rt > 0:
                if self.accel_vel < 0:
                    # moving forward → brake toward 0

                    self.accel_vel = min(0.0, self.accel_vel + rt * brake_rate)

                elif self.accel_vel > 0:
                    # moving backward → brake toward 0

                    self.accel_vel = max(0.0, self.accel_vel - rt * brake_rate)

                # if exactly zero, nothing changes

            # --- NATURAL COAST (no triggers pressed) ---

            if lt == 0 and rt == 0:
                if self.accel_vel < 0:
                    self.accel_vel = min(0.0, self.accel_vel + coast_rate)

                elif self.accel_vel > 0:
                    self.accel_vel = max(0.0, self.accel_vel - coast_rate)

            # --- CLAMP within max forward/reverse speeds ---

            self.accel_vel = max(-max_vel, min(max_vel, self.accel_vel))

            # --- TURN INPUT ---

            turn = (
                -apply_deadband(
                    self.joystick.get_left_stick()[0],
                    self.settings.kevinbot.controller.steer_deadband,
                )
                * 0.2
            ) * self.accel_vel

            # --- MIX (arcade drive) ---

            left_cmd = self.accel_vel - turn
            right_cmd = self.accel_vel + turn

            # --- SEND COMMANDS ---

            self.left_control = VelocityControl(left_cmd)

            self.right_control = VelocityControl(-right_cmd)

            self.left_drive.set(self.left_control)

            self.right_drive.set(self.right_control)

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
                "dashboard/DriveTargetLeft",
                FloatSendable(value=-self.left_drive._current_control.target),
            ),
            SetRequest(
                "dashboard/DriveTargetRight",
                FloatSendable(value=self.right_drive._current_control.target),
            ),
            SetRequest(
                "dashboard/DriveSpeedLeft",
                FloatSendable(value=-self.left_drive.signals.velocity.rad_s),
            ),
            SetRequest(
                "dashboard/DriveSpeedRight",
                FloatSendable(value=self.right_drive.signals.velocity.rad_s),
            ),
            SetRequest(
                "dashboard/DriveAngleLeft",
                FloatSendable(value=-self.left_drive.signals.angle.rads),
            ),
            SetRequest(
                "dashboard/DriveAngleRight",
                FloatSendable(value=self.right_drive.signals.angle.rads),
            ),
            SetRequest(
                "dashboard/Battery",
                FloatSendable(value=self.core.bms.voltages[0]),
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
