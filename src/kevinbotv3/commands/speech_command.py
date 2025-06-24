from kevinbotlib.scheduler import Command

from kevinbotv3.piper import BaseTTSEngine


class SpeechCommand(Command):
    def __init__(self, speaker: BaseTTSEngine, text: str):
        super().__init__()
        self.speaker = speaker
        self.text = text

    def init(self):
        self.speaker.speak(self.text)

    def execute(self) -> None:
        super().execute()

    def end(self) -> None:
        super().end()

    def finished(self) -> bool:
        return True
