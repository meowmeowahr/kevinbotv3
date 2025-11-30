import json
import os
import subprocess
import sys
import threading
from abc import ABC, abstractmethod
from multiprocessing import Process as _Process
from os import PathLike
from pathlib import Path

import platformdirs
from loguru import logger
from pyaudio import paInt16, PyAudio

from kevinbotv3.audioutils import ShutupPyAudioCtxMgr


def _abslistdir(directory):
    dirpath: str
    for dirpath, _, filenames in os.walk(directory):
        for f in filenames:
            yield os.path.abspath(os.path.join(dirpath, f))


def get_user_piper_model_dir():
    return platformdirs.user_data_dir("kevinbotlib/piper")


def get_system_piper_model_dir():
    return platformdirs.site_config_dir("kevinbotlib/piper")


def get_piper_models_paths(user=True, system=True):  # noqa: FBT002
    if user and system:
        return list(filter(lambda x: x.endswith(".onnx"), _abslistdir(get_user_piper_model_dir()))) + list(
            filter(lambda x: x.endswith(".onnx"), _abslistdir(get_system_piper_model_dir()))
        )
    if user:
        return list(filter(lambda x: x.endswith(".onnx"), _abslistdir(get_user_piper_model_dir())))
    if system:
        return list(filter(lambda x: x.endswith(".onnx"), _abslistdir(get_system_piper_model_dir())))
    msg = "At least one of user or system must be True"
    raise ValueError(msg)


def get_piper_models(user=True, system=True) -> dict[str, str]:  # noqa: FBT002
    """Get the name and directory of all installed models

    Returns:
        dict[str, str]: Name and directory pair
    """

    models = {}
    for model_path in get_piper_models_paths(user, system):
        models[Path(model_path).name.split(".")[0]] = model_path
    return models


class BaseTTSEngine(ABC):
    @abstractmethod
    def speak(self, text: str):
        """Abstract speak method.

        Args:
            text (str): text to synthesize
        """

    def speak_in_background(self, text: str):
        p = _Process(target=self.speak, args=(text,))
        p.start()


class PiperTTSEngine(BaseTTSEngine):
    """
    Text to Speech Engine using rhasspy/Piper, running in the background.
    Sends text to stdin and plays audio from stdout using PyAudio.
    """

    def __init__(self, model: str, executable: PathLike | str) -> None:
        """Constructor for PiperTTSEngine

        Args:
            executable: Piper executable location
            model: Pre-downloaded Piper model
        """
        super().__init__()
        self.executable = str(executable)
        self._model = model
        self._debug = False
        self._piper_process: subprocess.Popen | None = None
        self._stream = None
        self._pyaudio = None
        self._bitrate = None
        self._playing = False
        self._start_piper()

    def _start_piper(self):
        """Start the Piper process in the background and set up PyAudio stream."""
        modelfile = get_piper_models()[self._model]

        # Attempt to retrieve the bitrate
        try:
            with open(modelfile + ".json") as config:
                self._bitrate = int(json.loads(config.read())["audio"]["sample_rate"])
        except (KeyError, json.JSONDecodeError, FileNotFoundError):
            self._bitrate = 22050
            logger.warning("Bitrate config data parsing failure. Assuming bitrate for `medium` quality (22050)")

        # Set up Piper synthesis command
        piper_command = [
            self.executable,
            "--model",
            modelfile,
            "--config",
            modelfile + ".json",
            "--output-raw",
        ]

        # Start Piper process
        self._piper_process = subprocess.Popen(
            piper_command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,  # Unbuffered for real-time processing
        )

        # Initialize PyAudio and stream
        audio = PyAudio()
        self._stream = audio.open(format=paInt16, channels=1, rate=self._bitrate, output=True)

        def player():
            # Read and play audio in chunks
            while True:
                data = self._piper_process.stdout.read(1024)
                if not data:
                    continue
                self._stream.write(data)
                self._playing = False in [b == 0 for b in data]

        threading.Thread(target=player, daemon=True).start()

    @property
    def playing(self) -> bool:
        return self._playing

    def __del__(self):
        """Clean up resources when the object is destroyed."""
        self._cleanup()

    def _cleanup(self):
        """Close the Piper process and PyAudio stream."""
        if self._stream:
            self._stream.stop_stream()
            self._stream.stop()
        if self._pyaudio:
            self._pyaudio.terminate()
        if self._piper_process:
            self._piper_process.terminate()
            try:
                self._piper_process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                self._piper_process.kill()

    @property
    def model(self):
        """Getter for the currently loaded model.

        Returns:
            str: model name
        """
        return self._model

    @model.setter
    def model(self, value: str):
        """Setter for the currently loaded model. Restarts Piper with the new model.

        Args:
            value (str): model name
        """
        self._model = value
        self._cleanup()
        self._start_piper()

    @property
    def models(self) -> list[str]:
        """Get all usable models

        Returns:
            list[str]: List of model names
        """
        return list(get_piper_models().keys())

    def speak(self, text: str):
        """Synthesize the given text using the running Piper process and play it in real-time.

        Args:
            text (str): Text to synthesize
        """
        if not self._piper_process or self._piper_process.poll() is not None:
            logger.warning("Piper process not running. Restarting...")
            self._cleanup()
            self._start_piper()

        if self._piper_process.stdin and self._piper_process.stdout:
            self._piper_process.stdin.write((text + "\n").encode("utf-8"))
            self._playing = True


class ManagedSpeaker:
    """
    Manage speech so that only one string is played. Playing a new string will cancel the previous one.
    """

    def __init__(self, engine: BaseTTSEngine) -> None:
        self.engine = engine
        self.process: _Process | None = None

    def speak(self, text: str):
        """
        Stop any current speech and start a new one.

        Args:
            text (str): Text to synthesize
        """
        self.cancel()
        self.process = _Process(target=self.engine.speak, args=(text,), daemon=True)
        self.process.start()

    def cancel(self):
        """Attempt to cancel the current speech."""
        if self.process and self.process.is_alive():
            self.process.terminate()

    def running(self) -> bool:
        return self.process.is_alive() if self.process else False
