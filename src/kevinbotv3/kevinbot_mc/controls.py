import abc


class MotorControl(abc.ABC):
    index = -1

    def __init__(self):
        self.target = 0.0

    def __eq__(self, other):
        return self.index == other.index and self.target == other.target

class UnknownControl(MotorControl):
    index = -1

class NeutralControl(MotorControl):
    index = 0

class CoastControl(MotorControl):
    index = 1

class BrakeControl(MotorControl):
    index = 2

class VelocityControl(MotorControl):
    index = 6

    def __init__(self, velocity: float):
        super().__init__()
        self.target = velocity

class TorqueControl(MotorControl):
    index = 5

    def __init__(self, torque: float):
        super().__init__()
        self.target = torque
