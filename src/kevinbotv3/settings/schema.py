from pydantic import BaseModel


class CoreSettings(BaseModel):
    port: str
    baud: int
    timeout: float
    tick: float


class KevinbotSettings(BaseModel):
    core: CoreSettings


class SettingsSchema(BaseModel):
    kevinbot: KevinbotSettings
