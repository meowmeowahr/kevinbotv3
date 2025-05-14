def apply_deadband(value: float, deadband: float) -> float:
    if abs(value) < deadband:
        return 0.0
    sign = 1 if value > 0 else -1
    adjusted = (abs(value) - deadband) / (1.0 - deadband)
    return sign * adjusted
