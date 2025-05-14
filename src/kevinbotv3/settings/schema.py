from pydantic import BaseModel


class CoreSettings(BaseModel):
    port: str
    baud: int
    timeout: float
    tick: float


class ControllerSettings(BaseModel):
    power_deadband: float
    steer_deadband: float


class KevinbotSettings(BaseModel):
    core: CoreSettings
    controller: ControllerSettings


class SettingsSchema(BaseModel):
    kevinbot: KevinbotSettings
