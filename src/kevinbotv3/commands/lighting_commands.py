from kevinbotlib.logger import Logger
from kevinbotlib.scheduler import Command

from kevinbotv3.core import KevinbotLighting, LightingEffect, LightingZone


class WhiteCommand(Command):
    def __init__(self, lighting: KevinbotLighting, zone: LightingZone, brightness: int = 255) -> None:
        super().__init__()

        self.lighting = lighting
        self.zone = zone
        self.brightness = brightness

    def init(self) -> None:
        super().init()
        Logger().debug(f"Set lighting zone {self.zone} to white")

        self.lighting.set_effect(self.zone, LightingEffect.color1)
        self.lighting.set_color1(self.zone, (255 * (self.brightness // 255), 255 * (self.brightness // 255), 255 * (self.brightness // 255)))

    def execute(self) -> None:
        return super().execute()

    def end(self) -> None:
        return super().end()

    def finished(self) -> bool:
        return True


class FireCommand(Command):
    def __init__(self, lighting: KevinbotLighting, zone: LightingZone, brightness: int = 255) -> None:
        super().__init__()

        self.lighting = lighting
        self.zone = zone
        self.brightness = brightness

    def init(self) -> None:
        super().init()
        Logger().debug(f"Set lighting zone {self.zone} to fire")

        self.lighting.set_effect(self.zone, LightingEffect.fire)
        self.lighting.set_brightness(self.zone, self.brightness)

    def execute(self) -> None:
        return super().execute()

    def end(self) -> None:
        return super().end()

    def finished(self) -> bool:
        return True


class RainbowCommand(Command):
    def __init__(self, lighting: KevinbotLighting, zone: LightingZone, brightness: int = 255) -> None:
        super().__init__()

        self.lighting = lighting
        self.zone = zone
        self.brightness = brightness

    def init(self) -> None:
        super().init()
        Logger().debug(f"Set lighting zone {self.zone} to rainbow")

        self.lighting.set_effect(self.zone, LightingEffect.rainbow)
        self.lighting.set_brightness(self.zone, self.brightness)

    def execute(self) -> None:
        return super().execute()

    def end(self) -> None:
        return super().end()

    def finished(self) -> bool:
        return True
