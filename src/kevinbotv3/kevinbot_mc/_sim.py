from typing import Any, Dict

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QWidget,
    QToolBox,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QHBoxLayout,
    QComboBox,
    QDoubleSpinBox,
    QGroupBox,
    QFormLayout,
    QSizePolicy,
)

from kevinbotlib.simulator.windowview import WindowView, register_window_view
from kevinbotlib.robot import BaseRobot


def _fmt(v: Any) -> str:
    if v is None:
        return "—"
    try:
        if isinstance(v, float):
            return f"{v:.4f}"
        return str(v)
    except Exception:
        return str(v)


class MotorControlView(QWidget):
    """
    A lightweight control/status view for a single simulated motor.
    This view exposes:
      - basic status (enabled, control mode, target)
      - a few control widgets (enable/disable, mode, target, apply)
      - a readout of common signals (angle, velocity, currents, voltages, phases)
    The view accepts payload dictionaries with the following shapes (examples):
      {"type": "status", "name": "Motor 1", "enabled": True}
      {"type": "control", "name": "Motor 1", "mode": "velocity", "target": 1.23}
      {"type": "signals", "name": "Motor 1", "angle": 0.12, "velocity": 3.4, "currents": {"i_q": 0.1, "i_d": 0.2}}
    When user interacts with controls, the view will attempt to send messages back to the simulator
    using BaseRobot.instance.simulator.send_to_window(...) when a simulator is available.
    """

    def __init__(self, parent: QWidget, name: str):
        super().__init__(parent=parent)
        self._name = name

        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)

        # Header
        self.header = QLabel(f"<b>{self._name}</b>")
        self.header.setContentsMargins(2, 2, 2, 6)

        # Status group
        self.status_group = QGroupBox("Status")
        status_layout = QFormLayout()
        self.enabled_label = QLabel("Unknown")
        self.mode_label = QLabel("Unknown")
        self.target_label = QLabel("—")
        status_layout.addRow("Enabled:", self.enabled_label)
        status_layout.addRow("Control Mode:", self.mode_label)
        status_layout.addRow("Target:", self.target_label)
        self.status_group.setLayout(status_layout)

        # Controls group
        self.controls_group = QGroupBox("Controls")
        controls_layout = QHBoxLayout()
        self.enable_button = QPushButton("Enable")
        self.enable_button.setCheckable(True)
        self.mode_combo = QComboBox()
        # A conservative list of modes; simulator side can interpret string values.
        self.mode_combo.addItems(
            ["Unknown", "OpenLoop", "Velocity", "Position", "Current"]
        )
        self.target_spin = QDoubleSpinBox()
        self.target_spin.setRange(-1e6, 1e6)
        self.target_spin.setSingleStep(0.1)
        self.apply_button = QPushButton("Apply")
        controls_layout.addWidget(self.enable_button)
        controls_layout.addWidget(QLabel("Mode:"))
        controls_layout.addWidget(self.mode_combo)
        controls_layout.addWidget(QLabel("Target:"))
        controls_layout.addWidget(self.target_spin)
        controls_layout.addWidget(self.apply_button)
        self.controls_group.setLayout(controls_layout)

        # Signals group
        self.signals_group = QGroupBox("Signals")
        signals_layout = QFormLayout()
        self.angle_label = QLabel("—")
        self.velocity_label = QLabel("—")
        self.i_q_label = QLabel("—")
        self.i_d_label = QLabel("—")
        self.v_q_label = QLabel("—")
        self.v_d_label = QLabel("—")
        self.v_in_label = QLabel("—")
        self.u_a_label = QLabel("—")
        self.i_a_label = QLabel("—")
        signals_layout.addRow("Angle (rad):", self.angle_label)
        signals_layout.addRow("Velocity (rad/s):", self.velocity_label)
        signals_layout.addRow("i_q (A):", self.i_q_label)
        signals_layout.addRow("i_d (A):", self.i_d_label)
        signals_layout.addRow("v_q (V):", self.v_q_label)
        signals_layout.addRow("v_d (V):", self.v_d_label)
        signals_layout.addRow("v_in (V):", self.v_in_label)
        signals_layout.addRow("u_a (V):", self.u_a_label)
        signals_layout.addRow("i_a (A):", self.i_a_label)
        self.signals_group.setLayout(signals_layout)

        # Combine everything
        main_layout = QVBoxLayout(self)
        main_layout.addWidget(self.header)
        main_layout.addWidget(self.status_group)
        main_layout.addWidget(self.controls_group)
        main_layout.addWidget(self.signals_group)
        main_layout.addStretch(1)

        # Wiring
        self.enable_button.clicked.connect(self._on_toggle_enabled)
        self.apply_button.clicked.connect(self._on_apply)
        self.mode_combo.currentTextChanged.connect(self._on_mode_changed)

    # ---- UI -> Simulator helpers ------------------------------------------------
    def _send_to_sim(self, payload: Dict[str, Any]) -> None:
        if BaseRobot.instance and getattr(BaseRobot.instance, "simulator", None):
            try:
                BaseRobot.instance.simulator.send_to_window("kevinbotmc.motor", payload)
            except Exception:
                # The simulator may not accept every message; swallow errors here to avoid blocking UI.
                pass

    def _on_toggle_enabled(self, pressed: bool) -> None:
        # send a request to change enabled state
        payload = {
            "type": "request_enabled",
            "name": self._name,
            "value": bool(pressed),
        }
        self._send_to_sim(payload)
        # reflect tentative state in UI immediately
        self.enabled_label.setText("Enabled" if pressed else "Disabled")

    def _on_mode_changed(self, mode: str) -> None:
        payload = {"type": "request_mode", "name": self._name, "mode": mode}
        self._send_to_sim(payload)

    def _on_apply(self) -> None:
        target = float(self.target_spin.value())
        mode = str(self.mode_combo.currentText())
        payload = {
            "type": "request_apply",
            "name": self._name,
            "mode": mode,
            "target": target,
        }
        self._send_to_sim(payload)

    # ---- External updates -----------------------------------------------------
    def update_payload(self, payload: Dict[str, Any]) -> None:
        # Handle a few common update types in a forgiving way.
        t = payload.get("type")
        if t in ("status", "enabled", "state"):
            enabled = payload.get("enabled")
            if enabled is not None:
                self.enabled_label.setText("Enabled" if enabled else "Disabled")
                self.enable_button.setChecked(bool(enabled))
                self.enable_button.setText("Disable" if enabled else "Enable")
        if t in ("control", "status", "control_update", "request"):
            mode = payload.get("mode")
            if mode is not None:
                # try to set mode in combo if present
                idx = self.mode_combo.findText(str(mode))
                if idx >= 0:
                    self.mode_combo.setCurrentIndex(idx)
                else:
                    # unknown mode: add it (non-destructive)
                    self.mode_combo.addItem(str(mode))
                    self.mode_combo.setCurrentText(str(mode))
                self.mode_label.setText(str(mode))
            target = payload.get("target")
            if target is not None:
                try:
                    self.target_spin.setValue(float(target))
                except Exception:
                    pass
                self.target_label.setText(_fmt(target))
        if t in ("signals", "signal", "status"):
            # top-level signals
            if "angle" in payload:
                self.angle_label.setText(_fmt(payload["angle"]))
            if "velocity" in payload:
                self.velocity_label.setText(_fmt(payload["velocity"]))
            # nested maps
            currents = payload.get("currents") or {}
            if isinstance(currents, dict):
                if "i_q" in currents:
                    self.i_q_label.setText(_fmt(currents["i_q"]))
                if "i_d" in currents:
                    self.i_d_label.setText(_fmt(currents["i_d"]))
            voltages = payload.get("voltages") or {}
            if isinstance(voltages, dict):
                if "v_q" in voltages:
                    self.v_q_label.setText(_fmt(voltages["v_q"]))
                if "v_d" in voltages:
                    self.v_d_label.setText(_fmt(voltages["v_d"]))
                if "v_in" in voltages:
                    self.v_in_label.setText(_fmt(voltages["v_in"]))
            phases = payload.get("phases") or {}
            if isinstance(phases, dict):
                if "u_a" in phases:
                    self.u_a_label.setText(_fmt(phases["u_a"]))
                if "i_a" in phases:
                    self.i_a_label.setText(_fmt(phases["i_a"]))


@register_window_view("kevinbotmc.motor")
class MotorWindowView(WindowView):
    def __init__(self):
        super().__init__()

        self.widget = QToolBox()
        self.widget.setContentsMargins(4, 4, 4, 4)

        # keep track of views by motor name
        self._views: dict[str, MotorControlView] = {}

    @property
    def title(self):
        return "KevinbotMC Motors"

    def icon(self, dark_mode: bool) -> QIcon:
        return super().icon(dark_mode)

    def generate(self) -> QWidget:
        return self.widget

    def update(self, payload: Any) -> None:
        # The payload is expected to include a `type` and usually a `name`.
        # `create` will make a new tab. Other types will be routed to the
        # appropriate MotorControlView based on the `name` field.
        t = payload.get("type")
        if t == "create":
            name = payload.get("name", "Unknown")
            # avoid creating duplicates
            if name in self._views:
                return
            view = MotorControlView(self.widget, name)
            view.update_payload({"type": "create", "name": name})
            self._views[name] = view
            self.widget.addItem(view, name)
            return

        # For all other payloads, route to the correct view if present
        name = payload.get("name")
        if name and name in self._views:
            try:
                self._views[name].update_payload(payload)
            except Exception:
                # keep simulator UI robust; don't crash on malformed payloads
                pass
            return

        # If no name provided, attempt to broadcast to all views
        for v in self._views.values():
            try:
                v.update_payload(payload)
            except Exception:
                pass
