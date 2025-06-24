from pydantic import BaseModel


class CoreSettings(BaseModel):
    port: str
    baud: int
    timeout: float
    tick: float


class ControllerSettings(BaseModel):
    power_deadband: float
    steer_deadband: float


class TTSSettings(BaseModel):
    model: str
    executable: str


class KevinbotSettings(BaseModel):
    core: CoreSettings
    controller: ControllerSettings
    tts: TTSSettings


class SettingsSchema(BaseModel):
    kevinbot: KevinbotSettings
