from pydantic import BaseModel


class CoreSettings(BaseModel):
    port: str
    baud: int
    timeout: float
    tick: float


class ControllerSettings(BaseModel):
    power_deadband: float
    steer_deadband: float
    accel_p: float
    coast_p: float


class DriveMotorSettings(BaseModel):
    port: str
    baud: int

class DriveSettings(BaseModel):
    max_volts: float
    max_vel: float
    led_brightness: int
    kp: float
    ki: float
    kd: float
    kr: float
    modulation: int
    left: DriveMotorSettings
    right: DriveMotorSettings


class TTSSettings(BaseModel):
    model: str
    executable: str


class KevinbotSettings(BaseModel):
    core: CoreSettings
    drive: DriveSettings
    controller: ControllerSettings
    tts: TTSSettings


class SettingsSchema(BaseModel):
    kevinbot: KevinbotSettings
