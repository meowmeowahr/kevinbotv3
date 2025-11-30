import dataclasses


@dataclasses.dataclass
class AngleState:
    rads: float

@dataclasses.dataclass
class VelocityState:
    rad_s: float

@dataclasses.dataclass
class CurrentState:
    i_q: float
    i_d: float

@dataclasses.dataclass
class VoltageState:
    v_q: float
    v_d: float
    v_bemf: float
    v_in: float

@dataclasses.dataclass
class PhaseStates:
    u_a: float
    u_b: float
    u_c: float
    i_a: float
    i_b: float
    i_c: float

@dataclasses.dataclass
class MotorSignals:
    target: float = 0.0
    angle: AngleState = dataclasses.field(default_factory=lambda: AngleState(0.0))
    velocity: VelocityState = dataclasses.field(default_factory=lambda: VelocityState(0.0))
    currents: CurrentState = dataclasses.field(default_factory=lambda: CurrentState(0.0, 0.0))
    voltages: VoltageState = dataclasses.field(default_factory=lambda: VoltageState(0.0, 0.0, 0.0, 0.0))
    phases: PhaseStates = dataclasses.field(default_factory=lambda: PhaseStates(0.0, 0.0, 0.0, 0.0, 0.0, 0.0))
