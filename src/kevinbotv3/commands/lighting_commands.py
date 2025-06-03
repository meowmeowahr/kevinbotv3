from typing import Callable

from kevinbotlib.logger import Logger
from kevinbotlib.scheduler import Command

from kevinbotv3.core import KevinbotLighting, LightingEffect, LightingZone
from kevinbotv3.runtime import Runtime


class OffCommand(Command):
    def __init__(self, lighting: KevinbotLighting, zone: LightingZone) -> None:
        super().__init__()

        self.lighting = lighting
        self.zone = zone

    def init(self) -> None:
        super().init()
        Logger().debug(f"Set lighting zone {self.zone} to off")
        Runtime.Leds.effect = "off"

        self.lighting.set_effect(self.zone, LightingEffect.color1)
        self.lighting.set_color1(self.zone, (0, 0, 0))

    def execute(self) -> None:
        return super().execute()

    def end(self) -> None:
        return super().end()

    def finished(self) -> bool:
        return True


class WhiteCommand(Command):
    def __init__(self, lighting: KevinbotLighting, zone: LightingZone, brightness: Callable[[], int]) -> None:
        super().__init__()

        self.lighting = lighting
        self.zone = zone
        self.brightness = brightness

    def init(self) -> None:
        super().init()
        Logger().debug(f"Set lighting zone {self.zone} to white")
        Runtime.Leds.effect = "white"

        self.lighting.set_effect(self.zone, LightingEffect.color1)
        self.lighting.set_color1(
            self.zone, (255 * int(self.brightness() / 255), 255 * int(self.brightness() / 255), 255 * int(self.brightness() / 255))
        )

    def execute(self) -> None:
        return super().execute()

    def end(self) -> None:
        return super().end()

    def finished(self) -> bool:
        return True


class FireCommand(Command):
    def __init__(self, lighting: KevinbotLighting, zone: LightingZone, brightness: Callable[[], int]) -> None:
        super().__init__()

        self.lighting = lighting
        self.zone = zone
        self.brightness = brightness

    def init(self) -> None:
        super().init()
        Logger().debug(f"Set lighting zone {self.zone} to fire")
        Runtime.Leds.effect = "fire"

        self.lighting.set_effect(self.zone, LightingEffect.fire)
        self.lighting.set_brightness(self.zone, self.brightness())

    def execute(self) -> None:
        return super().execute()

    def end(self) -> None:
        return super().end()

    def finished(self) -> bool:
        return True


class RainbowCommand(Command):
    def __init__(self, lighting: KevinbotLighting, zone: LightingZone, brightness: Callable[[], int]) -> None:
        super().__init__()

        self.lighting = lighting
        self.zone = zone
        self.brightness = brightness

    def init(self) -> None:
        super().init()
        Logger().debug(f"Set lighting zone {self.zone} to rainbow")
        Runtime.Leds.effect = "rainbow"

        self.lighting.set_effect(self.zone, LightingEffect.rainbow)
        self.lighting.set_brightness(self.zone, self.brightness())

    def execute(self) -> None:
        return super().execute()

    def end(self) -> None:
        return super().end()

    def finished(self) -> bool:
        return True
